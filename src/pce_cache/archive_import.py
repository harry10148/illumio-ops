from __future__ import annotations

import gzip
import os
import re
import threading
import time
from datetime import date, datetime, timezone

import orjson
from loguru import logger
from sqlalchemy import case, func
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import sessionmaker

from src.pce_cache.models import PceTrafficFlowRaw

_TRAFFIC_FILE = re.compile(r"^traffic-(\d{4}-\d{2}-\d{2})\.jsonl(?:\.gz)?$")

# 同時只允許一個 load 在跑：重建/匯入/聚合期間若第二個 load 進來，會跟第一個
# 搶同一個暫存檔與目標 DB。用 module-level lock + non-blocking acquire，
# 第二個請求立即被擋下（不排隊），呼叫端（web.py）接住 ArchiveLoadBusy 回 409。
_LOAD_LOCK = threading.Lock()


class ArchiveLoadBusy(Exception):
    """另一個 load_archive_review 正在進行中（lock 非阻塞取得失敗）。"""


# 任意位數小數秒（如 .5、.7771234567）：py3.10 的 fromisoformat 只收 3/6 位
# （3.11 起才任意位數），正規化為 6 位以免整列被當解析失敗跳過。
_DT_FRAC_RE = re.compile(r"^(\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2})\.(\d+)(.*)$")


def _parse_dt(s: str) -> datetime:
    """archive ISO 時間戳 → aware UTC datetime。處理結尾 Z、明確 offset、
    以及 naive（早期未帶 offset 的 archive）→ 視為 UTC。"""
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    m = _DT_FRAC_RE.match(s)
    if m:
        s = f"{m.group(1)}.{m.group(2)[:6].ljust(6, '0')}{m.group(3)}"
    dt = datetime.fromisoformat(s)
    dt = dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)
    # Floor 到整秒：archive 查閱把查詢窗設為 MIN(last_detected) 的整秒字串
    # （actions.py 用 strftime("...%SZ")）。若時間戳帶次秒精度，start < earliest
    # 會讓 CacheReader.cover_state 判 partial → fallback 打即時 PCE API，破壞
    # 「archive 查閱只讀 review DB」的不變量。整秒化使該不變量與來源精度無關。
    return dt.replace(microsecond=0)


def _iter_lines(path: str):
    opener = gzip.open if path.endswith(".gz") else open
    try:
        with opener(path, "rb") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    yield line
    except (OSError, EOFError, gzip.BadGzipFile) as exc:
        # 截斷/損壞的封存檔（例如 gzip 輪替中途崩潰產生的半檔）：已讀出的
        # 行照常處理，這裡只記 warning、放棄該檔剩餘部分，讓呼叫端繼續下一檔。
        logger.warning("archive: corrupt/truncated file {}: {}", path, exc)


def _matching_traffic_files(archive_dir: str, start: date, end: date) -> list[str]:
    """回傳 archive_dir 下檔名日期落在 [start, end]（含端點）的 traffic 日檔（排序）。
    依檔名日期挑檔，不開檔讀內容。目錄不存在/不可讀 → 回空清單。"""
    try:
        names = sorted(os.listdir(archive_dir))
    except OSError as exc:
        logger.warning("archive: listdir {} failed: {}", archive_dir, exc)
        return []
    out = []
    for name in names:
        m = _TRAFFIC_FILE.match(name)
        if not m:
            continue
        try:
            file_date = date.fromisoformat(m.group(1))
        except ValueError:
            continue
        if start <= file_date <= end:
            out.append(name)
    return out


