from types import SimpleNamespace

import pandas as pd
import pytest
from ortools.sat.python import cp_model

from optimizer.mode1.night_shift.oncall_constraints import OncallConstraints
from config.objective_weights import (
    WEIGHT_ONCALL_PREV_MONTH_BALANCE,
    WEIGHT_ONCALL_TWO_PER_MONTH_HISTORY,
)


def _make_oncall_request_validation_constraint(
    requests,
    *,
    days,
    floors=None,
    senior_staff=None,
    previous_oncall_by_day=None,
    sexes=None,
):
    staff_names = list(requests)
    floors = floors or {}
    senior_staff = senior_staff or set()
    sexes = sexes or {}
    staff = pd.DataFrame(
        {
            "当直": True,
            "休職": False,
            "Floor": [floors.get(name, 1) for name in staff_names],
            "主任以上": [name in senior_staff for name in staff_names],
            "Sex": [sexes.get(name, "M") for name in staff_names],
        },
        index=staff_names,
    )
    hope_list = pd.DataFrame(
        {
            day: [requests[name].get(day, 7) for name in staff_names]
            for day in range(1, days + 1)
        },
        index=staff_names,
    )
    constraint = OncallConstraints.__new__(OncallConstraints)
    constraint.days = days
    constraint.staff = staff
    constraint.hope_list = hope_list
    constraint.hope_day_column_map = {day: day for day in range(1, days + 1)}
    constraint.debug_enabled = False
    constraint.prev_month_oncall_staff_ids = set()
    constraint.optimizer = SimpleNamespace(
        prev_month_oncall_staff_by_day=previous_oncall_by_day or {}
    )
    return constraint


def test_required_floor_ignores_missing_values():
    assert OncallConstraints._has_required_floor(
        [pd.NA, 3, None],
        [1, 2, 3, 4, 5],
    )


@pytest.mark.parametrize(
    ("event_type", "anchor", "january_days"),
    [
        ("third_friday", 18, []),
        ("second_friday", 11, []),
        ("fourth_friday", 25, []),
        ("monday_tuesday_thursday", None, []),
        ("porifa", None, [32]),
        ("dementia_round", None, [32]),
        ("exective_meeting", None, []),
    ],
)
def test_extended_december_soft_event_dates(event_type, anchor, january_days):
    constraint = OncallConstraints.__new__(OncallConstraints)
    constraint.year, constraint.month, constraint.days = 2026, 12, 34
    constraint.holiday_dates = set()

    actual_anchor, days = constraint._get_soft_oncall_event_days({"event_type": event_type})

    assert actual_anchor == anchor
    assert [day for day in days if day > 31] == january_days


def test_manager_meeting_oncall_event_uses_january_week_number():
    constraint = OncallConstraints.__new__(OncallConstraints)
    constraint.year, constraint.month, constraint.days = 2028, 12, 34
    constraint.holiday_dates = set()

    _, days = constraint._get_soft_oncall_event_days({"event_type": "exective_meeting"})

    assert days == [4, 18, 32]


def test_extended_december_oncall_penalties_match_previous_january_dates():
    constraint = OncallConstraints.__new__(OncallConstraints)
    constraint.year, constraint.month, constraint.days = 2026, 12, 34
    constraint.previous_year_december_30_staff = {"A"}
    constraint.previous_december_31_staff = {"B"}
    constraint.previous_january_1_staff = {"C"}
    constraint.previous_january_2_staff = {"D"}
    constraint.previous_january_3_staff = {"E"}
    constraint.night_shifts = {
        ("A", "B", 30): "dec30",
        ("A", "B", 31): "dec31",
        ("A", "C", 32): "jan1",
        ("A", "D", 33): "jan2",
        ("A", "E", 34): "jan3",
        ("A", "Z", 1): "dec1",
    }

    penalties = constraint._previous_year_oncall_penalties()

    assert penalties == {
        (12, 30): ["dec30"],
        (12, 31): ["dec31"],
        (1, 1): ["jan1"],
        (1, 2): ["jan2"],
        (1, 3): ["jan3"],
    }


