from optimizer.shift_optimizer import ShiftOptimizer
from optimizer.base_constraint import BaseConstraint
from optimizer.primary_shift.work_constraints import WorkConstraints
from optimizer.concurrent_shift.concurrent_constraints import ConcurrentConstraints
from ortools.sat.python import cp_model
import pandas as pd
import pytest
from types import SimpleNamespace


def test_maximum_candidate_assignment_detects_shared_staff_conflict():
    candidates = {
        "3F": ["NameA", "NameB"],
        "4F": ["NameA", "NameB"],
    }
    requirements = {"3F": 2, "4F": 2}

    assert WorkConstraints._maximum_candidate_assignment(candidates, requirements) == 2


def _make_concurrent_constraint_for_eligibility_test():
    model = cp_model.CpModel()
    staff = pd.DataFrame(
        {"RI": [True, False, False], "NST": [False, True, False]},
        index=["RIStaff", "NSTStaff", "NoConcurrentStaff"],
    )
    constraint = ConcurrentConstraints.__new__(ConcurrentConstraints)
    constraint.model = model
    constraint.optimizer = object()
    constraint.staff = staff
    constraint.days = 1
    constraint.concurrent_sections = [2, 4]
    constraint.get_eligible_sections = {name: [] for name in staff.index}
    constraint.concurrent_shifts = {
        (name, 1, section): model.NewBoolVar(f"concurrent_{name}_{section}")
        for name in staff.index
        for section in constraint.concurrent_sections
    }

    constraint.add_concurrent_ri = lambda: None
    constraint.add_safety_wg = lambda: []
    constraint.add_dem_round = lambda: []
    constraint.add_heart_team = lambda: []
    constraint.add_infection_control = lambda: []
    constraint.add_audit_staff = lambda: None
    constraint.add_audit_fairness_penalties = lambda: []
    constraint.add_heart_team_fairness_penalties = lambda: []
    return constraint


def test_concurrent_base_allows_ri_only_for_ri_eligible_staff():
    constraint = _make_concurrent_constraint_for_eligibility_test()
    constraint.apply()
    constraint.model.Add(constraint.concurrent_shifts[("RIStaff", 1, 4)] == 1)

    status = cp_model.CpSolver().Solve(constraint.model)

    assert status in (cp_model.OPTIMAL, cp_model.FEASIBLE)


def test_concurrent_base_blocks_ri_for_staff_eligible_for_other_concurrent_work():
    constraint = _make_concurrent_constraint_for_eligibility_test()
    constraint.apply()
    constraint.model.Add(constraint.concurrent_shifts[("NSTStaff", 1, 4)] == 1)

    status = cp_model.CpSolver().Solve(constraint.model)

    assert status == cp_model.INFEASIBLE


def test_concurrent_base_blocks_all_work_when_staff_has_no_concurrent_eligibility():
    constraint = _make_concurrent_constraint_for_eligibility_test()
    constraint.apply()
    constraint.model.Add(constraint.concurrent_shifts[("NoConcurrentStaff", 1, 2)] == 1)

    status = cp_model.CpSolver().Solve(constraint.model)

    assert status == cp_model.INFEASIBLE


def _make_tuesday_porifa_constraint():
    model = cp_model.CpModel()
    staff_names = ["PorifaA", "PorifaB"]
    primary_sections = [0, 4, 11, 17]
    shifts = {
        (staff, 1, section): model.NewBoolVar(f"shift_{staff}_{section}")
        for staff in staff_names
        for section in primary_sections
    }
    concurrent_shifts = {
        (staff, 1, 10): model.NewBoolVar(f"concurrent_{staff}_porifa")
        for staff in staff_names
    }
    hold_tuesday = model.NewBoolVar("hold_porifa_tuesday_1")
    constraint = ConcurrentConstraints.__new__(ConcurrentConstraints)
    constraint.model = model
    constraint.optimizer = SimpleNamespace(
        porifa_tuesday_vars={1: hold_tuesday},
        porifa_friday_vars={},
    )
    constraint.staff = pd.DataFrame(index=staff_names)
    constraint.get_eligible_sections = {
        staff: primary_sections for staff in staff_names
    }
    constraint.days = 1
    constraint.year = 2026
    constraint.month = 10
    constraint.shifts = shifts
    constraint.concurrent_shifts = concurrent_shifts
    constraint._get_weekday = lambda day: 1
    constraint._is_holiday = lambda day: False

    def build_section_availability(**kwargs):
        section_config = kwargs["section_configs"]["ポリファーマシー"]
        for staff in staff_names:
            available = model.NewBoolVar(f"porifa_available_{staff}")
            model.Add(available == 1)
            section_config["available_list"].append(available)
            section_config["assigned_list"].append(shifts[(staff, 1, 11)])
            kwargs["porifa_staff_ids"].append(staff)

    constraint._build_section_availability = build_section_availability
    return constraint, hold_tuesday, staff_names