class ArchiveImporter:
    """把 archive 的 traffic JSONL 逐行還原成 PceTrafficFlowRaw 灌進指定的 review DB。"""

    _CHUNK = 500

    def __init__(self, archive_dir: str, session_factory: sessionmaker):
        self._dir = archive_dir
        self._sf = session_factory

    def import_range(self, start: date, end: date) -> dict:
        """匯入 [start, end]（含端點）範圍內的 traffic archive 到 review DB。

        回傳形狀不變：{"rows", "files", "skipped", "start", "end"}。F6 起
        `rows` 的語意從「新插入列數」改成「本次匯入被 upsert 的列數」（新插入
        +合併更新皆計入，見 `_flush` docstring）——同一 flow_hash 在較晚的
        export 檔案裡帶著成長後的值再次出現時，不再被當成單純的重複捨棄，
        而是合併進既有列；仍計入 `skipped` 的只剩真正無法解析的列（缺
        必要欄位／時間戳格式非法／raw 為 null）。"""
        from src.report.parsers.api_parser import flatten_flow_record
        files = skipped = rows = 0
        pending: list[dict] = []
        for name in _matching_traffic_files(self._dir, start, end):
            files += 1
            path = os.path.join(self._dir, name)
            for line in _iter_lines(path):
                try:
                    rec = orjson.loads(line)
                except orjson.JSONDecodeError:
                    skipped += 1
                    continue
                raw = rec.get("raw")
                if raw is None:
                    skipped += 1
                    continue
                # 缺 flow_hash / event_time / ingested_at，或時間戳格式非法：
                # 手動編輯、版本差異、部分寫入都可能造成——per-line 容錯，
                # 計入 skipped、continue，不中斷整次匯入。
                try:
                    last_detected = _parse_dt(rec["event_time"])
                    ingested_at = _parse_dt(rec["ingested_at"])
                    # 優先讀頂層 first_detected（新格式，export 端已對稱補上）；
                    # 舊格式 archive 沒有頂層欄位時，才 fallback 回 raw 回推。
                    fd_raw = rec.get("first_detected", "")
                    if not fd_raw:
                        ts_range = raw.get("timestamp_range") or {}
                        fd_raw = raw.get("first_detected") or ts_range.get("first_detected", "")
                    first_detected = _parse_dt(fd_raw) if fd_raw else last_detected
                    flow_hash = rec["flow_hash"]
                except (KeyError, ValueError):
                    skipped += 1
                    continue
                # 與即時 ingest / backfill 一致：預先算好 report_json，維持
                # ix_raw_report_json_null 的「幾乎無 NULL」不變量；flatten 失敗不阻斷。
                try:
                    report_json = orjson.dumps(flatten_flow_record(raw)).decode("utf-8")
                except Exception:  # noqa: BLE001
                    report_json = None
                pending.append({
                    "flow_hash": flow_hash,
                    "src_ip": rec.get("src_ip", ""),
                    "src_workload": rec.get("src_workload"),
                    "dst_ip": rec.get("dst_ip", ""),
                    "dst_workload": rec.get("dst_workload"),
                    "port": rec.get("port") or 0,
                    "protocol": rec.get("protocol", "tcp"),
                    "action": rec.get("action", "unknown"),
                    "flow_count": rec.get("flow_count") or 1,
                    "bytes_in": rec.get("bytes_in") or 0,
                    "bytes_out": rec.get("bytes_out") or 0,
                    "first_detected": first_detected,
                    "last_detected": last_detected,
                    "raw_json": orjson.dumps(raw).decode("utf-8"),
                    "report_json": report_json,
                    "ingested_at": ingested_at,
                })
                if len(pending) >= self._CHUNK:
                    inserted, dup = self._flush(pending)
                    rows += inserted
                    skipped += dup
                    pending = []
        if pending:
            inserted, dup = self._flush(pending)
            rows += inserted
            skipped += dup
        return {"rows": rows, "files": files, "skipped": skipped,
                "start": start.isoformat(), "end": end.isoformat()}

    def _flush(self, chunk: list[dict]) -> tuple[int, int]:
        """500 列/transaction 的 chunked upsert：以 flow_hash 為 unique key。

        F6 前是 on_conflict_do_nothing——同 flow_hash 重複匯出時，後到的列
        （通常帶著 re-pull 後成長的值）被整批丟棄，是 archive 計數低於 live
        cache 的根因之一。現在改成 on_conflict_do_update，volatile 欄位取
        MAX、first_detected 取 MIN（比照 aggregator.py／ingestor_traffic.py
        既有的 GREATEST 語意，對亂序重匯不會縮小、重複匯入同一份 idempotent）：
          - last_detected / bytes_in / bytes_out / flow_count / ingested_at
            取 MAX。
          - first_detected 取 MIN（同 flow_hash 理論上 first_detected 恆等，
            因為 flow_hash 的計算本身就包含 first_detected；取 MIN 只是
            防禦性對齊，不影響正常情況）。
          - raw_json / report_json 取「較新 last_detected 那一側」：CASE WHEN
            excluded.last_detected >= 既有值 THEN 用 excluded 側、否則維持
            既有值——避免舊 export 事後重匯，把新 export 的內容蓋回舊快照。

        SQLite 對同一條 INSERT 陳述式裡的多列會依序套用 upsert（後面的列可以
        conflict 到同陳述式裡前面剛插入的列），所以批內重複 flow_hash 也會
        正確依序合併，不需要額外的 Python 端去重。

        統計語意：回傳值第一項從「新插入列數」改成「本批被 upsert 的列數」
        （新插入+合併更新皆計入，rowcount 已完整涵蓋兩者）；upsert 不會丟列，
        第二項（skipped 差額）理論上恆為 0，保留計算方式只是防禦未來若換成
        會丟列的 upsert 變體。"""
        with self._sf.begin() as s:
            cols = PceTrafficFlowRaw.__table__.c
            base = sqlite_insert(PceTrafficFlowRaw).values(chunk)
            newer = base.excluded.last_detected >= cols.last_detected
            set_ = {
                "last_detected": func.max(cols.last_detected, base.excluded.last_detected),
                "first_detected": func.min(cols.first_detected, base.excluded.first_detected),
                "bytes_in": func.max(cols.bytes_in, base.excluded.bytes_in),
                "bytes_out": func.max(cols.bytes_out, base.excluded.bytes_out),
                "flow_count": func.max(cols.flow_count, base.excluded.flow_count),
                "ingested_at": func.max(cols.ingested_at, base.excluded.ingested_at),
                "raw_json": case((newer, base.excluded.raw_json), else_=cols.raw_json),
                "report_json": case((newer, base.excluded.report_json), else_=cols.report_json),
            }
            stmt = base.on_conflict_do_update(index_elements=["flow_hash"], set_=set_)
            result = s.execute(stmt)
            upserted = result.rowcount
        return upserted, len(chunk) - upserted


