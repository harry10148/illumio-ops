from src import i18n


def test_report_email_keys_are_not_placeholder_text_in_english():
    prev = i18n.get_language()
    i18n.set_language("en")
    try:
        keys = [
            "rpt_email_key_metrics",
            "rpt_email_kpi_title",
            "rpt_email_scheduled_report",
            "rpt_email_ven_subject",
            "rpt_email_pu_subject",
            "rpt_email_attached_files",
            "rpt_email_security_findings",
            "rpt_email_audit_subject",
            "rpt_email_traffic_subject",
            "rpt_email_records",
            "rpt_email_period",
            "rpt_email_key_findings",
            "rpt_email_no_findings",
            "rpt_email_source_api",
            "rpt_email_footer",
            "rpt_email_sent",
            "rpt_email_failed",
        ]
        for key in keys:
            text = i18n.t(key)
            assert not text.startswith("Rpt ")
            assert "GUI " not in text
    finally:
        i18n.set_language(prev)


def test_dashboard_no_policy_usage_summary_message_is_localized():
    prev = i18n.get_language()
    try:
        i18n.set_language("en")
        assert i18n.t("gui_dashboard_no_policy_usage_summary").startswith("No policy usage report summary found")

        i18n.set_language("zh_TW")
        assert "Policy 使用報表摘要" in i18n.t("gui_dashboard_no_policy_usage_summary")
    finally:
        i18n.set_language(prev)


def test_report_email_keys_are_explicitly_localized_in_zh_tw():
    prev = i18n.get_language()
    i18n.set_language("zh_TW")
    try:
        keys = [
            "rpt_email_key_metrics",
            "rpt_email_kpi_title",
            "rpt_email_scheduled_report",
            "rpt_email_attached_files",
            "rpt_email_security_findings",
            "rpt_email_key_findings",
            "rpt_email_no_findings",
            "rpt_email_source_api",
            "rpt_email_footer",
            "rpt_email_sent",
        ]
        for key in keys:
            text = i18n.t(key)
            assert "Rpt " not in text
            assert "GUI " not in text
    finally:
        i18n.set_language(prev)
