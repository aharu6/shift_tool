from optimizer.shift_optimizer import ShiftOptimizer
from optimizer.base_constraint import BaseConstraint
from optimizer.primary_shift.work_constraints import WorkConstraints
from optimizer.concurrent_shift.concurrent_constraints import ConcurrentConstraints
from ortools.sat.python import cp_model
import pandas as pd


def test_maximum_candidate_assignment_detects_shared_staff_conflict():
    candidates = {
        "3F": ["NameA", "NameB"],
        "4F": ["NameA", "NameB"],
    }
    requirements = {"3F": 2, "4F": 2}

    assert WorkConstraints._maximum_candidate_assignment(candidates, requirements) == 2


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


def test_leave_staff_has_no_eligible_sections():
    constraint = DummyPrevMonthOncallConstraint.__new__(DummyPrevMonthOncallConstraint)
    constraint.staff = pd.DataFrame(
        {"休職": [True], "Floor": [1]},
        index=["LeaveStaff"],
    )

    eligible_sections = constraint._get_eligible_sections()

    assert eligible_sections["LeaveStaff"] == []


def test_normalize_floor_column_accepts_labels_and_numeric_ids():
    values = pd.Series(["1-2", 1, 1.0, "1", "DI", 2.0, "課長"])

    normalized = ShiftOptimizer._normalize_floor_column(values)

    assert normalized.tolist() == [1, 1, 1, 1, 2, 2, 13]


def test_normalize_floor_column_accepts_pandas_integer_values():
    values = pd.Series([1, 14], dtype="int64")

    normalized = ShiftOptimizer._normalize_floor_column(values)

    assert normalized.tolist() == [1, 14]


def test_normalize_floor_column_rejects_unknown_values():
    values = pd.Series(["unknown", 7, 2.5, None])

    normalized = ShiftOptimizer._normalize_floor_column(values)

    assert normalized.isna().tolist() == [True, True, True, True]


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


def test_audit_staff_is_selected_only_from_dispensing_assignment():
    model = cp_model.CpModel()
    optimizer = ShiftOptimizer.__new__(ShiftOptimizer)
    optimizer.staff = pd.DataFrame({"RI": [False, False, False]}, index=["NameA", "NameB", "NameC"])
    optimizer.days = 1
    optimizer.year = 2026
    optimizer.month = 1
    optimizer.holidays = []
    optimizer.hope_list = pd.DataFrame(index=["NameA", "NameB", "NameC"])
    optimizer.primary_sections = [1]
    optimizer.concurrent_sections = [13, 14]
    optimizer.shifts = {
        ("NameA", 1, 1): model.NewBoolVar("disp_A"),
        ("NameB", 1, 1): model.NewBoolVar("disp_B"),
        ("NameC", 1, 1): model.NewBoolVar("disp_C"),
    }
    optimizer.concurrent_shifts = {
        ("NameA", 1, 13): model.NewBoolVar("audit_am_A"),
        ("NameA", 1, 14): model.NewBoolVar("audit_pm_A"),
        ("NameB", 1, 13): model.NewBoolVar("audit_am_B"),
        ("NameB", 1, 14): model.NewBoolVar("audit_pm_B"),
        ("NameC", 1, 13): model.NewBoolVar("audit_am_C"),
        ("NameC", 1, 14): model.NewBoolVar("audit_pm_C"),
    }
    optimizer.night_shifts = {}
    optimizer.prev_month_oncall_staff_ids = set()
    optimizer.holidays = []

    model.Add(optimizer.shifts[("NameA", 1, 1)] == 1)
    model.Add(optimizer.shifts[("NameB", 1, 1)] == 1)

    constraint = ConcurrentConstraints(model, optimizer)
    constraint.eligible_sections = {"NameA": [1], "NameB": [1], "NameC": []}
    constraint.add_audit_staff()

    # 調剤室非適格の人に監査を強制すると infeasible になることを確認
    model.Add(optimizer.concurrent_shifts[("NameC", 1, 13)] == 1)

    solver = cp_model.CpSolver()
    status = solver.Solve(model)

    assert status == cp_model.INFEASIBLE


def test_audit_am_selects_chemo_eligible_staff_on_saturday():
    model = cp_model.CpModel()
    optimizer = ShiftOptimizer.__new__(ShiftOptimizer)
    optimizer.staff = pd.DataFrame({"RI": [False, False, False]}, index=["NameA", "NameB", "NameC"])
    optimizer.days = 3
    optimizer.year = 2026
    optimizer.month = 1
    optimizer.holidays = []
    optimizer.hope_list = pd.DataFrame(index=["NameA", "NameB", "NameC"])
    optimizer.primary_sections = [1]
    optimizer.concurrent_sections = [13, 14]
    optimizer.shifts = {}
    optimizer.concurrent_shifts = {}
    optimizer.night_shifts = {}
    optimizer.prev_month_oncall_staff_ids = set()

    for staff in optimizer.staff.index:
        for day in range(1, optimizer.days + 1):
            optimizer.shifts[(staff, day, 1)] = model.NewBoolVar(f"disp_{staff}_{day}")
            optimizer.concurrent_shifts[(staff, day, 13)] = model.NewBoolVar(f"audit_am_{staff}_{day}")
            optimizer.concurrent_shifts[(staff, day, 14)] = model.NewBoolVar(f"audit_pm_{staff}_{day}")

    for staff in optimizer.staff.index:
        model.Add(optimizer.shifts[(staff, 3, 1)] == 1)

    constraint = ConcurrentConstraints(model, optimizer)
    constraint.eligible_sections = {
        "NameA": [1, 9],
        "NameB": [1, 9],
        "NameC": [1],
    }
    constraint.add_audit_staff()

    solver = cp_model.CpSolver()
    status = solver.Solve(model)

    assert status in (cp_model.OPTIMAL, cp_model.FEASIBLE)
    assert sum(solver.Value(optimizer.concurrent_shifts[(staff, 3, 13)]) for staff in ("NameA", "NameB")) == 1
    assert solver.Value(optimizer.concurrent_shifts[("NameC", 3, 13)]) == 0