def review_db_path(cfg) -> str:
    """review DB 放在 cache db_path 同目錄下，固定檔名。"""
    base = os.path.dirname(os.path.abspath(cfg.db_path))
    return os.path.join(base, "archive_review.sqlite")


def _meta_path(cfg) -> str:
    return review_db_path(cfg) + ".meta.json"


def review_session_factory(cfg):
    """對 review DB 建一個 sessionmaker（短命 engine，不用 process 快取，
    避免 review DB 被重建後抓到舊連線）。

    此函式會被 per-query 呼叫，若用預設 pool（QueuePool）engine 又從不
    dispose，長跑程序會累積連線池與 SQLite FD 直到 GC。用 NullPool 讓
    每個 session 各開各關自己的連線、不留池；讀路徑本就不需連線池。

    schema 只確保一次：_ensure_schema_once 以 db_path 為 key，同一個
    db_path 在本 process 生命週期內只跑一次 init_schema（見下方正確性
    論證）。"""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import NullPool
    from src.pce_cache.schema import _ensure_schema_once
    db_path = review_db_path(cfg)
    engine = create_engine(f"sqlite:///{db_path}", poolclass=NullPool)
    # review DB 的正確性論證（ensure-once 為何對「會被整批重建」的 review DB
    # 仍然安全）：review DB 由 load_archive_review 用 build-to-temp +
    # os.replace 重建——重建時是先對「暫存檔的 engine」完整跑過 init_schema
    # （含 PRAGMA user_version 遷移標記），確認匯入與聚合全部成功後才
    # os.replace 原子切換成正式檔。也就是說，os.replace 之後、db_path 這條
    # 路徑底下的新 DB，在被任何人讀到之前 schema 就已經完備。因此即使
    # ensured-set 裡早就記著這個 db_path「舊一輪（換檔前）已確保過」，這裡
    # 略過 init_schema 也不會讓呼叫端讀到缺 schema 的 DB——新 DB 的 schema
    # 完備性是由 build-to-temp 階段保證的，不依賴 ensure-once 這層快取。
    _ensure_schema_once(engine, db_path)
    return sessionmaker(engine)


