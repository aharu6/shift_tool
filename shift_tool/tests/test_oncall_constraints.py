import pandas as pd
from ortools.sat.python import cp_model

from optimizer.night_shift.oncall_constraints import OncallConstraints
from config.objective_weights import (
    WEIGHT_ONCALL_PREV_MONTH_BALANCE,
    WEIGHT_ONCALL_TWO_PER_MONTH_HISTORY,
)


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