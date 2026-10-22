from backend.analytics import schedule_selected, cp_sat_select


def person(identifier, skill="机修", **extra):
    return {"staff_id":identifier,"skills":skill,"available_hours":8,**extra}


def task(identifier, **extra):
    return {"equipment_id":identifier,"hours":2,"people":1,"risk":.8,"required_skill":"机修",**extra}


def test_joint_selection_uses_feasible_alternative_when_high_priority_window_is_impossible():
    candidates=[task("A",cost=100,priority_score=.9,window_start="2026-10-20T08:00:00",window_end="2026-10-20T10:00:00"),task("B",cost=100,priority_score=.5,window_start="2026-10-20T10:00:00",window_end="2026-10-20T12:00:00")]
    staff=[person("P1",shift_start="2026-10-20T10:00:00",shift_end="2026-10-20T18:00:00")]
    scheduled,conflicts=schedule_selected(candidates,staff,[],"2026-10-20T08:00:00",allow_subset=True,budget=100,max_hours=2)
    assert [item["equipment_id"] for item in scheduled]==["B"]
    assert any(item.get("equipment_id")=="A" for item in conflicts)


def test_joint_selection_enforces_shared_stock_budget_and_total_hours_together():
    spare=[{"part_name":"轴承","quantity":1,"available_quantity":1}]
    candidates=[task("A",cost=70,priority_score=.9,spare_parts=spare),task("B",cost=70,priority_score=.5,spare_parts=spare),task("C",cost=30,priority_score=.4)]
    scheduled,conflicts=schedule_selected(candidates,[person("P1"),person("P2")],[],"2026-10-20T08:00:00",allow_subset=True,budget=100,max_hours=4)
    assert {item["equipment_id"] for item in scheduled}=={"A","C"}
    assert sum(item["cost"] for item in scheduled)<=100
    assert sum(item["hours"] for item in scheduled)<=4
    assert any(item.get("equipment_id")=="B" for item in conflicts)


def test_two_people_required_and_missing_skills_reported():
    scheduled, conflicts=schedule_selected([task("A",people=2)],[person("P1"),person("P2","机电")],[],"2026-10-19T08:00:00")
    assert not scheduled
    assert "2 名" in conflicts[0]["reason"]
    scheduled, conflicts=schedule_selected([task("A",people=2)],[person("P1"),person("P2")],[],"2026-10-19T08:00:00")
    assert not conflicts
    assert len(scheduled[0]["staff_ids"])==2


def test_production_occupancy_and_staff_cannot_overlap():
    orders=[{"equipment_id":"A","order_id":"O1","start_at":"2026-10-19T08:00:00","end_at":"2026-10-19T11:00:00"}]
    scheduled, conflicts=schedule_selected([task("A"),task("B")],[person("P1")],orders,"2026-10-19T08:00:00")
    assert not conflicts
    first=next(item for item in scheduled if item["equipment_id"]=="A")
    assert first["start_at"] >= "2026-10-19 11:00:00"
    a,b=scheduled
    assert a["end_at"]<=b["start_at"] or b["end_at"]<=a["start_at"]


def test_infeasible_window_and_spares_explained():
    tasks=[task("A",window_start="2026-10-19T08:00:00",window_end="2026-10-19T09:00:00"),task("B",spare_parts=[{"quantity":2,"available_quantity":1}])]
    scheduled,conflicts=schedule_selected(tasks,[person("P1")],[],"2026-10-19T08:00:00")
    assert not scheduled
    assert len(conflicts)==2


def test_scenario_team_capacity_and_existing_bookings_are_respected():
    people=[person(f"P{i}") for i in range(4)]
    scheduled,conflicts=schedule_selected([task("A",people=2),task("B",people=2)],people,[],"2026-10-19T08:00:00",staff_limit=2)
    assert not conflicts
    a,b=scheduled
    assert a["end_at"]<=b["start_at"] or b["end_at"]<=a["start_at"]
    booking={"equipment_id":"OLD","staff_id":"P0","start_at":"2026-10-19 08:00:00","end_at":"2026-10-19 10:00:00"}
    scheduled,conflicts=schedule_selected([task("A")],[people[0]],[],"2026-10-19T08:00:00",bookings=[booking])
    assert not conflicts
    assert scheduled[0]["start_at"]>="2026-10-19 10:00:00"


def test_shared_spare_stock_cannot_be_spent_twice_in_one_plan():
    tasks=[{**task(identifier),"cost":100,"priority_score":priority,"spare_parts":[{"part_name":"轴承","quantity":1,"available_quantity":1}]} for identifier,priority in [("A",.9),("B",.6)]]
    selected,status=cp_sat_select(tasks,1000,8,2)
    assert status in {"optimal","feasible"}
    assert len(selected)==1 and selected[0]["equipment_id"]=="A"
    scheduled,conflicts=schedule_selected(tasks,[person("P1"),person("P2")],[],"2026-10-19T08:00:00")
    assert not scheduled
    assert "共享备件" in conflicts[0]["reason"]


def test_skill_matching_does_not_assume_or_match_substrings():
    scheduled,conflicts=schedule_selected([task("A")],[person("P1","高级机修助理")],[],"2026-10-19T08:00:00")
    assert not scheduled and conflicts
    scheduled,conflicts=schedule_selected([task("A")],[{"staff_id":"P1","available_hours":8}],[],"2026-10-19T08:00:00")
    assert not scheduled and conflicts
    scheduled,conflicts=schedule_selected([task("A",required_skill="机修,电气")],[person("P1","机修，电气")],[],"2026-10-19T08:00:00")
    assert scheduled and not conflicts


def test_solver_timeout_is_not_reported_as_a_proven_conflict(monkeypatch):
    from ortools.sat.python import cp_model
    monkeypatch.setattr(cp_model.CpSolver,"solve",lambda self,model:cp_model.UNKNOWN)
    candidate={**task("A"),"cost":100}
    selected,status=cp_sat_select([candidate],1000,8,1)
    assert selected==[] and status=="time_limit"
    scheduled,conflicts=schedule_selected([candidate],[person("P1")],[],"2026-10-19T08:00:00")
    assert scheduled==[]
    assert "超时" in conflicts[0]["reason"]
    assert "不代表一定无解" in conflicts[0]["suggestion"]
