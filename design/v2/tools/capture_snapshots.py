"""從測試機 GUI 抓真 API 快照（遮罩後落地）。
用法：ILLUMIO_OPS_E2E_BASE_URL=https://host:5001 ILLUMIO_OPS_E2E_USER=... \
      ILLUMIO_OPS_E2E_PASSWORD=... python design/v2/tools/capture_snapshots.py [--only id,id]
"""
import json
import os
import pathlib
import re
import sys

import requests
import yaml
from masking import mask_payload, mask_values_only

HERE = pathlib.Path(__file__).resolve().parent
SNAP = HERE.parent / "snapshots"

_PATH_FROM_STEP_RE = re.compile(r"^(\w+)(?:\[(\d+)\])?$")


def load_manifest(p):
    return yaml.safe_load(pathlib.Path(p).read_text())


def login(base):
    s = requests.Session()
    # TLS 驗證預設開啟；自簽測試機用 CA bundle 注入，--insecure 需明確指定
    ca = os.environ.get("ILLUMIO_OPS_E2E_CA_BUNDLE")
    if ca:
        s.verify = ca
    elif "--insecure" in sys.argv:
        import urllib3
        urllib3.disable_warnings()
        s.verify = False
    r = s.post(f"{base}/api/login", json={
        "username": os.environ["ILLUMIO_OPS_E2E_USER"],
        "password": os.environ["ILLUMIO_OPS_E2E_PASSWORD"]}, timeout=30)
    r.raise_for_status()
    body = r.json()
    assert body.get("ok"), "login failed"
    return s, body["csrf_token"]


def resolve_path_from(entry, snap_dir):
    """把 entry['path'] 裡的 {placeholder} 換成 path_from 指到的已抓快照欄位值。

    path_from 語法："<snapshot_id>.<key>[.<key>[N]...]"，例如
    "rs_rulesets.items[0].id" → 讀 <snap_dir>/rs_rulesets.json，
    取 items[0]["id"]。snapshot 檔不存在時丟 FileNotFoundError（代表抓取順序
    寫錯，被依賴的 id 要排在 yaml 前面）。
    """
    snap_id, *steps = entry["path_from"].split(".")
    snap_file = pathlib.Path(snap_dir) / f"{snap_id}.json"
    if not snap_file.exists():
        raise FileNotFoundError(
            f"path_from needs snapshot '{snap_id}.json' captured first (for {entry['id']})")
    value = json.loads(snap_file.read_text())
    for step in steps:
        m = _PATH_FROM_STEP_RE.match(step)
        key, idx = m.group(1), m.group(2)
        value = value[key]
        if idx is not None:
            value = value[int(idx)]
    path = entry["path"]
    placeholder = re.search(r"\{(\w+)\}", path).group(0)
    return path.replace(placeholder, str(value))


def _request(sess, base, e, csrf):
    if e["method"] == "GET":
        return sess.get(f"{base}{e['path']}", timeout=120)
    # flask_wtf.csrf.CSRFProtect.protect() (installed lib, flask_wtf 1.3.0) enforces
    # WTF_CSRF_SSL_STRICT (default True, not overridden in src/gui/__init__.py:239-247)
    # for any request.is_secure POST: it requires a Referer header matching the host,
    # on top of the X-CSRFToken. Without it every masked POST 400s with csrf_error
    # even with a fresh, valid token — reproduced live against the staging box.
    return sess.post(f"{base}{e['path']}", json=e.get("payload") or {},
                      headers={"X-CSRFToken": csrf, "Referer": f"{base}/"}, timeout=300)


def capture_one(sess, base, e, outdir, csrf):
    if "path_from" in e:
        e = {**e, "path": resolve_path_from(e, outdir)}
    r = _request(sess, base, e, csrf)
    if r.status_code != 200:
        print(f"  !! {e['id']}: HTTP {r.status_code}")
        return False
    outdir.mkdir(parents=True, exist_ok=True)
    # manifest `mask: catalog`（見 endpoints.yaml 註解）：字典鍵名本身是
    # identifier（i18n key／event type key），不套語意式 key 遮罩，只掃長 hex 值。
    mask_fn = mask_values_only if e.get("mask") == "catalog" else mask_payload
    (outdir / f"{e['id']}.json").write_text(
        json.dumps(mask_fn(r.json()), ensure_ascii=False, indent=1))
    print(f"  ok {e['id']}")
    return True


def main():
    base = os.environ["ILLUMIO_OPS_E2E_BASE_URL"].rstrip("/")
    only = None
    if "--only" in sys.argv:
        only = set(sys.argv[sys.argv.index("--only") + 1].split(","))
    sess, csrf = login(base)
    fails = [e["id"] for e in load_manifest(HERE / "endpoints.yaml")
              if (only is None or e["id"] in only)
              and not capture_one(sess, base, e, SNAP, csrf)]
    if fails:
        sys.exit(f"FAILED: {fails}")


if __name__ == "__main__":
    main()
