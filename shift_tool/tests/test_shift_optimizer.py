from optimizer.shift_optimizer import ShiftOptimizer
from optimizer.base_constraint import BaseConstraint
from optimizer.primary_shift.work_constraints import WorkConstraints
from ortools.sat.python import cp_model
import pandas as pd


class DummyPrevMonthOncallOptimizer:
    def __init__(self):
        self.staff = pd.DataFrame(index=["Name1"])
        self.days = 31
        self.year = 2026
        self.month = 1
        self.holidays = []
        self.shifts = {("Name1", 1, 17): cp_model.CpModel().NewBoolVar("prev_month_oncall_ake")}
        self.concurrent_shifts = {}
        self.hope_list = pd.DataFrame(index=["Name1"])
        self.primary_sections = [1, 17]
        self.concurrent_sections = []
        self.night_shifts = {}
        self.prev_month_oncall_staff_ids = {"Name1"}


class DummyPrevMonthOncallConstraint(BaseConstraint):
    def apply(self):
        return None


def test_get_days_in_month_leap_year_february():
    optimizer = ShiftOptimizer.__new__(ShiftOptimizer)
    optimizer.year = 2024
    optimizer.month = 2

    assert optimizer._get_days_in_month() == 29


def test_get_days_in_month_non_leap_february():
    optimizer = ShiftOptimizer.__new__(ShiftOptimizer)
    optimizer.year = 2026
    optimizer.month = 2

    assert optimizer._get_days_in_month() == 28


def test_get_oncall_pair_normalizes_order():
    optimizer = ShiftOptimizer.__new__(ShiftOptimizer)
    expected = object()
    optimizer.night_shifts = {("NameA", "NameB", 3): expected}

    assert optimizer.get_oncall_pair("NameA", "NameB", 3) is expected
    assert optimizer.get_oncall_pair("NameB", "NameA", 3) is expected


def test_get_oncall_pair_same_staff_returns_none():
    optimizer = ShiftOptimizer.__new__(ShiftOptimizer)
    optimizer.night_shifts = {}

    assert optimizer.get_oncall_pair("NameA", "NameA", 3) is None


def test_normalize_boolean_column_handles_staff_availability_values():
    values = pd.Series([False, True, 0, 1, "FALSE", "当直不可", "当直可", None])

    normalized = ShiftOptimizer._normalize_boolean_column(values)

    assert normalized.tolist() == [False, True, False, True, False, False, True, False]


def test_day_one_availability_excludes_staff_with_prev_month_oncall():
    model = cp_model.CpModel()
    optimizer = DummyPrevMonthOncallOptimizer()
    optimizer.shifts[("Name1", 1, 17)] = model.NewBoolVar("prev_month_oncall_ake")
    optimizer.shifts[("Name1", 1, 1)] = model.NewBoolVar("dispensing")
    optimizer.get_eligible_sections = {"Name1": [1, 17]}
    constraint = DummyPrevMonthOncallConstraint(model, optimizer)
    section_configs = {
        "調剤室": {
            "section_id": 1,
            "assigned_list": [],
            "available_list": [],
            "check_day_off": True,
            "check_oncall_next": True,
        }
    }

    constraint._build_section_availability(section_configs=section_configs, day=1)
    is_available = section_configs["調剤室"]["available_list"][0]
    solver = cp_model.CpSolver()
    model.Add(is_available == 0)
    status = solver.Solve(model)

    assert status == cp_model.OPTIMAL


def test_oncall_nextday_constraint_can_be_softened_for_feasible_schedule():
    model = cp_model.CpModel()
    optimizer = ShiftOptimizer.__new__(ShiftOptimizer)
    optimizer.staff = pd.DataFrame(index=["Name1"])
    optimizer.days = 2
    optimizer.year = 2026
    optimizer.month = 1
    optimizer.holidays = []
    optimizer.hope_list = pd.DataFrame(index=["Name1"])
    optimizer.primary_sections = [1, 17]
    optimizer.concurrent_sections = []
    optimizer.night_shifts = {("Name1", "Name2", 1): model.NewBoolVar("pair_day_1")}
    optimizer.shifts = {
        ("Name1", 1, 17): model.NewBoolVar("ake_day_1"),
        ("Name1", 2, 17): model.NewBoolVar("ake_day_2"),
        ("Name1", 2, 1): model.NewBoolVar("disp_day_2"),
    }
    optimizer.prev_month_oncall_staff_ids = set()
    optimizer.strict_oncall_nextday = False

    constraint = WorkConstraints(model, optimizer)
    constraint.eligible_sections = {"Name1": [1, 17]}
    constraint.add_on_call_day_off_nextday_constraints()
    model.Add(optimizer.shifts[("Name1", 2, 1)] == 1)

    solver = cp_model.CpSolver()
    status = solver.Solve(model)

    assert status in (cp_model.OPTIMAL, cp_model.FEASIBLE)


