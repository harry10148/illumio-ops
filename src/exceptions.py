"""Typed exception hierarchy for illumio_ops."""


class IllumioOpsError(Exception):
    pass


class APIError(IllumioOpsError):
    pass


class TrafficQueryError(APIError):
    """Interactive traffic query failed on the PCE side (submit/poll/download).

    Raised by Analyzer.query_flows so GUI callers can distinguish "query
    failed" from "0 flows matched". The API-layer generator never raises
    this: ingest depends on its empty-yield + last_fetch_error contract.
    """


class ConfigError(IllumioOpsError):
    pass


class ReportError(IllumioOpsError):
    pass


class AlertError(IllumioOpsError):
    pass


class SchedulerError(IllumioOpsError):
    pass


class EventError(IllumioOpsError):
    pass
