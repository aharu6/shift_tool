from optimizer.mode1.shift_optimizer import ShiftOptimizer
from optimizer.method.base_constraint import BaseConstraint
from optimizer.mode1.primary_shift.work_constraints import WorkConstraints
from optimizer.mode2.concurrent_shift.concurrent_constraints import ConcurrentConstraints
from config.floor_mapping import FLOOR_MAPPING
from ortools.sat.python import cp_model
import pandas as pd
import pytest
from types import SimpleNamespace
from optimizer.method.baseshiftoptimizer import BaseShiftOptimizer

def test_maximum_candidate_assignment_detects_shared_staff_conflict():
    candidates = {
        "3F": ["NameA", "NameB"],
        "4F": ["NameA", "NameB"],
    }
    requirements = {"3F": 2, "4F": 2}

    assert WorkConstraints._maximum_candidate_assignment(candidates, requirements) == 2


def test_primary_attendance_fairness_normalizes_by_available_days():
    model = cp_model.CpModel()
    staff_names = ["Staff A", "Staff B", "On leave", "Outpatient"]
    work_vars = {
        (staff, day): model.NewBoolVar(f"work_{staff}_{day}")
        for staff in staff_names
        for day in range(1, 6)
    }
    constraint = WorkConstraints.__new__(WorkConstraints)
    constraint.model = model
    constraint.days = 5
    constraint.month = 10
    constraint.debug_enabled = False
    constraint.staff = pd.DataFrame(
        {
            "Floor": [1, 1, 1, FLOOR_MAPPING["外来"]],
            "休職": [False, False, True, False],
        },
        index=staff_names,
    )
    constraint.eligible_sections = {
        "Staff A": [4],
        "Staff B": [4, 5],
        "On leave": [4],
        "Outpatient": [16],
    }
    constraint.hope_list = pd.DataFrame(
        {day: [0 if day == 3 else 7, 7, 7, 7] for day in range(1, 6)},
        index=staff_names,
    )
    constraint.hope_day_column_map = {day: day for day in range(1, 6)}
    constraint._get_weekday = lambda day: 0
    constraint._is_holiday = lambda day: False
    constraint._attendance_section_ids = lambda day: {4} if day <= 3 else {5}

    def no_oncall_yesterday(staff, day):
        variable = model.NewBoolVar(f"had_oncall_{staff}_{day}")
        model.Add(variable == int((staff, day) == ("Staff B", 2)))
        return variable

    constraint._get_had_oncall_yesterday_var = no_oncall_yesterday
    constraint.optimizer = SimpleNamespace(
        get_primary_work_var=lambda staff, day: work_vars[(staff, day)]
    )

    assert constraint._get_fairness_staff() == ["Staff A", "Staff B", "On leave"]
    penalties = constraint.add_primary_section_fairness_penalties()
    model.Add(sum(work_vars["Staff A", day] for day in range(1, 6)) + sum(
        work_vars["Staff B", day] for day in range(1, 6)
    ) == 3)
    for day in range(1, 6):
        model.Add(work_vars["On leave", day] == 0)
        model.Add(work_vars["Outpatient", day] == 0)
    model.Add(work_vars["Staff B", 2] == 0)
    model.Minimize(sum(penalties))

    solver = cp_model.CpSolver()
    status = solver.Solve(model)

    assert status == cp_model.OPTIMAL
    assert sum(solver.Value(work_vars["Staff A", day]) for day in range(1, 6)) == 1
    assert sum(solver.Value(work_vars["Staff B", day]) for day in range(1, 6)) == 2
    assert all(solver.Value(work_vars["On leave", day]) == 0 for day in range(1, 6))
    assert all(solver.Value(work_vars["Outpatient", day]) == 0 for day in range(1, 6))
    assert solver.Value(penalties[0]) == 0


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


