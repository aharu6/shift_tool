from types import SimpleNamespace

import pandas as pd
import pytest
from ortools.sat.python import cp_model

from optimizer.night_shift.oncall_constraints import OncallConstraints
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
    constraint.optimizer = SimpleNamespace(
        prev_month_oncall_staff_by_day=previous_oncall_by_day or {}
    )
    return constraint


def test_required_floor_ignores_missing_values():
    assert OncallConstraints._has_required_floor(
        [pd.NA, 3, None],
        [1, 2, 3, 4, 5],
    )


def test_required_floor_rejects_missing_and_non_floor_values():
    assert not OncallConstraints._has_required_floor(
        [pd.NA, "調剤", None],
        [1, 2, 3, 4, 5],
    )


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

    requests = constraint._validate_oncall_requests()

    assert requests == {5: ["Senior A", "Senior B"]}


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


@pytest.mark.parametrize("next_day_hope", [0, 1, 3, 5, 6, 9, 10])
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