from types import SimpleNamespace

import pandas as pd
import pytest
from ortools.sat.python import cp_model

from optimizer.mode1.constraint_diagnostics import TrackedCpModel
from optimizer.mode1.primary_shift.work_constraints import WorkConstraints


def _make_constraint(*, hopes=None, fixed_days=(), off_limit=1):
    constraint = WorkConstraints.__new__(WorkConstraints)
    constraint.year = 2026
    constraint.month = 12
    constraint.days = 34
    constraint.staff = pd.DataFrame({"休職": [False]}, index=["A"])
    constraint.hope_list = pd.DataFrame(
        [{day: (hopes or {}).get(day, 7) for day in range(1, 35)}],
        index=["A"],
    )
    constraint.hope_day_column_map = {day: day for day in range(1, 35)}
    constraint.debug_enabled = False
    constraint._fixed_off_days = {("A", day) for day in fixed_days}
    constraint._offrequest_excluded_days = set()
    constraint.prev_month_oncall_staff_ids = set()
    constraint.get_eligible_sections = {"A": [1]}
    constraint.offrequest_day = off_limit
    constraint.model = TrackedCpModel()
    off_vars = {
        day: constraint.model.NewBoolVar(f"off_{day}")
        for day in range(1, 35)
    }
    constraint._get_dayoff_var = lambda staff, day: off_vars[day]
    constraint._get_had_oncall_yesterday_var = (
        lambda staff, day: constraint.model.NewConstant(0)
    )
    constraint.optimizer = SimpleNamespace()
    return constraint, off_vars


def test_january_fixed_days_are_not_diagnosed_against_december_limit():
    constraint, _ = _make_constraint(fixed_days=(1, 32, 33, 34))
    assert constraint.log_offrequest_conflicts() == {}
    assert constraint._fixed_counted_off_days("A") == [1]


def test_january_leave_does_not_exempt_december_off_limit():
    constraint, off = _make_constraint(hopes={32: 3})
    constraint.apply_offrequest_constraints()
    constraint.model.Add(off[1] == 1)
    constraint.model.Add(off[2] == 1)

    assert cp_model.CpSolver().Solve(constraint.model) == cp_model.INFEASIBLE


def test_january_off_days_do_not_consume_december_off_limit():
    constraint, off = _make_constraint()
    constraint.apply_offrequest_constraints()
    for day, var in off.items():
        constraint.model.Add(var == int(day in {1, 32, 33, 34}))

    assert cp_model.CpSolver().Solve(constraint.model) == cp_model.OPTIMAL


def test_december_leave_keeps_existing_exemption():
    constraint, off = _make_constraint(hopes={31: 3})
    constraint.apply_offrequest_constraints()
    constraint.model.Add(off[1] == 1)
    constraint.model.Add(off[2] == 1)

    assert cp_model.CpSolver().Solve(constraint.model) == cp_model.OPTIMAL


def test_december_fixed_days_still_trigger_diagnostic():
    constraint, _ = _make_constraint(fixed_days=(1, 2, 32))
    with pytest.raises(ValueError, match="指定休超過"):
        constraint.log_offrequest_conflicts()


def test_january_schedule_counts_first_three_days_toward_january_limit():
    constraint, off = _make_constraint()
    constraint.year, constraint.month, constraint.days = 2027, 1, 31
    constraint.apply_offrequest_constraints()
    constraint.model.Add(off[1] == 1)
    constraint.model.Add(off[3] == 1)

    assert cp_model.CpSolver().Solve(constraint.model) == cp_model.INFEASIBLE


@pytest.mark.parametrize(("year", "month", "days", "expected"), [
    (2026, 2, 28, 28),
    (2028, 2, 29, 29),
    (2026, 11, 30, 30),
    (2026, 12, 34, 31),
])
def test_current_month_days_respects_calendar_and_schedule_length(year, month, days, expected):
    constraint, _ = _make_constraint()
    constraint.year, constraint.month, constraint.days = year, month, days

    assert list(constraint._current_month_days()) == list(range(1, expected + 1))