def _make_porifa_constraint(day_weekdays, availability_by_day=None, ake_by_day=None):
    model = cp_model.CpModel()
    staff_names = ["PorifaA", "PorifaB"]
    primary_sections = [0, 4, 11, 17]
    days = max(day_weekdays)
    shifts = {
        (staff, day): model.NewBoolVar(f"shift_{staff}_{day}")
        for staff in staff_names
        for day in range(1, days + 1)
    }
    concurrent_shifts = {
        (staff, day): model.NewBoolVar(f"concurrent_{staff}_{day}")
        for staff in staff_names
        for day in range(1, days + 1)
    }
    hold_tuesday_vars = {
        day: model.NewBoolVar(f"hold_porifa_tuesday_{day}")
        for day, weekday in day_weekdays.items()
        if weekday == 1
    }
    hold_friday_vars = {
        day: model.NewBoolVar(f"hold_porifa_friday_{day}")
        for day, weekday in day_weekdays.items()
        if weekday == 4
    }
    constraint = ConcurrentConstraints.__new__(ConcurrentConstraints)
    constraint.model = model
    constraint.optimizer = SimpleNamespace(
        porifa_tuesday_vars=hold_tuesday_vars,
        porifa_friday_vars=hold_friday_vars.copy(),
        get_primary_work_var=lambda staff, day: shifts.get((staff, day)),
        get_concurrent_work_var=lambda staff, day: concurrent_shifts.get((staff, day)),
    )
    constraint.staff = pd.DataFrame(index=staff_names)
    constraint.get_eligible_sections = {
        staff: primary_sections for staff in staff_names
    }
    constraint.days = days
    constraint.year = 2026
    constraint.month = 10
    constraint.shifts = shifts
    constraint.concurrent_shifts = concurrent_shifts
    constraint._get_weekday = lambda day: day_weekdays.get(day, 0)
    constraint._is_holiday = lambda day: False
    availability_by_day = availability_by_day or {}
    def build_section_availability(**kwargs):
        day = kwargs["day"]
        section_config = kwargs["section_configs"]["ポリファーマシー"]
        for staff_index, staff in enumerate(staff_names):
            available = model.NewBoolVar(f"porifa_available_{staff}_{day}")
            is_available = availability_by_day.get(day, [True] * len(staff_names))[staff_index]
            model.Add(available == int(is_available))
            section_config["available_list"].append(available)
            section_config["assigned_list"].append(shifts[(staff, day)])
            kwargs["porifa_staff_ids"].append(staff)

    constraint._build_section_availability = build_section_availability
    return constraint, hold_tuesday_vars, hold_friday_vars, staff_names


def test_tuesday_porifa_is_concurrent_alongside_primary_work():
    constraint, hold_tuesday_vars, _, staff_names = _make_porifa_constraint(
        {1: 1}
    )
    constraint.add_concurrent_porifa()

    hold_tuesday = hold_tuesday_vars[1]
    constraint.model.Add(hold_tuesday == 1)
    for staff in staff_names:
        constraint.model.Add(constraint.shifts[(staff, 1)] == 1)

    solver = cp_model.CpSolver()
    status = solver.Solve(constraint.model)

    assert status in (cp_model.OPTIMAL, cp_model.FEASIBLE)
    for staff in staff_names:
        assert solver.Value(constraint.concurrent_shifts[(staff, 1)]) == 1
        assert solver.Value(constraint.shifts[(staff, 1)]) == 1


def test_tuesday_porifa_is_not_assigned_when_not_held():
    constraint, hold_tuesday_vars, _, staff_names = _make_porifa_constraint(
        {1: 1}
    )
    constraint.add_concurrent_porifa()
    constraint.model.Add(hold_tuesday_vars[1] == 0)

    solver = cp_model.CpSolver()
    status = solver.Solve(constraint.model)

    assert status in (cp_model.OPTIMAL, cp_model.FEASIBLE)
    for staff in staff_names:
        assert solver.Value(constraint.concurrent_shifts[(staff, 1)]) == 0


@pytest.mark.parametrize(
    ("value","expected"),
    [
        ("◎", "◎"),
        ("\u25ce\ufe0f", "◎"),
        ("\u25ce\ufe0e", "◎"),
        ("  ◎️ ", "◎"),
        (pd.NA, ""),
    ],
)
def test_normalize_attendance_mark(value, expected):
    assert BaseShiftOptimizer._normalize_attendance_mark(value) == expected


@pytest.mark.parametrize(
    "availability_by_day",
    [{1: [True, False]}],
    ids=["one-staff-unavailable"],
)

def test_friday_porifa_cannot_be_held_when_team_is_unavailable(
    availability_by_day,
):
    constraint, _, hold_friday_vars, _ = _make_porifa_constraint(
        {1: 4},
        availability_by_day=availability_by_day,
    )
    constraint.add_concurrent_porifa()
    constraint.model.Add(hold_friday_vars[1] == 1)

    assert cp_model.CpSolver().Solve(constraint.model) == cp_model.INFEASIBLE


def test_friday_porifa_holds_exactly_once_when_multiple_dates_are_schedulable():
    constraint, _, hold_friday_vars, staff_names = _make_porifa_constraint(
        {1: 4, 2: 0, 8: 4}
    )
    penalties = constraint.add_concurrent_porifa()

    solver = cp_model.CpSolver()
    status = solver.Solve(constraint.model)

    assert status in (cp_model.OPTIMAL, cp_model.FEASIBLE)
    assert sum(solver.Value(var) for var in hold_friday_vars.values()) == 1
    assert len(penalties) == len(staff_names) * len(hold_friday_vars)
    for day, hold_var in hold_friday_vars.items():
        for staff in staff_names:
            assert solver.Value(
                constraint.concurrent_shifts[(staff, day)]
            ) == solver.Value(hold_var)


