import datetime
from types import SimpleNamespace

import jpholiday
import pandas as pd
import pytest
from ortools.sat.python import cp_model

from optimizer.mode1.constraint_diagnostics import TrackedCpModel
from optimizer.mode1.primary_shift.work_constraints import WorkConstraints
from optimizer.mode1.shift_optimizer import ShiftOptimizer


def _calendar_constraint(year, month):
    constraint = WorkConstraints.__new__(WorkConstraints)
    constraint.year = year
    constraint.month = month
    constraint.holiday_dates = {
        date for date, _ in jpholiday.month_holidays(year, month)
    }
    return constraint


@pytest.mark.parametrize(
    ("year", "month", "day", "target"),
    [
        (2026, 6, 7, 4),
        (2025, 5, 3, 4),
        (2025, 5, 4, 7),
        (2025, 5, 5, 4),
        (2025, 5, 6, 7),
        (2026, 9, 20, 4),
        (2026, 9, 21, 7),
        (2026, 9, 22, 4),
        (2026, 9, 23, 7),
        (2023, 12, 30, 4),
        (2023, 12, 31, 7),
        (2024, 1, 1, 4),
        (2024, 1, 2, 7),
        (2024, 1, 3, 4),
        (2024, 12, 30, 7),
        (2024, 12, 31, 4),
        (2025, 1, 1, 7),
        (2025, 1, 2, 4),
        (2025, 1, 3, 7),
    ],
)
def test_holiday_targets_across_consecutive_days_and_year_end(year, month, day, target):
    constraint = _calendar_constraint(year, month)
    assert constraint._get_daily_attendance_target(day) == target
    if constraint._is_year_end_holiday_date(datetime.date(year, month, day)):
        assert constraint._attendance_section_ids(day) == {1}
        assert constraint.get_year_end_dispensing_required(day) == target


def test_sunday_at_month_start_uses_previous_month_holiday(monkeypatch):
    constraint = _calendar_constraint(2026, 2)
    monkeypatch.setattr(
        jpholiday, "is_holiday", lambda date: date == datetime.date(2026, 1, 31)
    )
    assert constraint._get_daily_attendance_target(1) == 7


def _attendance_model(hope_values, eligible=None, target_date=(2026, 11, 1)):
    year, month, day = target_date
    assert day == 1
    constraint = _calendar_constraint(year, month)
    constraint.model = TrackedCpModel()
    constraint.days = 1
    constraint.staff = pd.DataFrame(
        {"休職": False, "日曜出勤": True}, index=list(hope_values)
    )
    constraint.eligible_sections = eligible or {name: [1] for name in hope_values}
    constraint.hope_list = pd.DataFrame({1: hope_values})
    constraint.hope_day_column_map = {1: 1}
    constraint.debug_enabled = False
    constraint._fixed_off_days = set()
    constraint._offrequest_excluded_days = set()
    work = {
        name: constraint.model.NewBoolVar(f"work_{name}") for name in hope_values
    }
    constraint.optimizer = SimpleNamespace(
        get_primary_work_var=lambda name, day: work[name],
        register_objective_term=lambda name, term: None,
    )
    constraint._is_year_end_or_new_year = lambda **kwargs: None
    constraint._get_had_oncall_yesterday_var = lambda name, day: constraint.model.NewConstant(0)
    constraint.add_sunday_holiday_work_constraints = lambda: []
    constraint.add_consecutive_work_constraints = lambda: []
    constraint.apply_attendance_constraints()
    return constraint.model, work


def test_half_days_count_as_half_and_training_is_excluded():
    model, work = _attendance_model({
        "A": 1, "B": 1, "C": 1, "D": 9, "E": 10, "Training": 6,
    })
    solver = cp_model.CpSolver()
    assert solver.Solve(model) == cp_model.OPTIMAL
    assert all(solver.Value(var) == 1 for var in work.values())


def _read_mode1_hopes(tmp_path, hopes):
    staff = pd.DataFrame({"Name": list(hopes), "Floor": 1})
    path = tmp_path / "staff.xlsx"
    with pd.ExcelWriter(path) as writer:
        staff.to_excel(writer, sheet_name="member_list", index=False, startrow=1)
    hope_list = pd.DataFrame({"Name": list(hopes), 1: list(hopes.values())})
    optimizer = ShiftOptimizer(
        year=2026, month=11, holidays=[], staff_list_pass=path,
        hope_list=hope_list, offrequest_day=8,
    )
    return optimizer.hope_list[1].to_dict()


@pytest.mark.parametrize("force_half_off", [False, True])
def test_real_half_day_hopes_require_work_and_count_half_a_person(
    tmp_path, force_half_off
):
    hopes = _read_mode1_hopes(tmp_path, {
        "A": "出", "B": "出", "C": "出",
        "D": "AM有PM出", "E": "PM指\nAM出",
    })
    model, work = _attendance_model(hopes)
    if force_half_off:
        model.Add(work["D"] == 0)
    solver = cp_model.CpSolver()
    status = solver.Solve(model)
    assert status == (cp_model.INFEASIBLE if force_half_off else cp_model.OPTIMAL)
    if not force_half_off:
        assert solver.Value(work["D"]) == solver.Value(work["E"]) == 1


@pytest.mark.parametrize("hope", ["AM指PM有", "AM夏PM有"])
@pytest.mark.parametrize("force_work", [False, True])
def test_two_half_day_leave_requests_require_full_day_off(tmp_path, hope, force_work):
    hopes = _read_mode1_hopes(tmp_path, {
        "A": "出", "B": "出", "C": "出", "D": "出", "E": hope,
    })
    model, work = _attendance_model(hopes)
    if force_work:
        model.Add(work["E"] == 1)
    solver = cp_model.CpSolver()
    status = solver.Solve(model)
    assert status == (cp_model.INFEASIBLE if force_work else cp_model.OPTIMAL)
    if not force_work:
        assert solver.Value(work["E"]) == 0


def test_half_day_oncall_ban_is_preserved_in_mode1_hopes(tmp_path):
    hopes = _read_mode1_hopes(tmp_path, {"A": "AM指×", "B": "PM出"})
    assert set(hopes["A"]) == {10, 2}
    assert hopes["B"] == 10


@pytest.mark.parametrize(
    "hopes",
    [
        {"A": 1, "B": 1, "C": 1},
        {"A": 1, "B": 1, "C": 1, "D": 1, "E": 1},
        {"A": 1, "B": 1, "C": 1, "D": 9},
    ],
)
def test_holiday_staffing_is_hard_for_shortage_or_excess(hopes):
    model, _ = _attendance_model(hopes)
    assert cp_model.CpSolver().Solve(model) == cp_model.INFEASIBLE


def test_outpatient_and_unqualified_forced_workers_are_not_counted():
    hopes = {"A": 1, "B": 1, "C": 1, "D": 1, "E": 1, "F": 1}
    eligible = {"A": [1], "B": [1], "C": [1], "D": [1], "E": [4], "F": [16]}
    model, work = _attendance_model(hopes, eligible)
    solver = cp_model.CpSolver()
    assert solver.Solve(model) == cp_model.OPTIMAL
    assert solver.Value(work["E"]) == 1


def test_seven_person_target_is_enforced():
    model, work = _attendance_model(
        {name: 1 for name in "ABCDEFG"}, target_date=(2025, 1, 1)
    )
    solver = cp_model.CpSolver()
    assert solver.Solve(model) == cp_model.OPTIMAL
    assert sum(solver.Value(var) for var in work.values()) == 7
