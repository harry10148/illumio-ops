"""Is the PCE at a new address the one the flow database holds (decision D3, spec §6.4)? Asked before the data is kept
for it: a few stored workload hrefs are read from the new address with the read key, and the PCE must answer for them
with the same href (workload hrefs carry a UUID and the org, so another PCE or org cannot answer for them)."""
from __future__ import annotations

from illumio_ops.pce.client import PceBudgetExhausted, PceTransportError
from illumio_ops.services.context import AppContext
from illumio_ops.settings.schema import PceSettings
from illumio_ops.store.flowdb import workloads

SAMPLE = 5
GONE = (404, 410)


class NothingToCompare(Exception):
    """No stored workload of this org: there is no data that could tell the two apart."""


class Unverifiable(Exception):
    """The new address did not answer in a way that tells (refused the key, unreachable, an error)."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class NotTheSame(Exception):
    """The new address answered, and knows none of the stored workloads."""

    def __init__(self, asked: int) -> None:
        super().__init__(f"none of {asked} workloads found")
        self.asked = asked


def sample_hrefs(ctx: AppContext, org_id: str) -> list[str]:
    prefix = f"/orgs/{org_id}/workloads/"
    with ctx.flows().connect() as conn:
        rows = workloads.all_workloads(conn)
    ours = sorted((r for r in rows if r.href.startswith(prefix)), key=lambda r: (not r.managed, r.href))
    return [r.href for r in ours[:SAMPLE]]


def verify(ctx: AppContext, candidate: PceSettings) -> None:
    """Returns when at least one stored workload is answered with its own href; raises NothingToCompare, Unverifiable
    or NotTheSame otherwise."""
    hrefs = sample_hrefs(ctx, candidate.org_id)
    if not hrefs:
        raise NothingToCompare
    refused: str | None = None
    with ctx.pce_client(candidate) as client:
        for href in hrefs:
            try:
                r = client.request("GET", href, org_scoped=False)
            except PceTransportError as exc:
                raise Unverifiable(exc.kind) from None
            except PceBudgetExhausted:
                raise Unverifiable("rate_limit") from None
            if r.status == 200:
                try:
                    body = r.json()
                except ValueError:
                    body = None
                if isinstance(body, dict) and body.get("href") == href:
                    return
                continue
            if r.status not in GONE:
                refused = refused or f"HTTP {r.status}"
    if refused is not None:
        raise Unverifiable(refused)
    raise NotTheSame(len(hrefs))
