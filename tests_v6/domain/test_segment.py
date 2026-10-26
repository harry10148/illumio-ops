"""Analysis segments (spec §6.3 point 4): one definition = filter + grouping (≤ 2 levels) + metric + view,
compiled once so the screen and the report compute the same number."""
from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from illumio_ops.domain.filter import FilterSpec, PortProto
from illumio_ops.domain.segment import (
    EventFilter,
    EventSegment,
    FlowSegment,
    GroupBy,
    compile_event_ranking,
    compile_flow_ranking,
    lateral_default_segments,
)
from illumio_ops.domain.values import SegmentDimension as D
from illumio_ops.domain.values import SegmentMetric as M
from illumio_ops.domain.values import SegmentView as V

END = datetime(2026, 10, 25, 12, 0, tzinfo=UTC)
START = END - timedelta(days=7)
SPEC = FilterSpec(start=START, end=END)


def test_ranking_requires_group_by():
    with pytest.raises(ValidationError):
        FlowSegment(filter=SPEC, view=V.RANKING, limit=10)
    with pytest.raises(ValidationError):
        FlowSegment(filter=SPEC, view=V.DETAIL, group_by=(GroupBy(dimension=D.SRC_HOST),), limit=10)


def test_more_than_two_levels_rejected():
    with pytest.raises(ValidationError):
        FlowSegment(filter=SPEC, view=V.RANKING, limit=10, group_by=(
            GroupBy(dimension=D.SRC_HOST), GroupBy(dimension=D.DST_HOST), GroupBy(dimension=D.SERVICE)))


def test_label_dimension_requires_key():
    with pytest.raises(ValidationError):
        GroupBy(dimension=D.SRC_LABEL)
    with pytest.raises(ValidationError):
        GroupBy(dimension=D.SRC_HOST, label_key="app")
    assert GroupBy(dimension=D.DST_LABEL, label_key="app").label_key == "app"


def test_event_dimension_on_flow_segment_rejected():
    with pytest.raises(ValidationError):
        FlowSegment(filter=SPEC, view=V.RANKING, limit=10, group_by=(GroupBy(dimension=D.EVENT_TYPE),))
    with pytest.raises(ValidationError):
        FlowSegment(filter=SPEC, view=V.RANKING, limit=10, metric=M.EVENTS, group_by=(GroupBy(dimension=D.SRC_HOST),))
    with pytest.raises(ValidationError):
        EventSegment(filter=EventFilter(start=START, end=END), view=V.RANKING, limit=10,
                     group_by=(GroupBy(dimension=D.SRC_HOST),))
    with pytest.raises(ValidationError):
        EventSegment(filter=EventFilter(start=START, end=END), view=V.PREDICTED_BLOCK, limit=10)


def test_compiled_sql_params_order():
    seg = FlowSegment(filter=SPEC.model_copy(update={"initiator_user": "admin"}), view=V.RANKING, limit=5,
                      metric=M.DISTINCT_DST,
                      group_by=(GroupBy(dimension=D.SRC_LABEL, label_key="app"), GroupBy(dimension=D.INITIATOR_USER)))
    sql, params = compile_flow_ranking(seg)
    # label key (JOIN) first, then the filter's own parameters, then the limit (+1 to see if it was hit)
    assert params[0] == "app" and params[-1] == 6 and "%admin%" in params
    assert sql.index("JOIN") < sql.index("WHERE") < sql.index("GROUP BY") < sql.index("ORDER BY")
    assert "COUNT(DISTINCT f.dst_key)" in sql


def test_event_ranking_compiles_with_host_join():
    seg = EventSegment(filter=EventFilter(start=START, end=END, event_types=("agent.tampering",)), view=V.RANKING,
                       limit=10, group_by=(GroupBy(dimension=D.EVENT_HOST),))
    sql, params = compile_event_ranking(seg)
    assert "LEFT JOIN workloads" in sql and params[-1] == 11 and "agent.tampering" in params


def test_lateral_default_segments_keys_and_shapes():
    ports = (PortProto(port=22, proto=6), PortProto(port=445))
    segs = lateral_default_segments(ports, start=START, end=END)
    assert set(segs) == {"admin_initiator_users", "admin_initiator_processes", "system_accounts_on_admin"}
    users = segs["admin_initiator_users"]
    assert users.view is V.RANKING and users.metric is M.DISTINCT_DST
    assert [g.dimension for g in users.group_by] == [D.INITIATOR_USER]
    assert users.filter.ports == ports and users.filter.exclude_system_accounts is True
    assert segs["system_accounts_on_admin"].filter.exclude_system_accounts is False
    assert [g.dimension for g in segs["admin_initiator_processes"].group_by] == [D.INITIATOR_PROCESS]