def test_extended_december_yakushin_uses_first_thursday_of_december():
    constraint = OncallConstraints.__new__(OncallConstraints)
    constraint.year, constraint.month, constraint.days = 2026, 12, 34
    constraint.model = cp_model.CpModel()
    constraint.staff = pd.DataFrame({"主任以上": [True, False]}, index=["A", "B"])
    constraint.hope_list = pd.DataFrame(7, index=["A", "B"], columns=range(1, 35))
    constraint.hope_day_column_map = {day: day for day in range(1, 35)}
    constraint.debug_enabled = False
    requested_days = []
    constraint.optimizer = SimpleNamespace(
        get_oncall_pair=lambda staff, other, day: requested_days.append(day)
    )

    assert constraint.yakushin_nextday() == []
    assert requested_days == [2]


def test_required_floor_rejects_missing_and_non_floor_values():
    assert not OncallConstraints._has_required_floor(
        [pd.NA, "調剤", None],
        [1, 2, 3, 4, 5],
    )


@pytest.mark.parametrize(
    ("work_status", "expected_status"),
    [
        (0, cp_model.INFEASIBLE),
        (1, cp_model.OPTIMAL),
    ],
)
def test_oncall_assignment_requires_primary_work(work_status, expected_status):
    model = cp_model.CpModel()
    staff = pd.DataFrame(index=["NameA", "NameB"])
    work_vars = {
        name: model.NewBoolVar(f"work_{name}")
        for name in staff.index
    }
    pair_var = model.NewBoolVar("oncall_NameA_NameB_day1")
    pair_vars = {("NameA", "NameB", 1): pair_var}

    constraint = OncallConstraints.__new__(OncallConstraints)
    constraint.model = model
    constraint.days = 1
    constraint.staff = staff
    constraint.optimizer = SimpleNamespace(
        get_oncall_pair=lambda staff1, staff2, day: pair_vars.get(
            (*sorted((staff1, staff2)), day)
        ),
        get_primary_work_var=lambda name, day: work_vars.get(name),
    )

    constraint.apply_primary_shift_constraints()
    model.Add(work_vars["NameA"] == work_status)
    model.Add(pair_var == 1)

    solver = cp_model.CpSolver()
    assert solver.Solve(model) == expected_status


def test_oncall_fairness_balances_previous_counts_excluding_senior_staff():
    constraint = OncallConstraints.__new__(OncallConstraints)
    constraint.model = cp_model.CpModel()
    constraint.days = 31
    constraint.staff = pd.DataFrame(
        {"主任以上": [False, False, True], "当直": [True, True, True]},
        index=["Staff A", "Staff B", "Senior"],
    )
    constraint.get_eligible_sections = {
        "Staff A": [],
        "Staff B": [],
        "Senior": [],
    }
    constraint.optimizer = type(
        "Optimizer",
        (),
        {"previous_oncall_counts": {"Staff A": 4, "Staff B": 1, "Senior": 99}},
    )()
    staff_a_count = constraint.model.NewIntVar(0, 2, "staff_a_month_count")
    staff_b_count = constraint.model.NewIntVar(0, 2, "staff_b_month_count")
    senior_count = constraint.model.NewIntVar(0, 1, "senior_month_count")
    constraint.monthly_oncall_counts = {
        "Staff A": staff_a_count,
        "Staff B": staff_b_count,
        "Senior": senior_count,
    }

    penalties = constraint.add_oncall_fairness_penalties()
    constraint.model.Add(staff_a_count + staff_b_count == 3)
    constraint.model.Add(senior_count == 1)
    constraint.model.Minimize(sum(penalties))

    solver = cp_model.CpSolver()
    status = solver.Solve(constraint.model)

    assert status == cp_model.OPTIMAL
    assert solver.Value(staff_a_count) == 1
    assert solver.Value(staff_b_count) == 2
    assert solver.Value(penalties[0]) == 2


