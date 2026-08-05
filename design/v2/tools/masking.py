"""遞迴遮罩快照裡的機密。

語意式 key 判定（2026-08-03 使用者裁決，取代舊版「子字串即遮」regex——
舊規則把 c-h-e-c-k 這種普通字誤判成含 "hec" 而整批非機密欄位被打光，
詳見 docs/superpowers/plans/2026-08-03-ui-redesign-v2-phase1-mockup.md
Global Constraints）：

- key 依非英數字元「以及 camelCase 邊界」切成 token（小寫），完整字 token
  命中即遮：password/passwd/secret/token/credential/credentials/hec。
  camelCase 邊界必須切開，否則 apiToken/authToken/clientSecret/
  passwordHash/apiSecret/secretKey/sessionToken/accessToken/hecToken/
  bearerToken/refreshToken 這類複合字會被當成單一 token（"apitoken" 之類）
  而錯過完整字比對，導致機密欄位漏遮（2026-08-03 review I1 發現的
  fail-open）。
- 或 token "key" 與下列詞相鄰（含中間無底線的合體字，如 apikey）即遮：
  api/private/ssh/signing/encryption/session/access/auth/license。
- 其餘 "*_key" 只是 identifier 尾綴（filter_key/label_key/i18n_key/
  desc_key/rec_key/name_key 等，指到別的字典鍵名，不是機密），不遮。
- `<key>__set`／`<key>__length` 尾綴一律不遮：這是後端 _redact_secrets()
  （src/gui/_helpers.py:126-140）自己合成的安全衍生 metadata（bool/int），
  本尊已被後端換成星號，這兩個尾綴不可能還原出機密。

PII（個資，非機密）類別，2026-08-03 使用者裁決，修正原計畫 constraint
只涵蓋機密未涵蓋個資的缺口：alert_channels[].last_target 是告警最近一次
送達的收件方（Email 地址／LINE 使用者 ID），屬個人資料而非機密憑證，但
快照/截圖同樣不可外流真實聯絡方式。獨立成 `_PII_KEYS`（精確 key 全字
比對，不做 token 化），刻意窄範圍——不用泛用字（如 "target"）當 token
判準，否則會誤傷同結構下其它欄位。命中後一樣走 `is_sensitive_key`／
`mask_payload` 既有 pipeline、遮成同一個 MASK token，只是語意分類不同。

執行 last_target 遮罩時盤點發現：同一顆真實 email／LINE 使用者 ID 還從
另外兩個泛用鍵名洩漏（超出原計畫「只有 alert_channels[].last_target」的
盤點範圍）——
  - settings.json `/alerts/line_target_id`：跟 last_target 一樣是專用鍵
    名，無歧義，併入 `_PII_KEYS` 精確比對。
  - dashboard_overview.json `/alerts/recent[].target`、status.json
    `/dispatch_history[].target`、settings.json `/email/recipients`：
    鍵名是泛用字，同一個 "target" 在 `/posture/remediation[].target`
    卻是數字目標值（非個資），不能無條件遮（否則把數字打成字串會造成
    連坐型別錯誤）。因此獨立一條「值形狀」二次確認規則
    `_PII_VALUE_GATED_KEYS`：key 命中且值本身長得像 email 或 LINE 使用者
    ID（`U` + 32 hex）才遮，數字或其它形狀的值原樣保留。

2026-08-05 使用者裁決把同一個 PII 類別延伸到 settings.json 的寄件設定
（`/email/sender`、`/smtp/user` 帶的是同一顆真實個人信箱）：
  - `sender`／`user` 鍵名同樣是泛用字（流量明細的 `source.user` 是流量的
    使用者欄、事件明細的 `user` 是一個巢狀物件），所以併入
    `_PII_VALUE_GATED_KEYS` 走值形狀二次確認，不做無條件遮蔽。
  - `/smtp/host` 帶的是同一顆個人網域（mail.<個人網域>），但 `host` 是全專
    案最泛用的鍵名之一（siem_destinations 的目的地 host、workload 主機名都
    叫 host），值形狀又只是個主機名——沒有任何值形狀規則能把「個人郵件網
    域」跟「機房主機」分開。這一顆因此獨立成 `_PII_PATHS`：精確路徑比對，
    只遮 settings 端點的 `smtp.host`，其餘 host 一律不動。路徑不帶陣列索引
    （list 沿用父層路徑），所以同一個鍵不管包在幾層陣列裡都認得出來。

value 規則不變：40+ 位純 hex 字串一律遮（PCE api secret 的典型長相）。
"""
import re
from typing import Any

