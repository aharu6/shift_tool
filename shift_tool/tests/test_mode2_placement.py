from datetime import date
from types import SimpleNamespace

import pandas as pd
from ortools.sat.python import cp_model

from create_calender import CalendarCreator
from optimizer.mode2.concurrent_shift.concurrent_constraints import ConcurrentConstraints
from optimizer.mode2.primary_shift.weekly_placement_optimizer import WeeklyPlacementOptimizer
from optimizer.mode2.shift_optimizer import ShiftOptimizer


def _concurrent_constraint(days=26):
    constraint = ConcurrentConstraints.__new__(ConcurrentConstraints)
    constraint.model = cp_model.CpModel()
    constraint.staff = pd.DataFrame(index=["A", "B", "C"])
    constraint.days, constraint.year, constraint.month = days, 2026, 6
    constraint.holiday_dates = {date(2026, 6, 3)}
    constraint.get_eligible_sections = {
        "A": [18, 19, 24, 27],
        "B": [18, 19, 24, 27],
        "C": [],
    }
    constraint.hope_list = pd.DataFrame(7, index=constraint.staff.index, columns=range(1, days + 1))
    constraint.hope_list.loc["B", 1] = 10
    constraint.hope_day_column_map = {day: day for day in range(1, days + 1)}
    constraint.debug_enabled = False
    constraint.optimizer = SimpleNamespace(
        get_attendance_status=lambda staff, day: not (staff == "B" and day == 26)
    )
    constraint.concurrent_shifts = {
        (staff, day, section): constraint.model.NewBoolVar(f"{staff}_{day}_{section}")
        for staff in constraint.staff.index
        for day in range(1, days + 1)
        for section in (1, 2, 8, 15)
    }
    return constraint


def test_mode2_concurrent_days_eligibility_and_objective():
    constraint = _concurrent_constraint()
    penalties = constraint.add_mode2_safety_wg()
    constraint.add_mode2_heart_team()
    constraint.add_mode2_nst()
    penalties += constraint.add_mode2_infection_control()
    constraint.model.Minimize(sum(penalties))
    solver = cp_model.CpSolver()
    assert solver.Solve(constraint.model) == cp_model.OPTIMAL
    shifts = constraint.concurrent_shifts
    assert solver.Value(shifts["A", 26, 8]) == 1
    assert solver.Value(shifts["B", 26, 8]) == 0
    assert solver.Value(shifts["A", 19, 8]) == 0
    assert sum(solver.Value(shifts[name, 2, 1]) for name in ("A", "B", "C")) == 1
    assert sum(solver.Value(shifts[name, 4, 2]) for name in ("A", "B", "C")) == 1
    assert solver.Value(shifts["B", 1, 15]) == 1
    assert solver.Value(shifts["A", 1, 15]) == 0
    for name in ("A", "B", "C"):
        assert solver.Value(shifts[name, 3, 15]) == 0
        assert solver.Value(shifts[name, 3, 2]) == 0


def test_heart_team_assignment_is_required_when_candidates_exist():
    constraint = _concurrent_constraint(days=2)
    constraint.add_mode2_heart_team()
    for name in ("A", "B"):
        constraint.model.Add(constraint.concurrent_shifts[name, 2, 1] == 0)
    assert cp_model.CpSolver().Solve(constraint.model) == cp_model.INFEASIBLE


def test_known_simultaneous_duties_are_incompatible():
    optimizer = ShiftOptimizer.__new__(ShiftOptimizer)
    optimizer.model = cp_model.CpModel()
    optimizer.staff = pd.DataFrame(index=["A"])
    optimizer.days, optimizer.year, optimizer.month = 1, 2026, 6
    optimizer.concurrent_shifts = {
        ("A", 1, section): optimizer.model.NewBoolVar(f"duty_{section}")
        for section in (1, 2, 4, 5, 8, 13, 14, 15)
    }
    optimizer.add_concurrent_time_conflicts()
    optimizer.model.Add(optimizer.concurrent_shifts["A", 1, 4] == 1)
    optimizer.model.Add(optimizer.concurrent_shifts["A", 1, 5] == 1)
    assert cp_model.CpSolver().Solve(optimizer.model) == cp_model.INFEASIBLE