def _remove_sqlite_sidecars(path: str) -> None:
    """只刪 -wal/-shm sidecar，留下主檔（存在才刪，不存在不當錯誤）。"""
    for suffix in ("-wal", "-shm"):
        try:
            os.remove(path + suffix)
        except FileNotFoundError:
            pass


def _remove_sqlite_files(path: str) -> None:
    """刪除 SQLite 主檔與其 -wal/-shm sidecar（存在才刪，不存在不當錯誤）。"""
    try:
        os.remove(path)
    except FileNotFoundError:
        pass
    _remove_sqlite_sidecars(path)


def _write_meta(cfg, meta: dict) -> None:
    """meta 寫入 temp + os.replace，避免崩潰留下半寫入的 meta 檔。"""
    path = _meta_path(cfg)
    tmp = path + ".tmp"
    with open(tmp, "wb") as fh:
        fh.write(orjson.dumps(meta))
    os.replace(tmp, path)


def load_archive_review(cfg, start: date, end: date) -> dict:
    """同步版：取得 lock 後執行（語意與 docstring 同 _load_archive_review_locked）。"""
    if not _LOAD_LOCK.acquire(blocking=False):
        raise ArchiveLoadBusy()
    try:
        return _load_archive_review_locked(cfg, start, end)
    finally:
        _LOAD_LOCK.release()