def test_oncall_nextday_constraint_strictly_blocks_ake_without_prev_oncall():
    model = cp_model.CpModel()
    optimizer = ShiftOptimizer.__new__(ShiftOptimizer)
    optimizer.staff = pd.DataFrame(index=["Name1", "Name2"])
    optimizer.days = 2
    optimizer.year = 2026
    optimizer.month = 1
    optimizer.holidays = []
    optimizer.hope_list = pd.DataFrame(index=["Name1", "Name2"])
    optimizer.primary_sections = [1, 17]
    optimizer.concurrent_sections = []
    optimizer.night_shifts = {("Name1", "Name2", 1): model.NewBoolVar("pair_day_1")}
    optimizer.get_oncall_pair = ShiftOptimizer.get_oncall_pair.__get__(optimizer, ShiftOptimizer)
    optimizer.shifts = {}
    for staff in optimizer.staff.index:
        for day in (1, 2):
            optimizer.shifts[(staff, day, 17)] = model.NewBoolVar(f"ake_{staff}_{day}")
            optimizer.shifts[(staff, day, 1)] = model.NewBoolVar(f"disp_{staff}_{day}")
    optimizer.prev_month_oncall_staff_ids = set()
    optimizer.strict_oncall_nextday = True

    constraint = WorkConstraints(model, optimizer)
    constraint.eligible_sections = {"Name1": [1, 17], "Name2": [1, 17]}
    constraint.add_on_call_day_off_nextday_constraints()

    # 前日当直がないのに明けを立てようとすると infeasible になることを確認
    model.Add(optimizer.night_shifts[("Name1", "Name2", 1)] == 0)
    model.Add(optimizer.shifts[("Name1", 2, 17)] == 1)

    solver = cp_model.CpSolver()
    status = solver.Solve(model)

    assert status == cp_model.INFEASIBLE


def test_oncall_nextday_constraint_strictly_requires_ake_after_prev_oncall():
    model = cp_model.CpModel()
    optimizer = ShiftOptimizer.__new__(ShiftOptimizer)
    optimizer.staff = pd.DataFrame(index=["Name1", "Name2"])
    optimizer.days = 2
    optimizer.year = 2026
    optimizer.month = 1
    optimizer.holidays = []
    optimizer.hope_list = pd.DataFrame(index=["Name1", "Name2"])
    optimizer.primary_sections = [1, 17]
    optimizer.concurrent_sections = []
    optimizer.night_shifts = {("Name1", "Name2", 1): model.NewBoolVar("pair_day_1")}
    optimizer.get_oncall_pair = ShiftOptimizer.get_oncall_pair.__get__(optimizer, ShiftOptimizer)
    optimizer.shifts = {}
    for staff in optimizer.staff.index:
        for day in (1, 2):
            optimizer.shifts[(staff, day, 17)] = model.NewBoolVar(f"ake_{staff}_{day}")
            optimizer.shifts[(staff, day, 1)] = model.NewBoolVar(f"disp_{staff}_{day}")
    optimizer.prev_month_oncall_staff_ids = set()
    optimizer.strict_oncall_nextday = True

    constraint = WorkConstraints(model, optimizer)
    constraint.eligible_sections = {"Name1": [1, 17], "Name2": [1, 17]}
    constraint.add_on_call_day_off_nextday_constraints()

    # 前日当直ありの場合、翌日の明けを0にすると infeasible になることを確認
    model.Add(optimizer.night_shifts[("Name1", "Name2", 1)] == 1)
    model.Add(optimizer.shifts[("Name1", 2, 17)] == 0)

    solver = cp_model.CpSolver()
    status = solver.Solve(model)

    assert status == cp_model.INFEASIBLE
