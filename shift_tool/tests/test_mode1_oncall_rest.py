from types import SimpleNamespace

import pandas as pd
import pytest
from ortools.sat.python import cp_model

from optimizer.mode1.primary_shift.work_constraints import WorkConstraints


def _constraint(days=5, previous_oncall=False):
    constraint = WorkConstraints.__new__(WorkConstraints)
    constraint.model = cp_model.CpModel()
    constraint.staff = pd.DataFrame({"休職": [False, False]}, index=["A", "B"])
    constraint.days = days
    constraint.get_eligible_sections = {"A": [1], "B": [16]}
    constraint.eligible_sections = constraint.get_eligible_sections
    constraint.prev_month_oncall_staff_ids = {"A"} if previous_oncall else set()
    constraint._had_oncall_yesterday_vars = {}
    constraint._day_off_vars = {}
    constraint._fixed_off_days = set()
    constraint.hope_list = pd.DataFrame(7, index=constraint.staff.index, columns=range(1, days + 1))
    constraint.hope_day_column_map = {day: day for day in range(1, days + 1)}
    constraint.debug_enabled = False
    work = {
        (staff, day): constraint.model.NewBoolVar(f"work_{staff}_{day}")
        for staff in constraint.staff.index for day in range(1, days + 1)
    }
    oncall = {
        day: constraint.model.NewBoolVar(f"oncall_{day}")
        for day in range(1, days + 1)
    }
    constraint.optimizer = SimpleNamespace(
        get_primary_work_var=lambda staff, day: work.get((staff, day)),
        get_oncall_pair=lambda staff, other, day: oncall.get(day),
        _normalize_attendance_mark=lambda value: str(value).strip(),
        prev_month_shift=pd.DataFrame({
            "Name": ["A", "B"],
            "-1": ["4", "4"],
            "-2": ["4", "4"],
            "-3": ["4", "4"],
            "-4": ["4", "4"],
        }),
    )
    return constraint, work, oncall


@pytest.mark.parametrize(("previous_oncall", "worked", "expected"), [
    (True, 1, 1),
    (True, 0, 0),
    (False, 1, 0),
])
def test_day_two_penalty_uses_previous_month_oncall(previous_oncall, worked, expected):
    constraint, work, _ = _constraint(days=2, previous_oncall=previous_oncall)
    constraint.model.Add(work["A", 2] == worked)
    penalties = constraint.add_day_off_oncallnextday()
    solver = cp_model.CpSolver()
    assert solver.Solve(constraint.model) == cp_model.OPTIMAL
    assert len(penalties) == 1
    assert solver.Value(penalties[0]) == expected


def test_day_three_penalty_uses_first_day_oncall():
    constraint, work, oncall = _constraint(days=3)
    constraint.model.Add(oncall[1] == 1)
    constraint.model.Add(work["A", 3] == 1)
    penalties = constraint.add_day_off_oncallnextday()
    solver = cp_model.CpSolver()
    assert solver.Solve(constraint.model) == cp_model.OPTIMAL
    assert solver.Value(penalties[1]) == 1


def test_oncall_rest_penalty_skips_work_request():
    constraint, _, _ = _constraint(days=2, previous_oncall=True)
    constraint.hope_list.loc["A", 2] = 1
    assert constraint.add_day_off_oncallnextday() == []


@pytest.mark.parametrize(("work_count", "expected"), [
    (5, cp_model.OPTIMAL),
    (6, cp_model.INFEASIBLE),
])
def test_consecutive_work_counts_recovery_after_current_month_oncall(work_count, expected):
    constraint, work, oncall = _constraint(days=7)
    constraint._work_day_vars = {}
    constraint.optimizer.prev_month_shift = pd.DataFrame({
        "Name": ["A", "B"],
        **{str(-day): ["指", "指"] for day in range(1, 7)},
    })
    for day in range(1, 8):
        constraint.model.Add(oncall[day] == int(day == work_count))
        constraint.model.Add(work["A", day] == int(day <= work_count))
    constraint.add_consecutive_work_constraints()

    assert cp_model.CpSolver().Solve(constraint.model) == expected


