from types import SimpleNamespace

import pandas as pd
from ortools.sat.python import cp_model

from optimizer.mode1.primary_shift.work_constraints import WorkConstraints
from optimizer.mode1.shift_optimizer import ShiftOptimizer


def test_meeting_attendance_penalties_respect_hopes_and_roles():
    constraint = WorkConstraints.__new__(WorkConstraints)
    constraint.model = cp_model.CpModel()
    constraint.year, constraint.month, constraint.days = 2026, 10, 31
    constraint.holiday_dates = set()
    constraint.staff = pd.DataFrame({
        "主任以上": [True, True, False],
        "Floor": [1, 2, 1],
        "Floor2": [None, 13, None],
        "Floor3": [None, None, None],
    }, index=["A", "B", "C"])
    constraint.get_eligible_sections = {"A": [4], "B": [8, 25], "C": [4]}
    constraint.hope_list = pd.DataFrame(7, index=constraint.staff.index, columns=range(1, 32))
    constraint.hope_list.loc["A", 5] = 0
    constraint.hope_list.loc["A", 16] = 6
    constraint.hope_day_column_map = {day: day for day in range(1, 32)}
    constraint.debug_enabled = False
    work = {
        (staff, day): constraint.model.NewBoolVar(f"work_{staff}_{day}")
        for staff in constraint.staff.index for day in range(1, 32)
    }
    constraint.optimizer = SimpleNamespace(get_primary_work_var=lambda staff, day: work[staff, day])
    penalties = constraint._meeting_attendance_penalties()
    constraint.model.Minimize(sum(penalties))
    solver = cp_model.CpSolver()
    assert solver.Solve(constraint.model) == cp_model.OPTIMAL
    for staff, day in (("A", 1), ("A", 19), ("B", 9), ("B", 16)):
        assert solver.Value(work[staff, day]) == 1
    assert solver.Value(work["A", 5]) == 0
    assert solver.Value(work["A", 16]) == 0
    assert solver.Value(work["C", 19]) == 0
    assert solver.Value(work["B", 23]) == 0


def test_mode1_fixes_porifa_flags_and_minimizes_registered_objective():
    optimizer = ShiftOptimizer.__new__(ShiftOptimizer)
    optimizer.model = cp_model.CpModel()
    tuesday = optimizer.model.NewBoolVar("tuesday")
    friday = optimizer.model.NewBoolVar("friday")
    choice = optimizer.model.NewBoolVar("choice")
    optimizer.porifa_tuesday_vars = {6: tuesday}
    optimizer.porifa_friday_vars = {2: friday}
    optimizer.objective_terms = [("choice", 1 - choice)]
    optimizer.oncall_constraints = SimpleNamespace(apply=lambda: None)
    optimizer.work_constraints = SimpleNamespace(
        apply=lambda: None, log_oncall_work_candidate_overlap=lambda: None
    )
    optimizer.apply_all_constraints()
    solver = cp_model.CpSolver()
    assert solver.Solve(optimizer.model) == cp_model.OPTIMAL
    assert solver.Value(tuesday) == 0
    assert solver.Value(friday) == 0
    assert solver.Value(choice) == 1