def test_previous_month_target_precedes_two_oncall_history_fairness():
    constraint = OncallConstraints.__new__(OncallConstraints)
    constraint.model = cp_model.CpModel()
    constraint.staff = pd.DataFrame(
        {
            "主任以上": [False, False, False],
            "当直": [True, True, True],
        },
        index=["Staff A", "Staff B", "Staff C"],
    )
    constraint.get_eligible_sections = {staff: [] for staff in constraint.staff.index}
    constraint.optimizer = type(
        "Optimizer",
        (),
        {
            "previous_month_oncall_counts": {
                "Staff A": 1,
                "Staff B": 2,
                "Staff C": 2,
            },
            "previous_months_with_two_oncalls": {
                "Staff A": 12,
                "Staff B": 1,
                "Staff C": 10,
            },
        },
    )()
    monthly_counts = {
        staff: constraint.model.NewIntVar(0, 2, f"{staff}_monthly_count")
        for staff in constraint.staff.index
    }
    constraint.monthly_oncall_counts = monthly_counts

    balance_penalties = constraint.add_oncall_prev_month_balance_penalties()
    history_penalties = constraint.add_oncall_two_per_month_history_penalties()
    constraint.model.Add(sum(monthly_counts.values()) == 5)
    constraint.model.Minimize(
        WEIGHT_ONCALL_PREV_MONTH_BALANCE * sum(balance_penalties)
        + WEIGHT_ONCALL_TWO_PER_MONTH_HISTORY * sum(history_penalties)
    )

    solver = cp_model.CpSolver()
    status = solver.Solve(constraint.model)

    assert status == cp_model.OPTIMAL
    assert solver.Value(monthly_counts["Staff A"]) == 2
    assert solver.Value(monthly_counts["Staff B"]) == 2
    assert solver.Value(monthly_counts["Staff C"]) == 1


def test_oncall_request_is_hard_constraint_even_when_objective_prefers_other_pair():
    constraint = OncallConstraints.__new__(OncallConstraints)
    constraint.model = cp_model.CpModel()
    constraint.days = 1
    constraint.staff = pd.DataFrame(index=["Requester", "Partner", "Other"])
    constraint.hope_list = pd.DataFrame(
        {1: [8, 7, 7]},
        index=constraint.staff.index,
    )
    constraint.hope_day_column_map = {1: 1}
    constraint.debug_enabled = False
    pair_vars = {
        ("Other", "Partner", 1): constraint.model.NewBoolVar("other_pair"),
        ("Other", "Requester", 1): constraint.model.NewBoolVar("requester_pair"),
        ("Partner", "Requester", 1): constraint.model.NewBoolVar("partner_pair"),
    }
    constraint.optimizer = type(
        "Optimizer",
        (),
        {
            "get_oncall_pair": lambda self, staff1, staff2, day: pair_vars.get(
                (*sorted((staff1, staff2)), day)
            )
        },
    )()

    constraint.model.Add(sum(pair_vars.values()) == 1)
    constraint._add_hard_oncall_request_constraints()
    constraint.model.Maximize(pair_vars[("Other", "Partner", 1)])

    solver = cp_model.CpSolver()
    status = solver.Solve(constraint.model)

    assert status == cp_model.OPTIMAL
    assert solver.Value(pair_vars[("Other", "Partner", 1)]) == 0
    assert solver.Value(pair_vars[("Other", "Requester", 1)]) + solver.Value(
        pair_vars[("Partner", "Requester", 1)]
    ) == 1


def test_oncall_request_conflict_with_hard_constraint_is_infeasible():
    constraint = OncallConstraints.__new__(OncallConstraints)
    constraint.model = cp_model.CpModel()
    constraint.days = 1
    constraint.staff = pd.DataFrame(index=["Requester", "Partner"])
    constraint.hope_list = pd.DataFrame(
        {1: [8, 7]},
        index=constraint.staff.index,
    )
    constraint.hope_day_column_map = {1: 1}
    constraint.debug_enabled = False
    pair_var = constraint.model.NewBoolVar("requested_pair")
    constraint.optimizer = type(
        "Optimizer",
        (),
        {"get_oncall_pair": lambda self, staff1, staff2, day: pair_var},
    )()

    constraint.model.Add(pair_var == 0)
    constraint._add_hard_oncall_request_constraints()

    solver = cp_model.CpSolver()
    status = solver.Solve(constraint.model)

    assert status == cp_model.INFEASIBLE


