# CLI 指令對照表

> [English](cli-command-map.md) | [繁體中文](cli-command-map_zh.md)

本文件把每個 `illumio-ops` 指令對應到它的入口:

- **CLI** — 透過 `illumio-ops <command>` 直接呼叫
- **Menu** — 從互動選單(`illumio-ops shell`)裡走到的位置
- **Deprecated alias** — 舊版寫法,仍可用,但會提示請改用新版

## Top-level 子指令

| 子指令 | CLI | Menu 路徑 | Deprecated alias |
|------------|-----|-----------|------------------|
| `cache backfill` | ✓ | shell → 7 (Manage PCE Cache) → 5 | — |
| `cache status` | ✓ | shell → 7 → 1 | — |
| `cache retention` | ✓ | shell → 7 → 6 | — |
| `completion install <shell>` | ✓ | — | — |
| `config validate` | ✓ | — | — |
| `config show` | ✓ | shell → 4 (Settings) — view path | — |
| `gui` | ✓ | shell → 5 (Launch Web GUI) | `--gui`(legacy argparse)|
| `monitor` | ✓ | shell — 由選單迴圈隱式執行 | `--monitor`(legacy argparse)|
| `report generate-traffic` | ✓ | shell → 2 (Reports) → 1 | `report traffic` |
| `report generate-audit` | ✓ | shell → 2 → 2 | `report audit` |
| `report generate-ven-status` | ✓ | shell → 2 → 3 | `report ven-status` |
| `report generate-policy-usage` | ✓ | shell → 2 → 4 | `report policy-usage` |
| `rule list` | ✓ | shell → 1 (Rule Management) — list | — |
| `rule edit` | ✓ | shell → 1 — edit | — |
| `shell` | ✓ | (這個指令本身就是選單)| 裸 `illumio-ops`(無參數)|
| `siem test` | ✓ | shell → 8 (SIEM) — test | — |
| `siem status` | ✓ | shell → 8 → 1 | — |
| `siem replay` | ✓ | shell → 8 → DLQ 子選單 → replay | — |
| `siem purge` | ✓ | shell → 8 → DLQ 子選單 → purge | — |
| `siem dlq` | ✓ | shell → 8 → DLQ 子選單 → list | — |
| `status` | ✓ | shell — 在面板顯示資訊 | — |
| `version` | ✓ | — | — |
| `workload list` | ✓ | — | — |

## 入口

| 入口 | 狀態 | 備註 |
|-------|--------|-------|
| `illumio-ops <subcommand>` | **正規入口** | 單一指令樹,以 click 為基底 |
| `illumio-ops shell` | **正規入口** | 明確的互動選單(Track C 新增)|
| `illumio-ops`(無參數)| 已棄用 | 顯示提示請改用 `shell`,但仍會啟動選單 |
| `illumio-ops --monitor`(及其他 legacy argparse flags)| 向後相容 | 路由至 `illumio-ops.py` 內的 legacy argparse handler |
| `python -m src.pce_cache_cli` | **不是入口** | 從 `src/main.py:main_menu` 呼叫的互動 helper module,不是獨立執行檔。請勿直接執行 |
| `python -m src.siem_cli` | **不是入口** | 同上 |
| `python -m src.rule_scheduler_cli` | **不是入口** | 同上 |

## 棄用政策

每個 deprecated 寫法至少在一個 major release 內仍可用。每次呼叫會在 stderr 印出一行提示(透過 `echo_warning`)指向正規寫法。

Track C 引入的 deprecation(2026-05-07):
- 裸 `illumio-ops` 無參數 → 請改用 `illumio-ops shell`
- `report traffic` / `report audit` / `report ven-status` / `report policy-usage` → 請改用 `report generate-*`

## 新增子指令的步驟

1. 在 `src/cli/<group>.py` 實作 click command 函式(用 `@click.pass_context`、`_output` helpers,並依 Track B 慣例用 `EXIT_*` 型別化 exit code)。
2. 註冊到 parent group:`group.add_command(my_cmd)` 或 `@group.command(...)`。
3. 若新增的是頂層子指令,還要把名字加進 `illumio-ops.py` 的 `_CLICK_SUBCOMMANDS` set,dispatcher 才能正確路由(否則會 fall through 到 legacy argparse handler)。
4. 更新本文件。