def _make_work_day_constraint(days=1):
    model = cp_model.CpModel()
    staff = "Name1"
    sections = [0, 4, 17, 28, 29]
    shifts = {
        (staff, day): model.NewBoolVar(f"shift_{staff}_{day}")
        for day in range(1, days + 1)
    }
    constraint = WorkConstraints.__new__(WorkConstraints)
    constraint.model = model
    constraint.staff = pd.DataFrame(index=[staff])
    constraint.days = days
    constraint.primary_sections = sections
    constraint.eligible_sections = {staff: sections}
    constraint.shifts = shifts
    constraint._work_day_vars = {}
    constraint._day_off_vars = {}
    constraint._had_oncall_yesterday_vars = {}
    constraint.prev_month_oncall_staff_ids = set()
    constraint.optimizer = SimpleNamespace(
        prev_month_shift=None,
        prev_month_oncall_staff_ids=set(),
        get_primary_work_var=lambda staff_name, day: shifts.get((staff_name, day)),
        _normalize_attendance_mark=BaseShiftOptimizer._normalize_attendance_mark,
    )
    constraint._get_weekday = lambda day: 6
    constraint._is_holiday = lambda day: False
    return constraint, staff


def _make_fairness_constraint(floors, days, secondary_floors=None, tertiary_floors=None):
    model = cp_model.CpModel()
    staff_names = list(floors)
    staff_data = pd.DataFrame({'Floor': floors}, index=staff_names)
    for column, values in (
        ('Floor2', secondary_floors or {}),
        ('Floor3', tertiary_floors or {}),
    ):
        staff_data[column] = [values.get(staff, pd.NA) for staff in staff_names]

    shifts = {
        (staff, day): model.NewBoolVar(f'shift_{staff}_{day}')
        for staff in staff_names
        for day in range(1, days + 1)
    }
    constraint = WorkConstraints.__new__(WorkConstraints)
    constraint.model = model
    constraint.staff = staff_data
    constraint.days = days
    constraint.shifts = shifts
    constraint.debug_enabled = False
    constraint._work_day_vars = {}
    constraint._staff_max_consecutive_work_vars = {}
    constraint._staff_max_consecutive_off_vars = {}
    constraint.eligible_sections = {staff: [4] for staff in staff_names}
    constraint.hope_list = pd.DataFrame(
        {day: [7] * len(staff_names) for day in range(1, days + 1)},
        index=staff_names,
    )
    constraint.hope_day_column_map = {day: day for day in range(1, days + 1)}
    constraint._get_weekday = lambda day: 0
    constraint._is_holiday = lambda day: False
    constraint._attendance_section_ids = lambda day: {4}

    def no_oncall_yesterday(staff, day):
        variable = model.NewBoolVar(f'had_oncall_{staff}_{day}')
        model.Add(variable == 0)
        return variable

    constraint._get_had_oncall_yesterday_var = no_oncall_yesterday
    constraint.optimizer = SimpleNamespace(
        get_primary_work_var=lambda staff, day: shifts.get((staff, day)),
    )
    return constraint


def test_fairness_staff_excludes_only_primary_outpatient_floor():
    constraint = _make_fairness_constraint(
        {
            'WardStaff': 1,
            'DIStaff': 2,
            'OutpatientStaff': FLOOR_MAPPING['外来'],
            'MissingFloorStaff': pd.NA,
            'Floor2OutpatientStaff': 3,
            'Floor3OutpatientStaff': 4,
        },
        days=1,
        secondary_floors={'Floor2OutpatientStaff': FLOOR_MAPPING['外来']},
        tertiary_floors={'Floor3OutpatientStaff': FLOOR_MAPPING['外来']},
    )

    assert constraint._get_fairness_staff() == [
        'WardStaff',
        'DIStaff',
        'MissingFloorStaff',
        'Floor2OutpatientStaff',
        'Floor3OutpatientStaff',
    ]


def test_monthly_attendance_fairness_compares_all_non_outpatient_floors():
    constraint = _make_fairness_constraint(
        {'WardStaff': 1, 'DIStaff': 2, 'OutpatientStaff': FLOOR_MAPPING['外来']},
        days=2,
    )
    penalties = constraint.add_primary_section_fairness_penalties()
    constraint.model.Add(constraint.shifts[('WardStaff', 1)] == 1)
    constraint.model.Add(constraint.shifts[('WardStaff', 2)] == 1)
    constraint.model.Add(constraint.shifts[('DIStaff', 1)] == 1)
    constraint.model.Add(constraint.shifts[('DIStaff', 2)] == 0)
    constraint.model.Add(constraint.shifts[('OutpatientStaff', 1)] == 0)
    constraint.model.Add(constraint.shifts[('OutpatientStaff', 2)] == 0)

    solver = cp_model.CpSolver()
    assert solver.Solve(constraint.model) in (cp_model.OPTIMAL, cp_model.FEASIBLE)
    assert len(penalties) == 1
    assert solver.Value(penalties[0]) == 50