@pytest.mark.parametrize(
    ("floor", "is_senior"),
    [(9, False), (1, True)],
)
def test_oncall_request_validation_uses_monthly_limit_for_outpatient_or_senior(
    floor,
    is_senior,
):
    constraint = _make_oncall_request_validation_constraint(
        {"Staff": {3: 8, 15: 8}},
        days=31,
        floors={"Staff": floor},
        senior_staff={"Staff"} if is_senior else set(),
    )

    with pytest.raises(ValueError, match="上限"):
        constraint._validate_oncall_requests()


def test_oncall_request_validation_rejects_same_floor_requesters_on_same_day():
    constraint = _make_oncall_request_validation_constraint(
        {"Staff A": {5: 8}, "Staff B": {5: 8}},
        days=31,
        floors={"Staff A": 2, "Staff B": 2},
    )

    with pytest.raises(ValueError, match="同一フロア"):
        constraint._validate_oncall_requests()


def test_oncall_request_validation_logs_reasons_when_request_has_no_eligible_partner(
    capsys,
):
    constraint = _make_oncall_request_validation_constraint(
        {"Requester": {5: 8}, "Partner": {}},
        days=31,
        floors={"Requester": 1, "Partner": 2},
        sexes={"Requester": "M", "Partner": "W"},
    )

    with pytest.raises(ValueError, match="相手候補がいません"):
        constraint._validate_oncall_requests()

    output = capsys.readouterr().out
    assert "[当直希望候補ログ]" in output
    assert "[当直希望候補] day=5, 希望者=Requester, 候補数=0" in output
    assert "異性" in output
    assert "除外理由別件数" in output


def test_oncall_request_validation_allows_two_senior_requesters():
    constraint = _make_oncall_request_validation_constraint(
        {"Senior A": {5: 8}, "Senior B": {5: 8}},
        days=31,
        floors={"Senior A": 1, "Senior B": 2},
        senior_staff={"Senior A", "Senior B"},
    )
    constraint._validate_monthly_oncall_feasibility = lambda: None

    requests = constraint._validate_oncall_requests()

    assert requests == {5: ["Senior A", "Senior B"]}


def test_monthly_oncall_validation_accepts_complete_daily_pair_assignment():
    constraint = _make_oncall_request_validation_constraint(
        {f"Staff {index}": {} for index in range(4)},
        days=2,
        floors={f"Staff {index}": index + 1 for index in range(4)},
    )

    requests = constraint._validate_oncall_requests()

    assert requests == {}


def test_monthly_oncall_validation_includes_hard_requests_in_daily_assignment():
    constraint = _make_oncall_request_validation_constraint(
        {
            "Requester": {1: 8},
            "Staff B": {},
            "Staff C": {},
            "Staff D": {},
        },
        days=2,
        floors={"Requester": 1, "Staff B": 2, "Staff C": 3, "Staff D": 4},
    )

    requests = constraint._validate_oncall_requests()

    assert requests == {1: ["Requester"]}


def test_monthly_oncall_validation_rejects_day_without_eligible_pair():
    constraint = _make_oncall_request_validation_constraint(
        {
            "Staff A": {2: 2},
            "Staff B": {2: 2},
            "Staff C": {2: 2},
            "Staff D": {2: 2},
        },
        days=2,
        floors={"Staff A": 1, "Staff B": 2, "Staff C": 3, "Staff D": 4},
    )

    with pytest.raises(ValueError, match="候補ペアがない日=\\[2\\]"):
        constraint._validate_oncall_requests()


def test_monthly_oncall_validation_rejects_when_staff_cannot_all_meet_minimum():
    constraint = _make_oncall_request_validation_constraint(
        {"Staff A": {}, "Staff B": {}, "Staff C": {}},
        days=2,
        floors={"Staff A": 1, "Staff B": 2, "Staff C": 3},
    )

    with pytest.raises(ValueError, match="通常スタッフ月1回以上"):
        constraint._validate_oncall_requests()


