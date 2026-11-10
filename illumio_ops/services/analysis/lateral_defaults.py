"""The lateral-movement default rankings (spec §6.5.7): on management-port traffic, who initiates connections —
users and processes by the number of distinct destination hosts, and the system accounts among the users. The
segments are domain.segment.lateral_default_segments, run by run_segment like every analysis segment; the lateral
movement page and the lateral posture report both read this function, so the two show the same numbers.

Few flows carry a user or a process (lab: user 12%, process 4%): the result says how many of the management-port
connections do, and a caller shows that beside the rankings."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel

from illumio_ops.domain.filter import FilterSpec, PortProto
from illumio_ops.domain.identity import is_system_account
from illumio_ops.domain.segment import lateral_default_segments
from illumio_ops.services.analysis.context import load_lateral_context
from illumio_ops.services.analysis.segments import run_segment
from illumio_ops.services.context import AppContext
from illumio_ops.services.flowsource import field_coverage

TOP = 10  # rows each ranking shows
# Accounts read to find the system accounts among them: the segment's own 50 would miss one ranked lower, and the
# page would then say there is none. Past this many the result says the rest were not checked.
SYSTEM_SCAN = 1000


class Initiator(BaseModel):
    name: str
    destinations: int  # distinct destination hosts reached on management ports


class LateralDefaults(BaseModel):
    start: datetime
    end: datetime
    users: list[Initiator]            # initiating users, system accounts left out
    processes: list[Initiator]        # initiating processes
    system_accounts: list[Initiator]  # the operating-system accounts among the initiating users
    more: dict[str, int]              # ranking -> rows read beyond TOP that are not shown
    capped: dict[str, int]            # ranking -> the rows its read stopped at: there are more, uncounted (and for
    #                                   system_accounts, accounts past it were not checked)
    flows: int                        # management-port flow records in the period
    with_user: int                    # of those, records that name the initiating user
    with_process: int                 # of those, records that name the initiating process


def lateral_defaults(ctx: AppContext, *, start: datetime, end: datetime, now: datetime) -> LateralDefaults:
    lc = load_lateral_context(ctx, now=now)
    ports = tuple(PortProto(port=port, proto=proto)
                  for port, proto in dict.fromkeys((e.port, e.proto) for e in lc.admin_ports.entries))
    segs = lateral_default_segments(ports, start=start, end=end)

    capped: dict[str, int] = {}

    def named(name: str, key: str, limit: int | None = None) -> list[Initiator]:
        seg = segs[key] if limit is None else segs[key].model_copy(update={"limit": limit})
        result = run_segment(ctx, seg, now=now)
        if result.limit_hit:
            capped[name] = seg.limit
        return [Initiator(name=str(r.keys[0]), destinations=r.value) for r in result.ranking or []
                if r.keys[0] not in (None, "")]

    users = named("users", "admin_initiator_users")
    processes = named("processes", "admin_initiator_processes")
    system = [r for r in named("system_accounts", "system_accounts_on_admin", SYSTEM_SCAN) if is_system_account(r.name)]
    fc = field_coverage(ctx, FilterSpec(start=start, end=end, ports=ports))
    shown = {"users": users, "processes": processes, "system_accounts": system}
    return LateralDefaults(start=start, end=end, users=users[:TOP], processes=processes[:TOP],
                           system_accounts=system[:TOP],
                           more={k: len(v) - TOP for k, v in shown.items() if len(v) > TOP}, capped=capped,
                           flows=fc.total, with_user=fc.initiator_user, with_process=fc.initiator_process)