@pytest.mark.parametrize(("oncall_on_day_one", "expected"), [
    (True, cp_model.OPTIMAL),
    (False, cp_model.INFEASIBLE),
])
def test_four_days_off_window_exempts_previous_day_oncall(oncall_on_day_one, expected):
    constraint, work, oncall = _constraint(days=5)
    constraint.staff.loc["B", "休職"] = True
    constraint.model.Add(oncall[1] == int(oncall_on_day_one))
    constraint.model.Add(work["A", 1] == 1)
    for day in range(2, 6):
        constraint.model.Add(work["A", day] == 0)
    constraint.add_consecutive_day_off_constraints()
    assert cp_model.CpSolver().Solve(constraint.model) == expected


@pytest.mark.parametrize(("month", "day", "attribute"), [
    (10, 0, None),
    (12, 30, "previous_year_december_30_staff"),
    (12, 31, "previous_december_31_staff"),
    (1, 1, "previous_january_1_staff"),
    (1, 2, "previous_january_2_staff"),
    (1, 3, "previous_january_3_staff"),
])
def test_weighted_penalties_call_bound_methods(month, day, attribute):
    constraint, work, _ = _constraint(days=31)
    constraint.month = month
    for name in (
        "previous_year_december_30_staff", "previous_december_31_staff",
        "previous_january_1_staff", "previous_january_2_staff",
        "previous_january_3_staff",
    ):
        setattr(constraint, name, {"A"} if name == attribute else set())
    constraint.meeting_constraints = SimpleNamespace(
        fixed_manager_meeting=lambda: [],
        general_meeting=lambda: [],
        yakushin=lambda: [],
        fixed_medical_safety_working_group=lambda: [],
        second_friday_conference=lambda: [],
        day16to23=lambda: [],
    )
    constraint._meeting_attendance_penalties = lambda: []
    constraint.concurrent_constraints = SimpleNamespace(add_concurrent_porifa=lambda: [])
    constraint.add_porifa_pair_penalties = lambda: []
    constraint.add_primary_section_fairness_penalties = lambda: []
    constraint.add_consecutive_streak_fairness_penalties = lambda: ([], [])
    terms = []
    constraint.optimizer.register_objective_term = lambda name, term: terms.append((name, term))
    constraint.apply_weighted_dayworkpenalties()
    if attribute:
        constraint.model.Add(work["A", day] == 1)
    constraint.model.Minimize(sum(term for _, term in terms))
    solver = cp_model.CpSolver()
    assert solver.Solve(constraint.model) == cp_model.OPTIMAL
    assert len(terms) == 1
    assert solver.ObjectiveValue() > 0 if attribute else solver.ObjectiveValue() == 0


@pytest.mark.parametrize(("month", "day", "attribute"), [
    (12, 30, "previous_year_december_30_staff"),
    (12, 31, "previous_december_31_staff"),
    (1, 1, "previous_january_1_staff"),
    (1, 2, "previous_january_2_staff"),
    (1, 3, "previous_january_3_staff"),
])
@pytest.mark.parametrize(("hope", "expected"), [
    (7, cp_model.INFEASIBLE),
    (1, cp_model.OPTIMAL),
])
def test_previous_year_attendance_constraint_allows_work_request(month, day, attribute, hope, expected):
    constraint, work, _ = _constraint(days=31)
    constraint.month = month
    for name in (
        "previous_year_december_30_staff", "previous_december_31_staff",
        "previous_january_1_staff", "previous_january_2_staff", "previous_january_3_staff",
    ):
        setattr(constraint, name, {"A"} if name == attribute else set())
    constraint._is_year_end_or_new_year(
        last_first_day=day, staff="A", work_var=work["A", day],
        has_work_request=hope, forced_work_hopes={1, 6, 8, 9, 10, 11},
    )
    constraint.model.Add(work["A", day] == 1)
    assert cp_model.CpSolver().Solve(constraint.model) == expected