def test_oncall_request_validation_rejects_requests_within_seven_days():
    constraint = _make_oncall_request_validation_constraint(
        {"Staff": {2: 8, 9: 8}},
        days=31,
    )

    with pytest.raises(ValueError, match="7日以内"):
        constraint._validate_oncall_requests()


def test_oncall_request_validation_rejects_spacing_conflict_with_previous_month():
    constraint = _make_oncall_request_validation_constraint(
        {"Staff": {7: 8}},
        days=31,
        previous_oncall_by_day={0: ["Staff"]},
    )

    with pytest.raises(ValueError, match="前月の当直履歴"):
        constraint._validate_oncall_requests()


@pytest.mark.parametrize("next_day_hope", [0, 1, 3, 4, 5, 6, 9, 10, 11, 12, 13, 14, 15])
def test_oncall_request_validation_rejects_blocking_next_day_hope(next_day_hope):
    constraint = _make_oncall_request_validation_constraint(
        {"Staff": {4: 8, 5: next_day_hope}},
        days=31,
    )

    with pytest.raises(ValueError, match="翌日の"):
        constraint._validate_oncall_requests()


def test_joint_request_diagnostic_finds_shared_partner_monthly_limit_conflict():
    constraint = _make_oncall_request_validation_constraint(
        {
            "Requester A": {1: 8},
            "Requester B": {9: 8},
            "Limited Partner": {},
        },
        days=10,
        floors={"Requester A": 1, "Requester B": 1, "Limited Partner": 9},
    )

    active_staff, requests_by_day, pairs_by_day = (
        constraint._get_hard_compatible_oncall_pairs()
    )
    assert pairs_by_day[1]
    assert pairs_by_day[9]

    model, _ = constraint._build_joint_request_model(
        active_staff,
        requests_by_day,
        pairs_by_day,
    )
    solver = cp_model.CpSolver()

    assert solver.Solve(model) == cp_model.INFEASIBLE


def test_monthly_feasibility_does_not_require_oncall_from_staff_with_no_available_days():
    constraint = _make_oncall_request_validation_constraint(
        {
            "Staff A": {},
            "Staff B": {},
            "Staff C": {},
            "Staff D": {},
            "Leave": {day: 3 for day in range(1, 3)},
        },
        days=2,
        floors={"Staff A": 1, "Staff B": 2, "Staff C": 3, "Staff D": 4, "Leave": 5},
    )
    active_staff, _, pairs_by_day = constraint._get_hard_compatible_oncall_pairs(
        enforced_request_days=set()
    )

    model, selected_by_staff = constraint._build_joint_request_model(
        active_staff,
        {},
        pairs_by_day,
        request_days=set(),
        assign_every_day=True,
        require_regular_staff_once=True,
    )
    solver = cp_model.CpSolver()

    assert selected_by_staff["Leave"] == []
    assert solver.Solve(model) == cp_model.OPTIMAL


@pytest.mark.parametrize("hope_value", [0, 3, 4, 5, 12, 13, 14, 15])
def test_forced_off_hopes_are_not_monthly_oncall_candidate_days(hope_value):
    constraint = _make_oncall_request_validation_constraint(
        {
            "Off staff": {1: hope_value},
            "Staff B": {},
            "Staff C": {},
        },
        days=1,
        floors={"Off staff": 1, "Staff B": 2, "Staff C": 3},
    )
    _, _, pairs_by_day = constraint._get_hard_compatible_oncall_pairs(
        enforced_request_days=set()
    )

    assert pairs_by_day[1]
    assert all("Off staff" not in pair for pair in pairs_by_day[1])


