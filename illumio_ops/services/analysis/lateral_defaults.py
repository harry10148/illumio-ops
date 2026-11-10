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

TOP = 10  # rows each ranking shows; the segment reads up to its own limit and says when there are more


class Initiator(BaseModel):
    name: str
    destinations: int  # distinct destination hosts reached on management ports


class LateralDefaults(BaseModel):
    start: datetime
    end: datetime
    users: list[Initiator]            # initiating users, system accounts left out
    processes: list[Initiator]        # initiating processes
    system_accounts: list[Initiator]  # the operating-system accounts among the initiating users
    more: dict[str, int]              # ranking -> rows beyond TOP that are not shown
    connections: int                  # management-port connections in the period
    with_user: int                    # of those, connections that name the initiating user
    with_process: int                 # of those, connections that name the initiating process


def lateral_defaults(ctx: AppContext, *, start: datetime, end: datetime, now: datetime) -> LateralDefaults:
    lc = load_lateral_context(ctx, now=now)
    ports = tuple(PortProto(port=port, proto=proto)
                  for port, proto in dict.fromkeys((e.port, e.proto) for e in lc.admin_ports.entries))
    segs = lateral_default_segments(ports, start=start, end=end)

    def named(key: str) -> list[Initiator]:
        rows = run_segment(ctx, segs[key], now=now).ranking or []
        return [Initiator(name=str(r.keys[0]), destinations=r.value) for r in rows if r.keys[0] not in (None, "")]

    users = named("admin_initiator_users")
    processes = named("admin_initiator_processes")
    system = [r for r in named("system_accounts_on_admin") if is_system_account(r.name)]
    fc = field_coverage(ctx, FilterSpec(start=start, end=end, ports=ports))
    shown = {"users": users, "processes": processes, "system_accounts": system}
    return LateralDefaults(start=start, end=end, users=users[:TOP], processes=processes[:TOP],
                           system_accounts=system[:TOP],
                           more={k: len(v) - TOP for k, v in shown.items() if len(v) > TOP},
                           connections=fc.total, with_user=fc.initiator_user, with_process=fc.initiator_process)