def test_dispensing_counts_overlapping_pm_duties_once():
    constraint = WeeklyPlacementOptimizer.__new__(WeeklyPlacementOptimizer)
    constraint.model = cp_model.CpModel()
    constraint.staff = pd.DataFrame({"必須メンバー": [False]}, index=["A"])
    constraint.days, constraint.year, constraint.month = 1, 2026, 6
    constraint.holiday_dates = set()
    constraint.hope_list = pd.DataFrame()
    constraint.hope_day_column_map = {}
    constraint.debug_enabled = False
    constraint.eligible_sections = {"A": [1]}
    terms = []
    constraint.optimizer = SimpleNamespace(
        register_objective_term=lambda name, term: terms.append(term)
    )
    constraint.shifts = {
        ("A", 1, section): constraint.model.NewBoolVar(f"primary_{section}")
        for section in (1, 3, 4, 5, 6, 7, 8, 9)
    }
    constraint.concurrent_shifts = {
        ("A", 1, section): constraint.model.NewBoolVar(f"concurrent_{section}")
        for section in (1, 2, 4, 5, 8, 10, 15)
    }
    for (_, _, section), var in constraint.shifts.items():
        constraint.model.Add(var == int(section == 1))
    for (_, _, section), var in constraint.concurrent_shifts.items():
        constraint.model.Add(var == int(section in (4, 5)))
    constraint.add_daily_staffing_targets()
    constraint.model.Minimize(sum(terms))
    solver = cp_model.CpSolver()
    assert solver.Solve(constraint.model) == cp_model.OPTIMAL
    shortages = {
        label: solver.Value(var)
        for _, label, var, _ in constraint.optimizer.staffing_shortages
    }
    assert shortages["調剤AM"] == 6
    assert shortages["調剤PM"] == 7


def test_sunday_uses_manager_or_other_eligible_floor():
    constraint = WeeklyPlacementOptimizer.__new__(WeeklyPlacementOptimizer)
    constraint.model = cp_model.CpModel()
    constraint.staff = pd.DataFrame(
        {"ポリファーマシーチーム": [False, False, False]},
        index=["A", "B", "C"],
    )
    constraint.days, constraint.year, constraint.month = 7, 2026, 6
    constraint.holiday_dates = set()
    constraint.primary_sections = (0, 1, 6, 10, 11, 17, 25, 26)
    constraint.get_eligible_sections = {
        "A": [1, 25], "B": [6], "C": [1, 26]
    }
    constraint.mode1_attendance_list = pd.DataFrame(
        "", index=constraint.staff.index, columns=range(1, 8)
    )
    constraint.optimizer = SimpleNamespace(
        porifa_tuesday=2, _normalize_attendance_mark=lambda value: value
    )
    constraint.shifts = {
        (staff, day, section): constraint.model.NewBoolVar(f"{staff}_{day}_{section}")
        for staff in constraint.staff.index
        for day in range(1, 8)
        for section in constraint.primary_sections
        if section not in (0, 17)
    }
    constraint.apply_exclusive_assignment()
    solver = cp_model.CpSolver()
    assert solver.Solve(constraint.model) == cp_model.OPTIMAL
    assert solver.Value(constraint.shifts["A", 7, 25]) == 1
    assert solver.Value(constraint.shifts["B", 7, 6]) == 1
    assert solver.Value(constraint.shifts["C", 7, 26]) == 1


def test_weekly_excel_palliative_times_and_nst(tmp_path):
    data = pd.DataFrame({
        "Name": ["A", "B", "C"],
        "日付": [1, 4, 4],
        "専属業務": ["調剤室", "4階", "調剤室"],
        "兼務業務": ["緩和回診", "緩和回診", "NST回診"],
        "当直": ["なし", "当直担当", "なし"],
    })
    files = CalendarCreator.mk_weekly_shift_schedule(data, 2026, 6, tmp_path)
    assert len(files) == 1
    sheet = pd.read_excel(files[0], index_col=0)
    assert "AMA" in sheet.loc["調剤室", "06/01 (月曜日)"]
    assert "PMA" in sheet.loc["その他", "06/01 (月曜日)"]
    assert "PMB ◎" in sheet.loc["4階", "06/04 (木曜日)"]
    assert "AMB ◎" in sheet.loc["その他", "06/04 (木曜日)"]
    assert "NST回診" in sheet.loc["その他", "06/04 (木曜日)"]