def test_tuesday_porifa_is_concurrent_alongside_primary_work():
    constraint, hold_tuesday, staff_names = _make_tuesday_porifa_constraint()
    constraint.add_concurrent_porifa()

    work_constraints = WorkConstraints.__new__(WorkConstraints)
    work_constraints.model = constraint.model
    work_constraints.staff = constraint.staff
    work_constraints.days = 1
    work_constraints.primary_sections = [0, 4, 11, 17]
    work_constraints.concurrent_sections = [10]
    work_constraints.eligible_sections = constraint.get_eligible_sections
    work_constraints.shifts = constraint.shifts
    work_constraints.concurrent_shifts = constraint.concurrent_shifts
    work_constraints._work_day_vars = {}
    work_constraints._add_basic_constraints()

    constraint.model.Add(hold_tuesday == 1)
    for staff in staff_names:
        constraint.model.Add(constraint.shifts[(staff, 1, 4)] == 1)

    solver = cp_model.CpSolver()
    status = solver.Solve(constraint.model)

    assert status in (cp_model.OPTIMAL, cp_model.FEASIBLE)
    for staff in staff_names:
        assert solver.Value(constraint.concurrent_shifts[(staff, 1, 10)]) == 1
        assert solver.Value(constraint.shifts[(staff, 1, 4)]) == 1


def test_tuesday_porifa_is_not_assigned_when_not_held():
    constraint, hold_tuesday, staff_names = _make_tuesday_porifa_constraint()
    constraint.add_concurrent_porifa()
    constraint.model.Add(hold_tuesday == 0)

    solver = cp_model.CpSolver()
    status = solver.Solve(constraint.model)

    assert status in (cp_model.OPTIMAL, cp_model.FEASIBLE)
    for staff in staff_names:
        assert solver.Value(constraint.concurrent_shifts[(staff, 1, 10)]) == 0


def _make_work_day_constraint(days=1):
    model = cp_model.CpModel()
    staff = "Name1"
    sections = [0, 4, 17, 28, 29]
    shifts = {
        (staff, day, section): model.NewBoolVar(f"shift_{staff}_{day}_{section}")
        for day in range(1, days + 1)
        for section in sections
    }
    constraint = WorkConstraints.__new__(WorkConstraints)
    constraint.model = model
    constraint.staff = pd.DataFrame(index=[staff])
    constraint.days = days
    constraint.primary_sections = sections
    constraint.eligible_sections = {staff: sections}
    constraint.shifts = shifts
    constraint._work_day_vars = {}
    constraint.optimizer = SimpleNamespace(prev_month_shift=None)
    constraint._get_weekday = lambda day: 6
    constraint._is_holiday = lambda day: False
    return constraint, staff


def test_work_day_var_excludes_off_section_and_is_cached():
    constraint, staff = _make_work_day_constraint()
    work_day = constraint._get_work_day_var(staff, 1)
    assert constraint._get_work_day_var(staff, 1) is work_day

    constraint.model.Add(constraint.shifts[(staff, 1, 0)] == 1)
    solver = cp_model.CpSolver()

    assert solver.Solve(constraint.model) in (cp_model.OPTIMAL, cp_model.FEASIBLE)
    assert solver.Value(work_day) == 0


def test_basic_constraints_block_concurrent_work_on_off_day():
    constraint, staff = _make_work_day_constraint()
    concurrent = constraint.model.NewBoolVar("concurrent")
    constraint.concurrent_sections = [10]
    constraint.concurrent_shifts = {(staff, 1, 10): concurrent}
    constraint.model.Add(constraint.shifts[(staff, 1, 0)] == 1)
    constraint._add_basic_constraints()
    constraint.model.Add(concurrent == 1)

    assert cp_model.CpSolver().Solve(constraint.model) == cp_model.INFEASIBLE


@pytest.mark.parametrize("section", [17, 28, 29])
def test_work_day_var_counts_non_off_sections_as_work(section):
    constraint, staff = _make_work_day_constraint()
    work_day = constraint._get_work_day_var(staff, 1)
    constraint.model.Add(constraint.shifts[(staff, 1, section)] == 1)
    solver = cp_model.CpSolver()

    assert solver.Solve(constraint.model) in (cp_model.OPTIMAL, cp_model.FEASIBLE)
    assert solver.Value(work_day) == 1