def test_streak_fairness_compares_all_non_outpatient_floors():
    constraint = _make_fairness_constraint(
        {'WardStaff': 1, 'DIStaff': 2, 'OutpatientStaff': FLOOR_MAPPING['外来']},
        days=5,
    )
    work_penalties, off_penalties = constraint.add_consecutive_streak_fairness_penalties(
        work_tolerance=0,
        off_tolerance=0,
    )
    schedules = {
        'WardStaff': [0, 0, 1, 1, 0],
        'DIStaff': [1, 1, 0, 0, 1],
        'OutpatientStaff': [1, 1, 1, 1, 1],
    }
    for staff, schedule in schedules.items():
        for day, works in enumerate(schedule, start=1):
            constraint.model.Add(constraint.shifts[(staff, day)] == works)
    for penalty in work_penalties + off_penalties:
        constraint.model.Add(penalty == 0)

    solver = cp_model.CpSolver()
    assert solver.Solve(constraint.model) in (cp_model.OPTIMAL, cp_model.FEASIBLE)
    assert len(work_penalties) == 1
    assert len(off_penalties) == 1


def test_fairness_penalties_are_skipped_with_fewer_than_two_non_outpatient_staff():
    constraint = _make_fairness_constraint(
        {'OutpatientStaff': FLOOR_MAPPING['外来']},
        days=2,
    )

    assert constraint.add_primary_section_fairness_penalties() == []
    assert constraint.add_consecutive_streak_fairness_penalties() == ([], [])


def test_work_day_var_uses_daily_flag_and_is_cached():
    constraint, staff = _make_work_day_constraint()
    work_day = constraint._get_work_day_var(staff, 1)
    assert constraint._get_work_day_var(staff, 1) is work_day

    constraint.model.Add(constraint.shifts[(staff, 1)] == 1)
    solver = cp_model.CpSolver()

    assert solver.Solve(constraint.model) in (cp_model.OPTIMAL, cp_model.FEASIBLE)
    assert solver.Value(work_day) == 1


def test_basic_constraints_block_concurrent_work_on_off_day():
    constraint, staff = _make_work_day_constraint()
    work_day = constraint._get_work_day_var(staff, 1)
    constraint.model.Add(constraint.shifts[(staff, 1)] == 0)

    solver = cp_model.CpSolver()
    assert solver.Solve(constraint.model) in (cp_model.OPTIMAL, cp_model.FEASIBLE)
    assert solver.Value(work_day) == 0


def test_work_day_var_reflects_daily_work_flag():
    constraint, staff = _make_work_day_constraint()
    work_day = constraint._get_work_day_var(staff, 1)
    constraint.model.Add(constraint.shifts[(staff, 1)] == 1)
    solver = cp_model.CpSolver()

    assert solver.Solve(constraint.model) in (cp_model.OPTIMAL, cp_model.FEASIBLE)
    assert solver.Value(work_day) == 1


def test_day_off_var_uses_separate_cache_and_is_complement_of_work_flag():
    constraint, staff = _make_work_day_constraint(days=2)
    work_day = constraint._get_work_day_var(staff, 1)
    day_off = constraint._get_dayoff_var(staff, 1)
    day_off_day_two = constraint._get_dayoff_var(staff, 2)

    assert day_off is not work_day
    assert constraint._get_dayoff_var(staff, 1) is day_off

    constraint.model.Add(constraint.shifts[(staff, 1)] == 1)
    constraint.model.Add(constraint.shifts[(staff, 2)] == 0)
    solver = cp_model.CpSolver()

    assert solver.Solve(constraint.model) in (cp_model.OPTIMAL, cp_model.FEASIBLE)
    assert solver.Value(day_off) == 0
    assert solver.Value(day_off_day_two) == 1


def test_consecutive_day_off_requires_previous_month_shift_at_month_start():
    constraint, staff = _make_work_day_constraint(days=1)
    constraint._get_hope_value = lambda staff, day, default=7: 7
    constraint._hope_matches = lambda value, values: value in values

    with pytest.raises(ValueError, match="前月シフト表が未指定"):
        constraint.add_consecutive_day_off_constraints()


def test_consecutive_day_off_accepts_previous_month_shift_at_month_start():
    constraint, staff = _make_work_day_constraint(days=3)
    constraint.eligible_sections = {staff: []}
    constraint._get_hope_value = lambda staff, day, default=7: 7
    constraint._hope_matches = lambda value, values: value in values
    constraint.optimizer.prev_month_shift = pd.DataFrame(
        {
            "Name": [staff],
            "-1": ["1"],
            "-2": ["1"],
            "-3": ["1"],
            "-4": ["1"],
        }
    )

    constraint.add_consecutive_day_off_constraints()
    solver = cp_model.CpSolver()

    assert solver.Solve(constraint.model) in (cp_model.OPTIMAL, cp_model.FEASIBLE)