def test_hard_monthly_constraint_skips_minimum_for_staff_without_candidate_days():
    staff_names = sorted(["Staff A", "Staff B", "Staff C", "Staff D", "Leave"])
    model = cp_model.CpModel()
    pair_vars = {
        (*pair, day): model.NewBoolVar(f"oncall_{pair[0]}_{pair[1]}_{day}")
        for day in (1, 2)
        for pair in (
            (staff_names[first], staff_names[second])
            for first in range(len(staff_names))
            for second in range(first + 1, len(staff_names))
        )
    }
    constraint = OncallConstraints.__new__(OncallConstraints)
    constraint.model = model
    constraint.days = 2
    constraint.staff = pd.DataFrame(
        {
            "当直": [True] * 5,
            "休職": [False] * 5,
            "Floor": list(range(1, 6)),
            "主任以上": [False] * 5,
            "Sex": ["M"] * 5,
        },
        index=staff_names,
    )
    constraint.hope_list = pd.DataFrame(
        [[3, 3] if name == "Leave" else [7, 7] for name in staff_names],
        index=staff_names,
        columns=[1, 2],
    )
    constraint.hope_day_column_map = {1: 1, 2: 2}
    constraint.debug_enabled = False
    constraint.optimizer = SimpleNamespace(
        prev_month_oncall_staff_by_day={},
        get_oncall_pair=lambda first, second, day: pair_vars.get(
            (*sorted((first, second)), day)
        ),
    )
    constraint.monthly_oncall_counts = {}

    constraint.add_oncall_constraints()
    model.Add(pair_vars[("Staff A", "Staff B", 1)] == 1)
    model.Add(pair_vars[("Staff C", "Staff D", 2)] == 1)
    solver = cp_model.CpSolver()

    assert solver.Solve(model) == cp_model.OPTIMAL
    assert solver.Value(constraint.monthly_oncall_counts["Leave"]) == 0, (
        constraint.monthly_oncall_counts.keys()
    )


def test_extended_month_diagnostic_separates_limits_and_keeps_cross_month_spacing():
    constraint = _make_oncall_request_validation_constraint(
        {"Staff A": {}, "Staff B": {}}, days=34,
        floors={"Staff A": 1, "Staff B": 2},
    )
    constraint.year, constraint.month = 2026, 12
    pairs = {day: [] for day in range(1, 35)}
    for day in (1, 10, 32):
        pairs[day] = [("Staff A", "Staff B")]
    model, assignments = constraint._build_joint_request_model(
        ["Staff A", "Staff B"], {day: ["Staff A"] for day in (1, 10, 32)}, pairs
    )
    solver = cp_model.CpSolver()
    assert solver.Solve(model) == cp_model.OPTIMAL
    assert len(assignments["Staff A"]) == 3

    pairs[30] = [("Staff A", "Staff B")]
    model, _ = constraint._build_joint_request_model(
        ["Staff A", "Staff B"], {30: ["Staff A"], 32: ["Staff A"]}, pairs
    )
    assert solver.Solve(model) == cp_model.INFEASIBLE


def test_extended_month_hard_constraints_count_december_and_january_separately():
    constraint = _make_oncall_request_validation_constraint(
        {"Staff A": {}, "Staff B": {}}, days=34,
        floors={"Staff A": 1, "Staff B": 2},
    )
    constraint.year, constraint.month = 2026, 12
    constraint.model = cp_model.CpModel()
    pairs = {
        day: constraint.model.NewBoolVar(f"pair_{day}")
        for day in range(1, 35)
    }
    constraint.optimizer.get_oncall_pair = lambda first, second, day: pairs[day]
    constraint.monthly_oncall_counts = {}
    constraint.add_oncall_constraints()
    for day, var in pairs.items():
        constraint.model.Add(var == int(day in {1, 10, 32}))

    solver = cp_model.CpSolver()
    assert solver.Solve(constraint.model) == cp_model.OPTIMAL
    assert solver.Value(constraint.monthly_oncall_counts["Staff A"]) == 2


def test_extended_month_does_not_count_january_only_candidate_as_december_candidate():
    requests = {day: 0 for day in range(1, 32)}
    constraint = _make_oncall_request_validation_constraint(
        {"Leave": requests, "Staff B": {}}, days=34,
        floors={"Leave": 1, "Staff B": 2},
    )
    constraint.year, constraint.month = 2026, 12
    assert "Leave" not in constraint._staff_with_hard_compatible_oncall_candidates()


