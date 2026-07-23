"""Unmanaged 章 6 表併 3（spec C3）：exposed_ports_merged builder 與渲染。"""
import pandas as pd
from src.report.analysis.mod08_unmanaged_hosts import unmanaged_traffic
from src.report.exporters.html_exporter import NetworkInventoryHtmlExporter


def _df():
    rows = []
    for i, (src, conns) in enumerate([("10.9.0.1", 30), ("10.9.0.2", 20), ("10.9.0.3", 10), ("10.9.0.4", 5)]):
        rows.append({"src_ip": src, "dst_ip": f"10.1.0.{i}", "port": 445, "proto": "TCP",
                     "src_app": "", "dst_app": "fileserver", "policy_decision": "allowed",
                     "src_managed": False, "dst_managed": True,
                     "num_connections": conns, "bytes_total": 1000, "dst_hostname": f"h{i}"})
    # 一筆 managed 流量作對照
    rows.append({"src_ip": "10.0.0.1", "dst_ip": "10.1.0.9", "port": 443, "proto": "TCP",
                 "src_app": "web", "dst_app": "api", "policy_decision": "allowed",
                 "src_managed": True, "dst_managed": True,
                 "num_connections": 9, "bytes_total": 500, "dst_hostname": "h9"})
    return pd.DataFrame(rows)


def test_exposed_ports_merged_shape():
    out = unmanaged_traffic(_df())
    merged = out["exposed_ports_merged"]
    assert not merged.empty
    row = merged[merged["Port"] == 445].iloc[0]
    # top 3 + 溢出標記
    assert row["Top Unmanaged Sources"] == "10.9.0.1, 10.9.0.2, 10.9.0.3 +1"
    # 原 6 key 照舊保留
    for k in ("top_unmanaged_src", "top_unmanaged_dst", "managed_hosts_targeted_by_unmanaged",
              "per_dst_app", "per_port_proto", "src_port_detail"):
        assert k in out


def test_exposed_ports_merged_nan_src_ip():
    """NaN src_ip（Phase 2 教訓：groupby dropna=False + (unknown) 標籤）不可讓 builder 炸掉或漏算，
    且該來源仍須以 (unknown) 標籤現身於排行中（而非被 dropna 悄悄丟棄）。"""
    df = _df()
    df.loc[df["src_ip"] == "10.9.0.2", "src_ip"] = None
    out = unmanaged_traffic(df)
    merged = out["exposed_ports_merged"]
    row = merged[merged["Port"] == 445].iloc[0]
    assert row["Top Unmanaged Sources"] == "10.9.0.1, (unknown), 10.9.0.3 +1"


def test_inventory_renders_three_tables():
    results = {"mod08": unmanaged_traffic(_df()), "mod12": {"kpis": [], "key_findings": []}, "findings": []}
    html = NetworkInventoryHtmlExporter(results, lang="en").build()
    from src.report.exporters.report_i18n import STRINGS
    assert STRINGS["rpt_tr_top_unmanaged"]["en"] in html
    assert STRINGS["rpt_tr_managed_apps_unmanaged"]["en"] in html
    assert STRINGS["rpt_tr_exposed_ports_merged"]["en"] in html
    # 停止渲染的兩表標題消失（實作前 git grep 確認的舊英文標題字面值）
    assert "Exposed Ports / Protocols" not in html
    assert "Unmanaged Source Port Detail" not in html
    assert "Managed Hosts Targeted by Unmanaged Sources" not in html


def test_top_unmanaged_src_network_classification():
    """未受管來源要區分內網/公網——公網來源打進 managed services 是高風險
    訊號，不能混在同一張表無從辨識（2026-07-23 視覺實檢）。"""
    df = _df()
    df.loc[df["src_ip"] == "10.9.0.1", "src_ip"] = "45.148.10.119"  # 公網
    out = unmanaged_traffic(df)
    top = out["top_unmanaged_src"]
    assert "Network" in top.columns
    by_ip = dict(zip(top["Unmanaged Source IP"], top["Network"]))
    assert by_ip["45.148.10.119"] == "external"
    assert by_ip["10.9.0.2"] == "internal"
    assert out["external_unmanaged_src"] == 1


def test_network_classification_bad_ip_defaults_external():
    """非法 IP 保守判為 external（寧可誤標紅也不誤標安全）。"""
    from src.report.analysis.mod08_unmanaged_hosts import _classify_network
    assert _classify_network("not-an-ip") == "external"
    assert _classify_network("192.168.1.5") == "internal"
    assert _classify_network("8.8.8.8") == "external"