def test_consecutive_day_off_window_is_exempt_when_oncall_precedes_window():
    constraint, staff = _make_work_day_constraint(days=5)
    constraint.eligible_sections = {staff: [4]}
    constraint._get_hope_value = lambda staff, day, default=7: 7
    constraint._hope_matches = lambda value, values: value in values
    constraint.optimizer.prev_month_shift = pd.DataFrame(
        {"Name": [staff], "-1": ["4"], "-2": ["4"], "-3": ["4"], "-4": ["4"]}
    )

    def had_oncall_yesterday(staff_name, day):
        oncall = constraint.model.NewBoolVar(f"oncall_before_{staff_name}_{day}")
        constraint.model.Add(oncall == (day == 2))
        return oncall

    constraint._get_had_oncall_yesterday_var = had_oncall_yesterday
    constraint.model.Add(constraint.shifts[(staff, 1)] == 1)
    for day in range(2, 6):
        constraint.model.Add(constraint.shifts[(staff, day)] == 0)

    constraint.add_consecutive_day_off_constraints()

    assert cp_model.CpSolver().Solve(constraint.model) in (
        cp_model.OPTIMAL,
        cp_model.FEASIBLE,
    )


def test_consecutive_day_off_month_boundary_window_skips_after_previous_month_oncall():
    constraint, staff = _make_work_day_constraint(days=1)
    constraint.eligible_sections = {staff: [4]}
    constraint._get_hope_value = lambda staff, day, default=7: 7
    constraint._hope_matches = lambda value, values: value in values
    constraint.optimizer.prev_month_shift = pd.DataFrame(
        {
            "Name": [staff],
            "-1": ["0"],
            "-2": ["0"],
            "-3": ["0"],
            "-4": ["◎"],
        }
    )
    constraint.model.Add(constraint.shifts[(staff, 1)] == 0)

    constraint.add_consecutive_day_off_constraints()

    assert cp_model.CpSolver().Solve(constraint.model) in (
        cp_model.OPTIMAL,
        cp_model.FEASIBLE,
    )


@pytest.mark.parametrize(("work_days", "recovery_days", "expected"), [
    ({1, 2, 3, 4, 5}, set(), cp_model.OPTIMAL),
    ({1, 2, 3, 4, 5, 6}, set(), cp_model.OPTIMAL),
    ({1, 2, 3, 4, 5, 6, 7}, set(), cp_model.INFEASIBLE),
    ({1, 2, 3, 4}, {5}, cp_model.OPTIMAL),
    ({1, 2, 3, 4, 5}, {6}, cp_model.OPTIMAL),
    ({1, 2, 3, 4, 5, 6}, {7}, cp_model.INFEASIBLE),
    ({1, 2, 3, 4, 5, 6}, {6}, cp_model.OPTIMAL),
    ({1, 2, 3, 4, 5, 6, 7}, {7}, cp_model.INFEASIBLE),
])
def test_consecutive_work_counts_work_and_recovery_once(work_days, recovery_days, expected):
    constraint, staff = _make_work_day_constraint(days=7)
    constraint.optimizer.prev_month_shift = pd.DataFrame({
        "Name": [staff],
        **{str(-day): ["0"] for day in range(1, 7)},
    })
    constraint._get_had_oncall_yesterday_var = lambda name, day: (
        constraint.model.NewConstant(int(day in recovery_days))
    )
    constraint.add_consecutive_work_constraints()
    for day in range(1, 8):
        constraint.model.Add(constraint.shifts[(staff, day)] == int(day in work_days))
    assert cp_model.CpSolver().Solve(constraint.model) == expected


def test_consecutive_work_requires_previous_month_shift_at_month_start():
    constraint, _ = _make_work_day_constraint(days=1)

    with pytest.raises(ValueError, match="前月シフト表が存在しません"):
        constraint.add_consecutive_work_constraints()


@pytest.mark.parametrize(("previous_value", "expected"), [
    ("", cp_model.INFEASIBLE),
    ("　", cp_model.INFEASIBLE),
    (None, cp_model.INFEASIBLE),
    ("指", cp_model.OPTIMAL),
    ("4", cp_model.INFEASIBLE),
    ("◎", cp_model.INFEASIBLE),
    ("○", cp_model.INFEASIBLE),
    ("研", cp_model.INFEASIBLE),
    ("AM夏", cp_model.INFEASIBLE),
    ("AM夏PM有", cp_model.OPTIMAL),
    ("AM指×", cp_model.INFEASIBLE),
    ("×指", cp_model.OPTIMAL),
])
def test_consecutive_work_month_boundary_counts_blank_as_work(previous_value, expected):
    constraint, staff = _make_work_day_constraint(days=1)
    constraint.optimizer.prev_month_shift = pd.DataFrame({
        "Name": [staff + "（◎のみ）"],
        **{str(-day): [previous_value] for day in range(1, 7)},
    })
    constraint.model.Add(constraint.shifts[(staff, 1)] == 1)
    constraint.add_consecutive_work_constraints()
    solver = cp_model.CpSolver()
    assert solver.Solve(constraint.model) == expected


def test_consecutive_work_allows_six_days_across_month_boundary():
    constraint, staff = _make_work_day_constraint(days=2)
    constraint.optimizer.prev_month_shift = pd.DataFrame({
        "Name": [staff], "-6": ["指"], "-5": ["指"],
        **{str(-day): [""] for day in range(1, 5)},
    })
    for day in (1, 2):
        constraint.model.Add(constraint.shifts[(staff, day)] == 1)
    constraint.add_consecutive_work_constraints()
    assert cp_model.CpSolver().Solve(constraint.model) == cp_model.OPTIMAL