def test_consecutive_work_counts_one_workday_even_if_multiple_sections_are_set():
    constraint, staff = _make_work_day_constraint(days=7)
    penalties = constraint.add_consecutive_work_constraints()
    constraint.model.Add(constraint.shifts[(staff, 1, 4)] == 1)
    constraint.model.Add(constraint.shifts[(staff, 1, 17)] == 1)
    for day in range(2, 7):
        constraint.model.Add(constraint.shifts[(staff, day, 4)] == 1)
    constraint.model.Add(constraint.shifts[(staff, 7, 0)] == 1)
    for penalty in penalties:
        constraint.model.Add(penalty == 0)
    solver = cp_model.CpSolver()

    assert solver.Solve(constraint.model) in (cp_model.OPTIMAL, cp_model.FEASIBLE)


def test_sunday_holiday_count_ignores_off_days_and_counts_each_day_once():
    constraint, staff = _make_work_day_constraint(days=2)
    penalties = constraint.add_sunday_holiday_work_constraints()
    constraint.model.Add(constraint.shifts[(staff, 1, 0)] == 1)
    constraint.model.Add(constraint.shifts[(staff, 2, 4)] == 1)
    constraint.model.Add(penalties[0] == 0)
    solver = cp_model.CpSolver()

    assert solver.Solve(constraint.model) in (cp_model.OPTIMAL, cp_model.FEASIBLE)


class DummyPrevMonthOncallOptimizer:
    def __init__(self):
        self.staff = pd.DataFrame(
            {"Floor": [1], "Floor2": [pd.NA], "Floor3": [pd.NA], "主任以上": [False]},
            index=["Name1"],
        )
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


def test_get_oncall_pair_handles_variable_created_in_staff_order():
    optimizer = ShiftOptimizer.__new__(ShiftOptimizer)
    expected = object()
    optimizer.night_shifts = {("Zelda", "Alice", 3): expected}

    assert optimizer.get_oncall_pair("Alice", "Zelda", 3) is expected


def test_get_oncall_pair_same_staff_returns_none():
    optimizer = ShiftOptimizer.__new__(ShiftOptimizer)
    optimizer.night_shifts = {}

    assert optimizer.get_oncall_pair("NameA", "NameA", 3) is None


def test_create_variables_builds_daily_work_and_oncall_pair_vars():
    optimizer = ShiftOptimizer.__new__(ShiftOptimizer)
    optimizer.model = cp_model.CpModel()
    optimizer.staff = pd.DataFrame(index=["NameA", "NameB"])
    optimizer.days = 2
    optimizer.year = 2026
    optimizer.month = 10
    optimizer.shifts = {}
    optimizer.concurrent_shifts = {}
    optimizer.night_shifts = {}
    optimizer.porifa_tuesday_vars = {}
    optimizer.porifa_friday_vars = {}

    optimizer.create_variables()

    assert optimizer.get_primary_work_var("NameA", 1) is optimizer.shifts[("NameA", 1, 1)]
    assert len(optimizer.shifts) == 4
    assert len(optimizer.night_shifts) == 2
    assert optimizer.get_oncall_pair("NameA", "NameB", 1) is optimizer.night_shifts[("NameA", "NameB", 1)]


def test_get_primary_shift_reads_from_primary_shift_dictionary():
    optimizer = ShiftOptimizer.__new__(ShiftOptimizer)
    expected = object()
    optimizer.shifts = {("NameA", 3, 4): expected}

    assert optimizer.get_primary_shift("NameA", 3, 4) is expected


def test_get_primary_work_status_returns_true_for_non_off_assignment():
    model = cp_model.CpModel()
    optimizer = ShiftOptimizer.__new__(ShiftOptimizer)
    optimizer.shifts = {("NameA", 3, 3): model.NewBoolVar("work_NameA_3")}
    model.Add(optimizer.shifts[("NameA", 3, 3)] == 1)
    solver = cp_model.CpSolver()
    assert solver.Solve(model) in (cp_model.OPTIMAL, cp_model.FEASIBLE)

    assert optimizer.get_primary_work_status(solver, "NameA", 3) is True


