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


class AsyncDownloadError(APIError):
    """Async traffic-query result download failed (non-200).

    Raised by AsyncJobManager.iter_async_query_results so callers can
    distinguish "download failed" from "0 flows matched" — a silent empty
    generator here previously let downstream rule-hit-count logic treat a
    failed download the same as a genuinely unused rule.
    """


class TruncatedCollectionError(APIError):
    """Collection GET hit the PCE 500-object cap and the async-GET
    fallback could not recover the full set.

    Raised only for raise_on_error=True callers: silently returning the
    truncated page would let incomplete data flow into reports as if it
    were the complete collection.
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