def test_consecutive_work_counts_recovery_from_previous_month_oncall():
    constraint, staff = _make_work_day_constraint(days=1)
    constraint.optimizer.prev_month_shift = pd.DataFrame({
        "Name": [staff], "-1": ["◎"],
        **{str(-day): [""] for day in range(2, 7)},
    })
    constraint.prev_month_oncall_staff_ids = {staff}
    constraint.model.Add(constraint.shifts[(staff, 1)] == 0)
    constraint.add_consecutive_work_constraints()

    assert cp_model.CpSolver().Solve(constraint.model) == cp_model.INFEASIBLE


def test_consecutive_work_rejects_unrecognized_previous_month_mark():
    constraint, staff = _make_work_day_constraint(days=1)
    constraint.optimizer.prev_month_shift = pd.DataFrame({
        "Name": [staff], "-1": ["不明"],
        **{str(-day): ["指"] for day in range(2, 7)},
    })
    with pytest.raises(ValueError, match="勤務状態を判定できません"):
        constraint.add_consecutive_work_constraints()


def test_sunday_holiday_count_ignores_off_days_and_counts_each_day_once():
    constraint, staff = _make_work_day_constraint(days=2)
    penalties = constraint.add_sunday_holiday_work_constraints()
    constraint.model.Add(constraint.shifts[(staff, 1)] == 0)
    constraint.model.Add(constraint.shifts[(staff, 2)] == 1)
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
        self.shifts = {}
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

    assert BaseShiftOptimizer._get_days_in_month(optimizer) == 29


def test_get_days_in_month_non_leap_february():
    optimizer = ShiftOptimizer.__new__(ShiftOptimizer)
    optimizer.year = 2026
    optimizer.month = 2

    assert BaseShiftOptimizer._get_days_in_month(optimizer) == 28


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

    assert optimizer.get_primary_work_var("NameA", 1) is optimizer.shifts[("NameA", 1)]
    assert len(optimizer.shifts) == 4
    assert len(optimizer.night_shifts) == 2
    assert optimizer.get_oncall_pair("NameA", "NameB", 1) is optimizer.night_shifts[("NameA", "NameB", 1)]


def test_create_variables_handles_extended_december():
    optimizer = ShiftOptimizer.__new__(ShiftOptimizer)
    optimizer.model = cp_model.CpModel()
    optimizer.staff = pd.DataFrame(index=["NameA", "NameB"])
    optimizer.days, optimizer.year, optimizer.month = 34, 2026, 12
    optimizer.shifts = {}
    optimizer.night_shifts = {}
    optimizer.porifa_tuesday_vars = {}
    optimizer.porifa_friday_vars = {}

    optimizer.create_variables()

    assert ("NameA", 34) in optimizer.shifts
    assert ("NameA", "NameB", 34) in optimizer.night_shifts
    assert 32 in optimizer.porifa_friday_vars
    assert 33 not in optimizer.porifa_friday_vars


def test_get_primary_shift_reads_from_primary_shift_dictionary():
    optimizer = ShiftOptimizer.__new__(ShiftOptimizer)
    expected = object()
    optimizer.shifts = {("NameA", 3, 4): expected}

    assert BaseShiftOptimizer.get_primary_shift("NameA", 3, 4) is expected


def test_get_primary_work_status_returns_true_for_non_off_assignment():
    model = cp_model.CpModel()
    optimizer = ShiftOptimizer.__new__(ShiftOptimizer)
    optimizer.shifts = {("NameA", 3): model.NewBoolVar("work_NameA_3")}
    model.Add(optimizer.shifts[("NameA", 3)] == 1)
    solver = cp_model.CpSolver()
    assert solver.Solve(model) in (cp_model.OPTIMAL, cp_model.FEASIBLE)

    assert optimizer.get_primary_work_status(solver, "NameA", 3) is True


def test_get_primary_work_status_returns_false_for_off_assignment():
    model = cp_model.CpModel()
    optimizer = ShiftOptimizer.__new__(ShiftOptimizer)
    optimizer.shifts = {("NameA", 3): model.NewBoolVar("work_NameA_3")}
    model.Add(optimizer.shifts[("NameA", 3)] == 0)
    solver = cp_model.CpSolver()
    assert solver.Solve(model) in (cp_model.OPTIMAL, cp_model.FEASIBLE)

    assert optimizer.get_primary_work_status(solver, "NameA", 3) is False


def test_get_primary_work_status_returns_none_without_primary_variables():
    optimizer = ShiftOptimizer.__new__(ShiftOptimizer)
    optimizer.shifts = {}

    assert optimizer.get_primary_work_status(object(), "NameA", 3) is None