def test_get_primary_work_status_returns_false_for_off_assignment():
    model = cp_model.CpModel()
    optimizer = ShiftOptimizer.__new__(ShiftOptimizer)
    optimizer.shifts = {("NameA", 3, 3): model.NewBoolVar("work_NameA_3")}
    model.Add(optimizer.shifts[("NameA", 3, 3)] == 0)
    solver = cp_model.CpSolver()
    assert solver.Solve(model) in (cp_model.OPTIMAL, cp_model.FEASIBLE)

    assert optimizer.get_primary_work_status(solver, "NameA", 3) is False


def test_get_primary_work_status_returns_none_without_primary_variables():
    optimizer = ShiftOptimizer.__new__(ShiftOptimizer)
    optimizer.shifts = {}

    assert optimizer.get_primary_work_status(object(), "NameA", 3) is None


def _make_attendance_constraint(staff, eligible_sections, hopes, target, section_ids):
    model = cp_model.CpModel()
    optimizer = SimpleNamespace()
    work_vars = {
        (staff_name, 1): model.NewBoolVar(f"work_{staff_name}")
        for staff_name in staff.index
    }
    optimizer.get_primary_work_var = lambda staff_name, day: work_vars.get(
        (staff_name, day)
    )
    objective_terms = []
    optimizer.register_objective_term = lambda name, term: objective_terms.append(
        (name, term)
    )

    constraint = WorkConstraints.__new__(WorkConstraints)
    constraint.model = model
    constraint.optimizer = optimizer
    constraint.staff = staff
    constraint.days = 1
    constraint.month = 10
    constraint.shifts = {}
    constraint.primary_sections = []
    constraint.eligible_sections = eligible_sections
    constraint._work_day_vars = {}
    constraint._get_daily_attendance_target = lambda day: target
    constraint._attendance_section_ids = lambda day: section_ids
    constraint._get_weekday = lambda day: 0
    constraint._is_holiday = lambda day: False
    constraint._get_hope_value = lambda staff_name, day, default=7: hopes.get(
        staff_name, default
    )
    constraint._hope_matches = lambda value, values: value in values
    constraint._is_enabled_value = lambda value: bool(value)
    constraint._get_staff_column_value = lambda staff_name, column: (
        staff.loc[staff_name, column] if column in staff.columns else False
    )

    def no_previous_oncall(staff_name, day):
        was_oncall = model.NewBoolVar(f"was_oncall_{staff_name}")
        model.Add(was_oncall == 0)
        return was_oncall

    constraint._get_had_oncall_yesterday_var = no_previous_oncall
    return constraint, work_vars, objective_terms


def test_attendance_counts_staff_once_across_multiple_eligible_sections():
    staff = pd.DataFrame(
        {"休職": [False, False, False], "日曜出勤": [True, True, True]},
        index=["Floor4", "Floor5", "Both"],
    )
    constraint, work_vars, objective_terms = _make_attendance_constraint(
        staff=staff,
        eligible_sections={"Floor4": [4], "Floor5": [5], "Both": [4, 5]},
        hopes={},
        target=2,
        section_ids={4, 5},
    )

    constraint.apply_attendance_constraints()
    constraint.model.Minimize(sum(term for _, term in objective_terms))
    solver = cp_model.CpSolver()
    assert solver.Solve(constraint.model) in (cp_model.OPTIMAL, cp_model.FEASIBLE)

    assert sum(solver.Value(variable) for variable in work_vars.values()) == 2


def test_daily_attendance_target_uses_section_and_dispensing_requirements():
    constraint = WorkConstraints.__new__(WorkConstraints)
    constraint.month = 10
    constraint.days = 31
    constraint._get_weekday = lambda day: 0 if day == 1 else 6
    constraint._is_holiday = lambda day: False
    constraint._is_prev_day_holiday = lambda day: False
    constraint._get_section_min_requirements = lambda **kwargs: {
        "3F": 4,
        "4F": 5,
    }

    assert constraint._get_daily_attendance_target(1) == 15
    assert constraint._get_daily_attendance_target(2) == 4