# camelCase 感知：先吃「首字大寫可選 + 小寫/數字串」，再吃「連續大寫（後面不
# 接小寫）」，讓 apiToken -> [api, Token]、HECToken -> [HEC, Token] 都能各自
# 對上完整字，而非被併成一個查無此字的合體 token。
_TOKEN_RE = re.compile(r"[A-Z]?[a-z0-9]+|[A-Z]+(?![a-z])")
_STANDALONE_SECRET_WORDS = {
    "password", "passwd", "secret", "token", "credential", "credentials", "hec",
}
_KEY_ADJACENT_WORDS = {
    "api", "private", "ssh", "signing", "encryption", "session",
    "access", "auth", "license",
}
_MERGED_KEY_FORMS = {w + "key" for w in _KEY_ADJACENT_WORDS}
_REDACTION_METADATA_SUFFIXES = ("__set", "__length")
_HEXY_VALUE_RE = re.compile(r"^[0-9a-fA-F]{40,}$")
# PII（非機密）：精確 key 全字比對，見模組 docstring PII 段落。刻意不做
# token 化／不收泛用字，避免誤傷同結構下其它欄位。
_PII_KEYS = {"last_target", "line_target_id"}
# PII 值形狀（非機密）：email／LINE 使用者 ID 的典型長相，用來給下面
# _PII_VALUE_GATED_KEYS 那批「鍵名會重複用在非個資語境」的欄位做二次確認。
_EMAIL_VALUE_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
_LINE_UID_VALUE_RE = re.compile(r"^U[0-9a-fA-F]{32}$")
# 泛用鍵名，只有在值長得像個資（email／LINE UID）才遮；否則保留原值
# （如 posture.remediation[].target 是數字目標值，不是個資）。見模組
# docstring PII 段落的洩漏面盤點。
_PII_VALUE_GATED_KEYS = {"target", "recipients", "sender", "user"}
# 精確路徑（不含陣列索引）比對，給「鍵名泛用、值形狀也分不出來」的那一顆。
# 刻意只列出真的要遮的那條路徑，不做任何前綴／萬用比對。
_PII_PATHS = {"smtp.host"}
MASK = "***MASKED***"


def _looks_like_pii_value(value: Any) -> bool:
    """值形狀判定：字串命中 email／LINE 使用者 ID 樣式，或字串 list 裡
    有任一元素命中（如 email.recipients 是 email 字串陣列）。"""
    if isinstance(value, str):
        return bool(_EMAIL_VALUE_RE.match(value) or _LINE_UID_VALUE_RE.match(value))
    if isinstance(value, list):
        return any(_looks_like_pii_value(v) for v in value)
    return False


def is_sensitive_key(key: str) -> bool:
    """語意式判定：key 是否代表機密或 PII 欄位（見模組 docstring 規則）。"""
    key = str(key)
    if key.endswith(_REDACTION_METADATA_SUFFIXES):
        return False
    if key.lower() in _PII_KEYS:
        return True
    tokens = [t.lower() for t in _TOKEN_RE.findall(key)]
    if any(t in _STANDALONE_SECRET_WORDS for t in tokens):
        return True
    if any(t in _MERGED_KEY_FORMS for t in tokens):
        return True
    for i, t in enumerate(tokens):
        if t != "key":
            continue
        prev_ok = i > 0 and tokens[i - 1] in _KEY_ADJACENT_WORDS
        next_ok = i + 1 < len(tokens) and tokens[i + 1] in _KEY_ADJACENT_WORDS
        if prev_ok or next_ok:
            return True
    return False


def _mask_pii_value_gated(key: str, value: Any, path: str = "") -> Any:
    """PII 泛用鍵名的值形狀二次確認（見 `_PII_VALUE_GATED_KEYS` 註解），外加
    `_PII_PATHS` 的精確路徑比對。key／path 都不命中回傳 None（呼叫端表示未
    處理，改走一般遞迴）。"""
    if path in _PII_PATHS:
        return MASK
    if key in _PII_VALUE_GATED_KEYS and _looks_like_pii_value(value):
        return MASK
    return None


def _child_path(path: str, key: str) -> str:
    """路徑不帶陣列索引：dict 才往下接一層，list 沿用父層路徑（見 docstring）。"""
    return f"{path}.{key}" if path else str(key)


def mask_payload(obj: Any, path: str = "") -> Any:
    """一般端點用：key 命中語意規則 → 整值（含子樹）遮蔽；hex 值也遮；
    泛用鍵名（target/recipients/sender/user）值形狀像個資才遮；`_PII_PATHS`
    列出的精確路徑無條件遮。見模組 docstring。"""
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            if is_sensitive_key(k):
                out[k] = MASK
                continue
            child = _child_path(path, k)
            gated = _mask_pii_value_gated(k, v, child)
            out[k] = gated if gated is not None else mask_payload(v, child)
        return out
    if isinstance(obj, list):
        return [mask_payload(v, path) for v in obj]
    if isinstance(obj, str) and _HEXY_VALUE_RE.match(obj):
        return MASK
    return obj


def mask_values_only(obj: Any, path: str = "") -> Any:
    """靜態目錄型端點用（manifest `mask: catalog`）：完全不做機密 key 判定
    （鍵名本身是識別碼，如 ui_translations 的 gui_password 是「密碼欄位
    顯示文字」的 i18n key，值才是要保留的文字），只掃長 hex 值；PII 值形狀
    二次確認規則與 `_PII_PATHS` 仍保留（防呆，catalog 資料理論上不該出現，但
    萬一混入同樣不可外流）。"""
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            child = _child_path(path, k)
            gated = _mask_pii_value_gated(k, v, child)
            out[k] = gated if gated is not None else mask_values_only(v, child)
        return out
    if isinstance(obj, list):
        return [mask_values_only(v, path) for v in obj]
    if isinstance(obj, str) and _HEXY_VALUE_RE.match(obj):
        return MASK
    return obj
