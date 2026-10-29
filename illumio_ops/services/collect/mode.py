"""Which sources each collection mode reads (spec §6.4): full reads everything, alert keeps
traffic briefly and never backfills it, lightweight reads no traffic at all."""
from __future__ import annotations

from illumio_ops.domain.values import CollectionMode, IngestSource
from illumio_ops.settings.schema import Settings

_ALWAYS = frozenset({IngestSource.EVENTS, IngestSource.INVENTORY, IngestSource.RANSOMWARE, IngestSource.BACKFILL})
MODE_SOURCES: dict[CollectionMode, frozenset[IngestSource]] = {
    CollectionMode.FULL: _ALWAYS | {IngestSource.TRAFFIC},
    CollectionMode.ALERT: _ALWAYS | {IngestSource.TRAFFIC},
    CollectionMode.LIGHTWEIGHT: _ALWAYS,
}


def in_mode(settings: Settings, source: str) -> bool:
    """The source belongs to the configured mode (whether or not collection is switched on)."""
    return source in MODE_SOURCES[settings.collection.mode]


def collects(settings: Settings, source: str) -> bool:
    """Collection is on and the configured mode reads this source."""
    return settings.collection.enabled and in_mode(settings, source)


def backfill_sources(settings: Settings, *, manual: bool) -> tuple[IngestSource, ...]:
    """What a backfill reads: the initial one reads traffic only in full mode; one started by hand
    reads whatever the mode collects."""
    traffic = settings.collection.mode is CollectionMode.FULL or (
        manual and in_mode(settings, IngestSource.TRAFFIC))
    return (IngestSource.TRAFFIC, IngestSource.EVENTS) if traffic else (IngestSource.EVENTS,)