def _make_attendance_constraint(
    staff,
    eligible_sections,
    hopes,
    target,
    section_ids,
    weekday=0,
    is_holiday=False,
):
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
    constraint.year = 2026
    constraint.month = 10
    constraint.shifts = {}
    constraint.primary_sections = []
    constraint.eligible_sections = eligible_sections
    constraint._work_day_vars = {}
    constraint._day_off_vars = {}
    constraint._fixed_off_days = set()
    constraint._offrequest_excluded_days = set()
    constraint._get_daily_attendance_target = lambda day: target
    constraint._attendance_section_ids = lambda day: section_ids
    constraint._get_weekday = lambda day: weekday
    constraint._is_holiday = lambda day: is_holiday
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
    constraint.add_consecutive_work_constraints = lambda: []
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


def test_oncall_work_candidate_overlap_reports_common_pairs_by_day(capsys):
    constraint = WorkConstraints.__new__(WorkConstraints)
    constraint.days = 2
    constraint._fixed_off_days = {
        ("Staff A", 1),
        ("Staff B", 1),
        ("Staff C", 1),
        ("Staff B", 2),
    }
    constraint.optimizer = SimpleNamespace(
        oncall_constraints=SimpleNamespace(
            _get_hard_compatible_oncall_pairs=lambda: (
                [],
                {},
                {
                    1: [("Staff A", "Staff B"), ("Staff A", "Staff C")],
                    2: [("Staff A", "Staff C"), ("Staff B", "Staff D")],
                },
            )
        )
    )

    diagnostics = constraint.log_oncall_work_candidate_overlap()
    output = capsys.readouterr().out

    assert diagnostics[1] == {
        "oncall_candidate_pairs": 2,
        "work_compatible_pairs": 0,
        "blocked_by_work_constraints": 2,
    }
    assert diagnostics[2] == {
        "oncall_candidate_pairs": 2,
        "work_compatible_pairs": 1,
        "blocked_by_work_constraints": 1,
    }
    assert "[当直・出勤共通候補なし] day=1" in output
    assert "[当直・出勤共通候補なし] day=2" not in output


def test_oncall_request_forces_work_without_making_staff_attendance_candidate():
    staff = pd.DataFrame(
        {"休職": [False], "日曜出勤": [False]},
        index=["OncallRequester"],
    )
    constraint, work_vars, objective_terms = _make_attendance_constraint(
        staff=staff,
        eligible_sections={"OncallRequester": []},
        hopes={"OncallRequester": 8},
        target=0,
        section_ids={1},
        weekday=6,
    )
    constraint.add_consecutive_work_constraints = lambda: []

    constraint.apply_attendance_constraints()
    constraint.model.Minimize(sum(term for _, term in objective_terms))
    solver = cp_model.CpSolver()

    assert solver.Solve(constraint.model) in (cp_model.OPTIMAL, cp_model.FEASIBLE)
    assert solver.Value(work_vars[("OncallRequester", 1)]) == 1
    assert solver.Value(objective_terms[0][1]) == 0


@pytest.mark.parametrize("hope_value", [9, 10])
@pytest.mark.parametrize(("weekday", "is_holiday"), [(6, False), (0, True)])
def test_am_pm_work_request_allows_sunday_or_holiday_attendance(
    hope_value, weekday, is_holiday
):
    staff = pd.DataFrame(
        {"休職": [False, False], "日曜出勤": [False, False]},
        index=["WorkRequester", "OtherHalfDay"],
    )
    constraint, work_vars, objective_terms = _make_attendance_constraint(
        staff=staff,
        eligible_sections={"WorkRequester": [4], "OtherHalfDay": [4]},
        hopes={"WorkRequester": hope_value, "OtherHalfDay": hope_value},
        target=1,
        section_ids={4},
        weekday=weekday,
        is_holiday=is_holiday,
    )
    constraint.add_consecutive_work_constraints = lambda: []

    constraint.apply_attendance_constraints()
    constraint.model.Minimize(sum(term for _, term in objective_terms))
    solver = cp_model.CpSolver()

    assert solver.Solve(constraint.model) in (cp_model.OPTIMAL, cp_model.FEASIBLE)
    assert solver.Value(work_vars[("WorkRequester", 1)]) == 1
    assert ("WorkRequester", 1) not in constraint._fixed_off_days
    assert ("WorkRequester", 1) not in constraint._offrequest_excluded_days


def test_daily_attendance_target_uses_section_and_dispensing_requirements():
    constraint = WorkConstraints.__new__(WorkConstraints)
    constraint.staff = pd.DataFrame(index=[])
    constraint.year = 2026
    constraint.month = 10
    constraint.days = 31
    constraint._is_holiday = lambda day: False
    constraint._is_prev_day_holiday = lambda day: False
    constraint._get_section_min_requirements = lambda **kwargs: {
        "3F": 4,
        "4F": 5,
    }

    assert constraint._get_daily_attendance_target(1) == 16
    assert constraint._get_daily_attendance_target(4) == 4