def _load_archive_review_locked(cfg, start: date, end: date) -> dict:
    """重建 review DB → 匯入範圍內 traffic archive → 跑聚合 → 寫 sidecar meta。

    防呆：範圍內沒有任何封存檔時，不重建 review DB（保留目前已載入的資料）、
    也不改 meta，回報 no_files=True，讓呼叫端明確提示，而非顯示看似成功的
    「0 筆」並把上一次載入的資料洗掉。

    併發：呼叫端（同步版 load_archive_review 或背景版 start_archive_load）
    負責在呼叫本函式前取得 _LOAD_LOCK（non-blocking）——第二個進來的 load
    立即拋 ArchiveLoadBusy，不排隊、不會跟第一個搶同一份暫存檔。本函式本身
    不碰 lock，只負責實際的重建/匯入/聚合。

    核心不變量：load 失敗後，review_status 與 review DB 必須仍一致地描述
    上一次成功載入。做法是 build-to-temp：整個重建/匯入/聚合都灌到獨立的
    暫存檔（`archive_review.sqlite.tmp`），只有全部成功才 os.replace 原子
    切換成正式檔、再寫 meta；任何一步失敗，正式 DB 與 meta 完全沒被碰過，
    只需清掉暫存檔。"""
    from sqlalchemy import create_engine
    from src.pce_cache.schema import init_schema
    from src.pce_cache.aggregator import TrafficAggregator
    if not _matching_traffic_files(cfg.archive_dir, start, end):
        prev = review_status(cfg)
        return {"loaded": bool(prev.get("loaded")), "no_files": True,
                "files": 0, "rows": 0, "skipped": 0,
                "start": start.isoformat(), "end": end.isoformat()}
    db = review_db_path(cfg)
    tmp = db + ".tmp"
    # 清掉前次可能留下的暫存檔（例如上次崩潰在切換前中斷）。
    _remove_sqlite_files(tmp)
    engine = create_engine(f"sqlite:///{tmp}")
    try:
        init_schema(engine)
        sf = sessionmaker(engine)
        result = ArchiveImporter(cfg.archive_dir, sf).import_range(start, end)
        TrafficAggregator(sf).run_once()
        # 把 WAL 內容併回主檔並清空 -wal，讓暫存檔本身自足——
        # 之後 os.replace 只搬主檔，不會漏資料留在 -wal 裡。
        with engine.begin() as conn:
            conn.exec_driver_sql("PRAGMA wal_checkpoint(TRUNCATE)")
    except Exception:
        engine.dispose()
        _remove_sqlite_files(tmp)
        raise
    engine.dispose()  # 釋放檔案 handle，才能安全 replace
    # 切換前清掉暫存檔自己殘留的 -wal/-shm（TRUNCATE checkpoint 後理論上
    # 已空，防禦性再清一次），以及目標檔案的舊 -wal/-shm（換了主檔後，
    # 舊 sidecar 對新主檔無效，留著會被下個連線誤讀）。
    _remove_sqlite_sidecars(tmp)
    # Windows：os.replace / 刪 sidecar 撞上仍持有舊 DB 開啟 handle 的讀取端
    # （archive review 查詢的 NullPool 短命連線；SQLite 開檔不帶
    # FILE_SHARE_DELETE）會拋 PermissionError，讓整個已成功的 load 在最後
    # 一步被判定失敗、匯入結果被丟棄。讀取端壽命短，短暫退避重試即可。
    # Linux 讀取端持有舊 inode，首次就會成功。
    for _attempt in range(10):
        try:
            _remove_sqlite_sidecars(db)
            os.replace(tmp, db)
            break
        except PermissionError:
            if _attempt == 9:
                raise
            time.sleep(0.5)
    meta = {"loaded": True, "rows": result["rows"], "files": result["files"],
            "skipped": result["skipped"], "start": result["start"], "end": result["end"]}
    _write_meta(cfg, meta)
    return meta


_PROGRESS_LOCK = threading.Lock()
_PROGRESS: dict = {"state": "idle"}


def _set_progress(**kw) -> None:
    with _PROGRESS_LOCK:
        _PROGRESS.clear()
        _PROGRESS.update(kw)


def load_progress() -> dict:
    with _PROGRESS_LOCK:
        return dict(_PROGRESS)


def start_archive_load(cfg, start: date, end: date) -> dict:
    """背景執行 archive 載入，立即回 {"started": True}。

    lock 在此取得、由背景執行緒 finally 釋放——同時只允許一個 load，
    第二個呼叫立即拋 ArchiveLoadBusy（與同步版一致，web 端回 409）。"""
    if not _LOAD_LOCK.acquire(blocking=False):
        raise ArchiveLoadBusy()
    _set_progress(state="running", start=start.isoformat(), end=end.isoformat(),
                  started_at=datetime.now(timezone.utc).isoformat())

    def _worker() -> None:
        try:
            meta = _load_archive_review_locked(cfg, start, end)
            _set_progress(state="done", **meta)
        except Exception as exc:  # noqa: BLE001 — 背景執行緒的最外層收斂
            logger.exception("archive background load failed")
            _set_progress(state="error", error=str(exc)[:500])
        finally:
            _LOAD_LOCK.release()

    threading.Thread(target=_worker, name="archive-load", daemon=True).start()
    return {"started": True, "start": start.isoformat(), "end": end.isoformat()}


def review_status(cfg) -> dict:
    try:
        with open(_meta_path(cfg), "rb") as fh:
            return orjson.loads(fh.read())
    except (FileNotFoundError, orjson.JSONDecodeError):
        return {"loaded": False}
