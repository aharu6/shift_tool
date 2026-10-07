import pandas as pd
from ortools.sat.python import cp_model

from optimizer.night_shift.oncall_constraints import OncallConstraints


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
        {"主任以上": [False, False, True]},
        index=["Staff A", "Staff B", "Senior"],
    )
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