@pytest.mark.parametrize(("day", "expected"), [(1, 20), (2, 20), (3, 16), (9, 19)])
def test_daily_attendance_target_excludes_overlapping_roles(day, expected):
    constraint = WorkConstraints.__new__(WorkConstraints)
    constraint.year, constraint.month, constraint.days = 2026, 10, 31
    constraint.staff = pd.DataFrame(index=["A", "B", "C"])
    constraint._is_holiday = lambda day: False
    constraint._is_prev_day_holiday = lambda day: False
    constraint._get_section_min_requirements = lambda **kwargs: {
        "3F": 4,
        "4F": 5,
        "入退院センター": 1,
        "化療": 2 if kwargs["weekday"] == 5 else 4,
    }

    assert constraint._get_daily_attendance_target(day) == expected


@pytest.mark.parametrize(("hopes", "expected_penalty"), [
    ({"A": 9, "B": 10}, 0),
    ({"A": 9, "B": 0}, 5000),
    ({"A": 1, "B": 10}, 5000),
])
def test_weekday_attendance_half_days_count_as_half(hopes, expected_penalty):
    staff = pd.DataFrame(
        {"休職": [False, False], "日曜出勤": [True, True]},
        index=["A", "B"],
    )
    constraint, _, terms = _make_attendance_constraint(
        staff=staff, eligible_sections={"A": [4], "B": [4]},
        hopes=hopes, target=1, section_ids={4},
    )
    constraint.apply_attendance_constraints()
    constraint.model.Minimize(sum(term for _, term in terms))
    solver = cp_model.CpSolver()
    assert solver.Solve(constraint.model) == cp_model.OPTIMAL
    assert solver.ObjectiveValue() == expected_penalty


@pytest.mark.parametrize("training_hope", [6, 11])
def test_attendance_forces_leave_and_training_status_without_counting_training(training_hope):
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
        hopes={"OffHope": 0, "Training": training_hope},
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


@pytest.mark.parametrize(
    ("weekday", "is_holiday", "excluded_from_offrequest"),
    [
        (0, False, True),
        (6, False, False),
        (0, True, False),
    ],
)
def test_offrequest_excludes_unavailable_workdays_but_counts_sunday_and_holiday(
    weekday, is_holiday, excluded_from_offrequest
):
    staff = pd.DataFrame(
        {"休職": [False], "日曜出勤": [False]},
        index=["Unavailable"],
    )
    constraint, work_vars, objective_terms = _make_attendance_constraint(
        staff=staff,
        eligible_sections={"Unavailable": []},
        hopes={},
        target=1,
        section_ids={4},
        weekday=weekday,
        is_holiday=is_holiday,
    )
    constraint.add_consecutive_work_constraints = lambda: []

    constraint.apply_attendance_constraints()
    counted_off = constraint._non_attendance("Unavailable", 1)

    assert ("Unavailable", 1) in constraint._fixed_off_days
    assert (
        ("Unavailable", 1) in constraint._offrequest_excluded_days
    ) is excluded_from_offrequest
    if excluded_from_offrequest:
        assert counted_off is None
        return

    assert counted_off is not None
    constraint.model.Minimize(sum(term for _, term in objective_terms))
    solver = cp_model.CpSolver()
    assert solver.Solve(constraint.model) in (cp_model.OPTIMAL, cp_model.FEASIBLE)
    assert solver.Value(work_vars[("Unavailable", 1)]) == 0
    assert solver.Value(counted_off) == 1


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
    optimizer.shifts[("Name1", 1)] = model.NewBoolVar("work_Name1_1")
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


def test_consecutive_day_off_skips_window_of_fixed_off_days():
    constraint, staff = _make_work_day_constraint(days=4)
    constraint.eligible_sections = {staff: [4]}
    constraint._get_hope_value = lambda staff, day, default=7: 7
    constraint._hope_matches = lambda value, values: value in values
    constraint._fixed_off_days = {(staff, day) for day in range(1, 5)}
    constraint.optimizer.prev_month_shift = pd.DataFrame(
        {"Name": [staff], "-1": ["4"], "-2": ["4"], "-3": ["4"], "-4": ["4"]}
    )
    for day in range(1, 5):
        constraint.model.Add(constraint.shifts[(staff, day)] == 0)

    constraint.add_consecutive_day_off_constraints()
    solver = cp_model.CpSolver()

    assert solver.Solve(constraint.model) in (cp_model.OPTIMAL, cp_model.FEASIBLE)


def test_consecutive_day_off_counts_previous_month_off_only():
    constraint, staff = _make_work_day_constraint(days=1)
    constraint.eligible_sections = {staff: [4]}
    constraint._get_hope_value = lambda staff, day, default=7: 7
    constraint._hope_matches = lambda value, values: value in values
    constraint.optimizer.prev_month_shift = pd.DataFrame(
        {"Name": [staff], "-1": ["0"], "-2": ["0"], "-3": ["0"], "-4": ["4"]}
    )
    constraint.add_consecutive_day_off_constraints()
    constraint.model.Add(constraint.shifts[(staff, 1)] == 0)

    assert cp_model.CpSolver().Solve(constraint.model) == cp_model.INFEASIBLE
