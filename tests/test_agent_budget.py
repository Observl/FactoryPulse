from backend.agent_budget import PhaseBudget
from backend.agent_registry import validate_arguments


def test_time_starts_at_30_and_progress_adds_10_to_original_deadline():
    now=[100.]
    b=PhaseBudget(clock=lambda:now[0])
    now[0]=120.
    assert b.remaining()==10
    assert b.credit("equipment",{"devices":[{"equipment_id":"E1"}]})
    assert b.remaining()==20  # Deadline 140, not 160: progress adds allowance, not a fresh window.
    assert b.snapshot(True)["current_limit_seconds"]==40
    assert b.credit("history",{"series":[{"value":2}]})
    assert b.remaining()==30


def test_empty_errors_duplicate_cached_and_drafts_do_not_extend_time():
    b=PhaseBudget(clock=lambda:0.)
    record={"records":[{"staff_id":"P1"}],"category":"staff"}
    assert not b.credit("equipment",{"devices":[]})
    assert not b.credit("history",{"error":"not found"})
    assert not b.credit("equipment",{"source":"SQLite","message":"done"})
    assert not b.credit("draft_schedule",{"record":{"id":"x"}},draft=True)
    assert not b.credit("operations_context",record,cached=True)
    assert b.credit("operations_context",record)
    assert not b.credit("operations_context",{**record,"queried_at":"different-time","evidence_id":"another-id"})
    assert b.snapshot(True)["current_limit_seconds"]==40


def test_finished_and_failed_runs_reset_and_cannot_credit_after_deadline():
    now=[0.]
    b=PhaseBudget(clock=lambda:now[0])
    b.credit("equipment",{"devices":[{"equipment_id":"E1"}]})
    assert b.snapshot()["reset_after_run"] is True
    assert b.snapshot()["current_limit_seconds"]==30
    assert PhaseBudget(clock=lambda:now[0]).remaining()==30
    now[0]=41.
    assert not b.credit("history",{"series":[{"value":3}]})
    assert b.remaining()==0


def test_optional_device_arguments_accept_model_empty_and_null_without_loosening_ids():
    assert validate_arguments("equipment",{"equipment_id":""})=={}
    assert validate_arguments("equipment",{"equipment_id":None})=={}
    assert validate_arguments("compare_plans",{"scenario_id":None,"budget":None})=={}


def test_model_history_view_preserves_observed_extremes_without_mutating_evidence():
    from backend.agent_context import model_evidence
    points=[{"timestamp":str(i),"risk":i,"signal":10-i} for i in range(20)]
    result={"series":points,"maintenance":[{"maintenance_id":"M1"}],"source":"SQLite"}
    view=model_evidence("history",result)
    assert view["series"]==[points[0],points[-1]]
    assert view["series_context_summary"]["input_points"]==20
    assert len(result["series"])==20
    assert view["maintenance"]==result["maintenance"]