def test_extended_month_candidate_does_not_use_other_month_request_limit():
    constraint = _make_oncall_request_validation_constraint(
        {"Staff A": {1: 8, 10: 8}, "Staff B": {}}, days=34,
        floors={"Staff A": 1, "Staff B": 2},
    )
    constraint.year, constraint.month = 2026, 12

    _, _, pairs = constraint._get_hard_compatible_oncall_pairs()

    assert ("Staff A", "Staff B") in pairs[32]
    assert not pairs[20]


def test_extended_month_request_validation_checks_monthly_limits_separately():
    constraint = _make_oncall_request_validation_constraint(
        {"Staff A": {1: 8, 10: 8, 32: 8}, "Staff B": {}}, days=34,
        floors={"Staff A": 1, "Staff B": 2},
    )
    constraint.year, constraint.month = 2026, 12
    constraint._validate_joint_oncall_requests = lambda: None
    constraint._validate_monthly_oncall_feasibility = lambda: None

    assert constraint._validate_oncall_requests() == {
        1: ["Staff A"], 10: ["Staff A"], 32: ["Staff A"]
    }

    constraint.hope_list.loc["Staff A", 20] = 8
    with pytest.raises(ValueError, match="希望回数が上限"):
        constraint._validate_oncall_requests()


@pytest.mark.parametrize(
    ("senior", "chosen_days", "expected"),
    [
        (False, (1, 10, 20, 32), cp_model.INFEASIBLE),
        (True, (1, 10), cp_model.INFEASIBLE),
        (True, (1, 32), cp_model.OPTIMAL),
        (True, (1, 32, 34), cp_model.INFEASIBLE),
    ],
)
def test_extended_month_hard_limits_apply_independently(senior, chosen_days, expected):
    constraint = _make_oncall_request_validation_constraint(
        {"Staff A": {}, "Staff B": {}}, days=34,
        floors={"Staff A": 1, "Staff B": 2},
        senior_staff={"Staff A"} if senior else None,
    )
    constraint.year, constraint.month = 2026, 12
    constraint.model = cp_model.CpModel()
    pairs = {
        day: constraint.model.NewBoolVar(f"pair_{day}")
        for day in range(1, 35)
    }
    constraint.optimizer.get_oncall_pair = lambda first, second, day: pairs[day]
    constraint.monthly_oncall_counts = {}
    constraint.add_oncall_constraints()
    for day, var in pairs.items():
        constraint.model.Add(var == int(day in chosen_days))

    assert cp_model.CpSolver().Solve(constraint.model) == expected


@pytest.mark.parametrize(("column", "value"), [("当直", False), ("休職", True)])
def test_extended_month_ineligible_staff_cannot_be_assigned_in_january(column, value):
    constraint = _make_oncall_request_validation_constraint(
        {"Staff A": {}, "Staff B": {}}, days=34,
        floors={"Staff A": 1, "Staff B": 2},
    )
    constraint.year, constraint.month = 2026, 12
    constraint.staff.loc["Staff A", column] = value
    constraint.model = cp_model.CpModel()
    pairs = {
        day: constraint.model.NewBoolVar(f"pair_{day}")
        for day in range(1, 35)
    }
    constraint.optimizer.get_oncall_pair = lambda first, second, day: pairs[day]
    constraint.monthly_oncall_counts = {}
    constraint.add_oncall_constraints()
    constraint.model.Add(pairs[32] == 1)

    assert cp_model.CpSolver().Solve(constraint.model) == cp_model.INFEASIBLE