def test_attendance_forces_leave_and_training_status_without_counting_training():
    staff = pd.DataFrame(
        {
            "休職": [True, False, False, False],
            "日曜出勤": [True, True, True, True],
        },
        index=["Leave", "OffHope", "Training", "Available"],
    )
    constraint, work_vars, objective_terms = _make_attendance_constraint(
        staff=staff,
        eligible_sections={
            "Leave": [4],
            "OffHope": [4],
            "Training": [4],
            "Available": [4],
        },
        hopes={"OffHope": 0, "Training": 6},
        target=1,
        section_ids={4},
    )

    constraint.apply_attendance_constraints()
    constraint.model.Minimize(sum(term for _, term in objective_terms))
    solver = cp_model.CpSolver()
    assert solver.Solve(constraint.model) in (cp_model.OPTIMAL, cp_model.FEASIBLE)

    assert solver.Value(work_vars[("Leave", 1)]) == 0
    assert solver.Value(work_vars[("OffHope", 1)]) == 0
    assert solver.Value(work_vars[("Training", 1)]) == 1
    assert solver.Value(work_vars[("Available", 1)]) == 1


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
    constraint.get_eligible_sections = optimizer.get_eligible_sections
    section_configs = {
        "調剤室": {
            "section_id": 1,
            "assigned_list": [],
            "available_list": [],
            "check_day_off": True,
            "check_oncall_next": True,
        }
    }

    constraint._build_section_availability(
        section_configs=section_configs,
        day=1,
        year=optimizer.year,
    )
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
    optimizer.concurrent_shifts = {}
    optimizer.night_shifts = {("Name1", "Name2", 1): model.NewBoolVar("pair_day_1")}
    optimizer.shifts = {
        ("Name1", 1, 17): model.NewBoolVar("ake_day_1"),
        ("Name1", 1, 1): model.NewBoolVar("disp_day_1"),
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
    optimizer.concurrent_shifts = {}
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
    optimizer.concurrent_shifts = {}
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
    optimizer.days = 10
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
            optimizer.shifts[(staff, day, 9)] = model.NewBoolVar(f"chemo_{staff}_{day}")
            optimizer.concurrent_shifts[(staff, day, 13)] = model.NewBoolVar(f"audit_am_{staff}_{day}")
            optimizer.concurrent_shifts[(staff, day, 14)] = model.NewBoolVar(f"audit_pm_{staff}_{day}")

    for staff in optimizer.staff.index:
        if staff != "NameA":
            model.Add(optimizer.shifts[(staff, 10, 1)] == 1)
    model.Add(optimizer.shifts[("NameA", 10, 1)] == 0)
    model.Add(optimizer.shifts[("NameA", 10, 9)] == 1)
    model.Add(optimizer.shifts[("NameB", 10, 9)] == 0)
    model.Add(optimizer.shifts[("NameC", 10, 9)] == 0)

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
    assert solver.Value(optimizer.concurrent_shifts[("NameA", 10, 13)]) == 1
    assert solver.Value(optimizer.concurrent_shifts[("NameB", 10, 13)]) == 0
    assert solver.Value(optimizer.concurrent_shifts[("NameC", 10, 13)]) == 0


def test_saturday_audit_am_is_zero_without_chemo_assignment():
    model = cp_model.CpModel()
    optimizer = ShiftOptimizer.__new__(ShiftOptimizer)
    optimizer.staff = pd.DataFrame({"RI": [False, False]}, index=["NameA", "NameB"])
    optimizer.days = 10
    optimizer.year = 2026
    optimizer.month = 1
    optimizer.holidays = []
    optimizer.hope_list = pd.DataFrame(index=["NameA", "NameB"])
    optimizer.primary_sections = [1]
    optimizer.concurrent_sections = [13, 14]
    optimizer.shifts = {}
    optimizer.concurrent_shifts = {}
    optimizer.night_shifts = {}
    optimizer.prev_month_oncall_staff_ids = set()

    for staff in optimizer.staff.index:
        for day in range(1, optimizer.days + 1):
            optimizer.shifts[(staff, day, 1)] = model.NewBoolVar(f"disp_{staff}_{day}")
            optimizer.shifts[(staff, day, 9)] = model.NewBoolVar(f"chemo_{staff}_{day}")
            optimizer.concurrent_shifts[(staff, day, 13)] = model.NewBoolVar(f"audit_am_{staff}_{day}")
            optimizer.concurrent_shifts[(staff, day, 14)] = model.NewBoolVar(f"audit_pm_{staff}_{day}")
        model.Add(optimizer.shifts[(staff, 10, 1)] == 1)
        model.Add(optimizer.shifts[(staff, 10, 9)] == 0)

    constraint = ConcurrentConstraints(model, optimizer)
    constraint.eligible_sections = {"NameA": [1, 9], "NameB": [1]}
    constraint.add_audit_staff()

    solver = cp_model.CpSolver()
    status = solver.Solve(model)

    assert status in (cp_model.OPTIMAL, cp_model.FEASIBLE)
    assert solver.Value(optimizer.concurrent_shifts[("NameA", 10, 13)]) == 0
    assert solver.Value(optimizer.concurrent_shifts[("NameB", 10, 13)]) == 0
