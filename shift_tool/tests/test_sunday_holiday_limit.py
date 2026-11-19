"""#174 日曜・祝日の出勤（当直含む）月1回原則のテスト。

- 出勤と当直のどちらかがある日を1回と数える
- 本人が出勤希望（出・AM出・PM出）を出した日は数えない
- ハード上限は2回、2回目がペナルティになる
- 年末（12/30）も対象日に含まれる
- 外来スタッフ（担当業務16）は対象外
"""
from types import SimpleNamespace

import pandas as pd
import pytest
from ortools.sat.python import cp_model

from optimizer.method.baseshiftoptimizer import BaseShiftOptimizer
from optimizer.mode1.primary_shift.work_constraints import WorkConstraints


def _make_constraint(
    staff_sections,
    days=31,
    year=2026,
    month=12,
    sundays=(),
    holidays=(),
    hopes=None,
    oncall_pair_keys=(),
):
    """WorkConstraints のスタブを作る。

    staff_sections: {スタッフ名: [担当業務ID]}
    hopes: {(スタッフ名, 日): 希望値}
    oncall_pair_keys: 当直ペア変数を用意する (スタッフ1, スタッフ2, 日) の集合
    """
    model = cp_model.CpModel()
    staff_names = list(staff_sections)
    shifts = {
        (staff, day): model.NewBoolVar(f"shift_{staff}_{day}")
        for staff in staff_names
        for day in range(1, days + 1)
    }
    pair_vars = {
        key: model.NewBoolVar(f"oncall_pair_{key[0]}_{key[1]}_{key[2]}")
        for key in oncall_pair_keys
    }

    constraint = WorkConstraints.__new__(WorkConstraints)
    constraint.model = model
    constraint.staff = pd.DataFrame(index=staff_names)
    constraint.days = days
    constraint.primary_sections = [0, 4, 17, 28, 29]
    constraint.eligible_sections = staff_sections
    constraint.get_eligible_sections = staff_sections
    constraint.shifts = shifts
    constraint.year, constraint.month = year, month
    constraint.holiday_dates = set()
    hope_list = pd.DataFrame(7, index=staff_names, columns=range(1, days + 1))
    for (staff, day), value in (hopes or {}).items():
        hope_list.loc[staff, day] = value
    constraint.hope_list = hope_list
    constraint.hope_day_column_map = {day: day for day in range(1, days + 1)}
    constraint.debug_enabled = False
    constraint._work_day_vars = {}
    constraint._oncall_day_vars = {}
    constraint._day_off_vars = {}
    constraint._had_oncall_yesterday_vars = {}
    constraint.prev_month_oncall_staff_ids = set()
    constraint.optimizer = SimpleNamespace(
        prev_month_shift=None,
        prev_month_oncall_staff_ids=set(),
        get_primary_work_var=lambda staff_name, day: shifts.get((staff_name, day)),
        get_oncall_pair=lambda s1, s2, day: pair_vars.get((s1, s2, day)),
        _normalize_attendance_mark=BaseShiftOptimizer._normalize_attendance_mark,
    )
    constraint._get_weekday = lambda day: 6 if day in sundays else 0
    constraint._is_holiday = lambda day: day in holidays
    return constraint, shifts, pair_vars


def _solve_min_penalty(constraint, penalties):
    constraint.model.Minimize(sum(penalties))
    solver = cp_model.CpSolver()
    status = solver.Solve(constraint.model)
    return solver, status


def test_oncall_days_count_toward_the_limit():
    # 日曜が3日あり、うち2日は当直（出勤なし）でも、3回目で上限2回に触れる
    staff = "Name1"
    partner = "Name2"
    constraint, shifts, pair_vars = _make_constraint(
        {staff: [4], partner: [4]},
        sundays={6, 13, 20},
        oncall_pair_keys={(staff, partner, 6), (staff, partner, 13)},
    )
    penalties = constraint.add_sunday_holiday_work_constraints()
    constraint.model.Add(pair_vars[(staff, partner, 6)] == 1)
    constraint.model.Add(pair_vars[(staff, partner, 13)] == 1)
    constraint.model.Add(shifts[(staff, 20)] == 1)

    solver = cp_model.CpSolver()
    assert solver.Solve(constraint.model) == cp_model.INFEASIBLE


def test_second_duty_is_allowed_but_penalized():
    staff = "Name1"
    constraint, shifts, _ = _make_constraint(
        {staff: [4]},
        sundays={6, 13, 20},
    )
    penalties = constraint.add_sunday_holiday_work_constraints()
    constraint.model.Add(shifts[(staff, 6)] == 1)
    constraint.model.Add(shifts[(staff, 13)] == 1)
    constraint.model.Add(shifts[(staff, 20)] == 0)

    solver, status = _solve_min_penalty(constraint, penalties)
    assert status == cp_model.OPTIMAL
    assert solver.Value(penalties[0]) == 1


def test_first_duty_has_no_penalty():
    staff = "Name1"
    constraint, shifts, _ = _make_constraint(
        {staff: [4]},
        sundays={6, 13},
    )
    penalties = constraint.add_sunday_holiday_work_constraints()
    constraint.model.Add(shifts[(staff, 6)] == 1)
    constraint.model.Add(shifts[(staff, 13)] == 0)

    solver, status = _solve_min_penalty(constraint, penalties)
    assert status == cp_model.OPTIMAL
    assert solver.Value(penalties[0]) == 0


def test_hoped_work_days_are_not_counted():
    # 出勤希望（出=1）を出した日曜は3日出勤しても数えない
    staff = "Name1"
    constraint, shifts, _ = _make_constraint(
        {staff: [4]},
        sundays={6, 13, 20},
        hopes={(staff, 6): 1, (staff, 13): 1, (staff, 20): 1},
    )
    penalties = constraint.add_sunday_holiday_work_constraints()
    for day in (6, 13, 20):
        constraint.model.Add(shifts[(staff, day)] == 1)

    solver, status = _solve_min_penalty(constraint, penalties)
    assert status == cp_model.OPTIMAL
    assert solver.Value(penalties[0]) == 0


def test_december_30_counts_as_target_day():
    # 12/30は日曜でも祝日でもないが、年末として対象日に含まれる
    staff = "Name1"
    constraint, shifts, _ = _make_constraint(
        {staff: [4]},
        month=12,
        sundays={6, 13},
    )
    penalties = constraint.add_sunday_holiday_work_constraints()
    constraint.model.Add(shifts[(staff, 6)] == 1)
    constraint.model.Add(shifts[(staff, 13)] == 1)
    constraint.model.Add(shifts[(staff, 30)] == 1)

    solver = cp_model.CpSolver()
    assert solver.Solve(constraint.model) == cp_model.INFEASIBLE


def test_outpatient_staff_is_excluded():
    outpatient = "Outpatient1"
    staff = "Name1"
    constraint, shifts, _ = _make_constraint(
        {staff: [4], outpatient: [16]},
        sundays={6, 13, 20},
    )
    penalties = constraint.add_sunday_holiday_work_constraints()
    # 外来スタッフはペナルティ対象外（1人分だけ返る）
    assert len(penalties) == 1
    for day in (6, 13, 20):
        constraint.model.Add(shifts[(outpatient, day)] == 1)

    solver = cp_model.CpSolver()
    assert solver.Solve(constraint.model) in (cp_model.OPTIMAL, cp_model.FEASIBLE)