@pytest.mark.parametrize("hope_value", [0, 3, 4, 5, 12, 13, 14, 15])
def test_isolated_available_day_before_requested_leave_exempts_monthly_oncall(hope_value):
    constraint = _make_oncall_request_validation_constraint(
        {
            "Leave": {2: hope_value},
            "Staff A": {},
            "Staff B": {},
            "Staff C": {},
            "Staff D": {},
        },
        days=2,
        floors={"Leave": 1, "Staff A": 2, "Staff B": 3, "Staff C": 4, "Staff D": 5},
    )
    model = cp_model.CpModel()
    constraint.model = model
    names = list(constraint.staff.index)
    constraint.staff["同期変数"] = range(len(names))
    pair_vars = {
        (first, second, day): model.NewBoolVar(f"oncall_{first}_{second}_{day}")
        for day in (1, 2)
        for index, first in enumerate(names)
        for second in names[index + 1:]
    }
    constraint.optimizer.get_oncall_pair = lambda first, second, day: pair_vars.get(
        (first, second, day), pair_vars.get((second, first, day))
    )
    constraint.monthly_oncall_counts = {}

    _, _, pairs_by_day = constraint._get_hard_compatible_oncall_pairs(
        enforced_request_days=set()
    )
    assert all(
        "Leave" not in pair for pairs in pairs_by_day.values() for pair in pairs
    )
    constraint._validate_monthly_oncall_feasibility()
    constraint.add_oncall_constraints()
    constraint.add_daily_oncall()
    solver = cp_model.CpSolver()
    assert solver.Solve(model) == cp_model.OPTIMAL
    assert solver.Value(constraint.monthly_oncall_counts["Leave"]) == 0
    for day in (1, 2):
        assert sum(
            solver.Value(var)
            for (*_, pair_day), var in pair_vars.items()
            if pair_day == day
        ) == 1

    model.Add(constraint.optimizer.get_oncall_pair("Leave", "Staff A", 1) == 1)
    assert solver.Solve(model) == cp_model.INFEASIBLE


def test_available_oncall_and_next_day_still_require_monthly_assignment():
    constraint = _make_oncall_request_validation_constraint(
        {"Staff A": {}, "Staff B": {}},
        days=2,
        floors={"Staff A": 1, "Staff B": 2},
    )
    model = cp_model.CpModel()
    pair_vars = {day: model.NewBoolVar(f"pair_{day}") for day in (1, 2)}
    constraint.model = model
    constraint.optimizer.get_oncall_pair = lambda first, second, day: pair_vars[day]
    constraint.monthly_oncall_counts = {}

    constraint.add_oncall_constraints()
    model.Add(sum(pair_vars.values()) == 0)

    assert cp_model.CpSolver().Solve(model) == cp_model.INFEASIBLE


def test_last_day_remains_candidate_without_next_month_hopes():
    constraint = _make_oncall_request_validation_constraint(
        {"Staff A": {1: 0}, "Staff B": {}},
        days=2,
        floors={"Staff A": 1, "Staff B": 2},
    )

    _, _, pairs_by_day = constraint._get_hard_compatible_oncall_pairs(
        enforced_request_days=set()
    )

    assert pairs_by_day[2] == [("Staff A", "Staff B")]


@pytest.mark.parametrize(
    ("available_days", "expected_days"),
    [({15}, set()), ({15, 16}, {15}), ({30}, {30})],
)
def test_month_long_leave_requires_two_adjacent_available_days(
    available_days, expected_days
):
    constraint = _make_oncall_request_validation_constraint(
        {
            "Leave": {day: 4 for day in range(1, 31) if day not in available_days},
            "Staff B": {},
        },
        days=30,
        floors={"Leave": 1, "Staff B": 2},
    )

    _, _, pairs_by_day = constraint._get_hard_compatible_oncall_pairs(
        enforced_request_days=set()
    )

    assert {
        day for day, pairs in pairs_by_day.items()
        if any("Leave" in pair for pair in pairs)
    } == expected_days


def test_oncall_request_validation_rejects_joint_monthly_limit_conflict():
    constraint = _make_oncall_request_validation_constraint(
        {
            "Requester A": {1: 8},
            "Requester B": {9: 8},
            "Limited Partner": {},
        },
        days=10,
        floors={"Requester A": 1, "Requester B": 1, "Limited Partner": 9},
    )

    with pytest.raises(ValueError, match="当直希望を同時に満たせません") as error:
        constraint._validate_oncall_requests()

    assert "1日" in str(error.value)
    assert "9日" in str(error.value)