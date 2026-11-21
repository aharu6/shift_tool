"""#174 日曜・祝日の出勤（当直含む）均一化のテスト。

方針（2026-11-21 転換）:
- 出勤と当直のどちらかがある日を1回と数える
- 本人が出勤希望（出・AM出・PM出）を出した日は数えない
- 年末（12/30）も対象日に含まれる
- 外来スタッフ（担当業務16）は対象外
- ソフト制約：まだ k-1 回入っていない人が残っている状態で誰かが k 回目に
  入ると、残っている人数分のペナルティ。全員が使用済みならペナルティなし
  （ハード方式は12月の実データで解なしになったため採らない）
- 数える対象日が月内に1日もないスタッフ（希望で全て塞がっている等）は
  均一化の対象に含めない
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


def _solve(constraint):
    solver = cp_model.CpSolver()
    return solver.Solve(constraint.model)


def _solve_min_penalty(constraint, penalties):
    constraint.model.Minimize(sum(penalties))
    solver = cp_model.CpSolver()
    status = solver.Solve(constraint.model)
    return solver, status


def test_second_duty_penalized_while_someone_is_unused():
    # B が0回のうちに A が2回目に入ると、未使用1人分のペナルティが付く
    constraint, shifts, _ = _make_constraint(
        {"A": [4], "B": [4]},
        sundays={6, 13, 20},
    )
    penalties = constraint.add_sunday_holiday_work_constraints()
    constraint.model.Add(shifts[("A", 6)] == 1)
    constraint.model.Add(shifts[("A", 13)] == 1)
    # B は全日0（年末の対象日も含めて1回も入らない）
    for day in range(1, 32):
        constraint.model.Add(shifts[("B", day)] == 0)

    solver, status = _solve_min_penalty(constraint, penalties)
    assert status == cp_model.OPTIMAL
    assert solver.Value(sum(penalties)) == 1


def test_second_duty_free_once_everyone_is_used():
    # 全員が1回入れば、2回目はペナルティなしで認める
    constraint, shifts, _ = _make_constraint(
        {"A": [4], "B": [4]},
        sundays={6, 13, 20},
    )
    penalties = constraint.add_sunday_holiday_work_constraints()
    constraint.model.Add(shifts[("A", 6)] == 1)
    constraint.model.Add(shifts[("B", 6)] == 1)
    constraint.model.Add(shifts[("A", 13)] == 1)

    solver, status = _solve_min_penalty(constraint, penalties)
    assert status == cp_model.OPTIMAL
    assert solver.Value(sum(penalties)) == 0


def test_third_duty_penalized_until_everyone_is_at_two():
    # B が1回のうちに A が3回目に入るとペナルティが付く
    # （2回目の分は B も1回入っているので付かない）
    constraint, shifts, _ = _make_constraint(
        {"A": [4], "B": [4]},
        sundays={6, 13, 20, 27},
    )
    penalties = constraint.add_sunday_holiday_work_constraints()
    for day in (6, 13, 20):
        constraint.model.Add(shifts[("A", day)] == 1)
    constraint.model.Add(shifts[("B", 6)] == 1)
    for day in range(1, 32):
        if day != 6:
            constraint.model.Add(shifts[("B", day)] == 0)

    solver, status = _solve_min_penalty(constraint, penalties)
    assert status == cp_model.OPTIMAL
    assert solver.Value(sum(penalties)) == 1


def test_oncall_days_count_toward_the_level():
    # 当直だけの日も1回と数える。B が0回のうちに A が当直で2回目に入ると
    # ペナルティが付く
    constraint, shifts, pair_vars = _make_constraint(
        {"A": [4], "B": [4], "C": [4]},
        sundays={6, 13},
        oncall_pair_keys={("A", "C", 6), ("A", "C", 13)},
    )
    penalties = constraint.add_sunday_holiday_work_constraints()
    constraint.model.Add(pair_vars[("A", "C", 6)] == 1)
    constraint.model.Add(pair_vars[("A", "C", 13)] == 1)
    # B は全日0（年末の対象日も含めて1回も入らない）
    for day in range(1, 32):
        constraint.model.Add(shifts[("B", day)] == 0)

    solver, status = _solve_min_penalty(constraint, penalties)
    assert status == cp_model.OPTIMAL
    assert solver.Value(sum(penalties)) >= 1


def test_hoped_work_days_are_not_counted():
    # 出勤希望（出=1）を出した日は数えないので、3日出勤しても制限に触れない
    staff = "Name1"
    constraint, shifts, _ = _make_constraint(
        {staff: [4], "B": [4]},
        sundays={6, 13, 20},
        hopes={(staff, 6): 1, (staff, 13): 1, (staff, 20): 1},
    )
    constraint.add_sunday_holiday_work_constraints()
    for day in (6, 13, 20):
        constraint.model.Add(shifts[(staff, day)] == 1)

    assert _solve(constraint) in (cp_model.OPTIMAL, cp_model.FEASIBLE)


def test_december_30_counts_as_target_day():
    # 12/30は日曜でも祝日でもないが、年末として対象日に含まれる
    # （日曜2回＋12/30で A が3回、B が0回なら2回目・3回目の両方に付く）
    constraint, shifts, _ = _make_constraint(
        {"A": [4], "B": [4]},
        month=12,
        sundays={6, 13},
    )
    penalties = constraint.add_sunday_holiday_work_constraints()
    constraint.model.Add(shifts[("A", 6)] == 1)
    constraint.model.Add(shifts[("A", 13)] == 1)
    constraint.model.Add(shifts[("A", 30)] == 1)
    for day in range(1, 32):
        constraint.model.Add(shifts[("B", day)] == 0)

    solver, status = _solve_min_penalty(constraint, penalties)
    assert status == cp_model.OPTIMAL
    assert solver.Value(sum(penalties)) == 2


def test_outpatient_staff_is_excluded():
    # 外来スタッフは対象外なので、何回入っても制限に触れない
    outpatient = "Outpatient1"
    staff = "Name1"
    constraint, shifts, _ = _make_constraint(
        {staff: [4], outpatient: [16]},
        sundays={6, 13, 20},
    )
    penalties = constraint.add_sunday_holiday_work_constraints()
    for day in (6, 13, 20):
        constraint.model.Add(shifts[(outpatient, day)] == 1)

    assert _solve(constraint) in (cp_model.OPTIMAL, cp_model.FEASIBLE)


def test_report_lists_over_and_zero_staff(tmp_path):
    # 解の値から数え直して、2回以上の人と0回の人をレポートに出す
    constraint, shifts, _ = _make_constraint(
        {"A": [4], "B": [4]},
        sundays={6, 13, 20},
    )
    constraint.add_sunday_holiday_work_constraints()
    constraint.model.Add(shifts[("A", 6)] == 1)
    constraint.model.Add(shifts[("A", 13)] == 1)
    for day in range(1, 32):
        if day not in (6, 13):
            constraint.model.Add(shifts[("A", day)] == 0)
        constraint.model.Add(shifts[("B", day)] == 0)
    solver = cp_model.CpSolver()
    assert solver.Solve(constraint.model) in (cp_model.OPTIMAL, cp_model.FEASIBLE)

    path = constraint.write_sunday_holiday_report(
        solver, tmp_path / "report.txt"
    )
    text = path.read_text(encoding="utf-8")
    assert "A: 2回" in text
    assert "6日（出勤）" in text
    assert "B（1名）" in text
    assert "全員分一致しました" in text


def test_december_count_does_not_cross_into_january(tmp_path):
    # 12月作成時は作成期間が翌1月3日（34日目）まで含まれるが、
    # 回数を数えるのは12月の中だけ。1月2日（33日目）の出勤は数えない
    constraint, shifts, _ = _make_constraint(
        {"A": [4], "B": [4]},
        days=34,
        sundays={6, 13, 20, 27},
    )
    target_days, _ = constraint._sunday_holiday_population()
    assert 31 in target_days
    assert 33 not in target_days
    assert max(target_days) <= 31

    constraint.add_sunday_holiday_work_constraints()
    constraint.model.Add(shifts[("A", 33)] == 1)
    constraint.model.Add(shifts[("B", 6)] == 1)
    constraint.model.Add(shifts[("B", 13)] == 1)
    for day in range(1, 35):
        if day != 33:
            constraint.model.Add(shifts[("A", day)] == 0)
        if day not in (6, 13):
            constraint.model.Add(shifts[("B", day)] == 0)
    solver = cp_model.CpSolver()
    assert solver.Solve(constraint.model) in (cp_model.OPTIMAL, cp_model.FEASIBLE)

    path = constraint.write_sunday_holiday_report(
        solver, tmp_path / "report.txt"
    )
    text = path.read_text(encoding="utf-8")
    assert "B: 2回" in text
    assert "A（1名）" in text


def test_staff_without_countable_days_does_not_block():
    # B は全ての日曜に終日休み希望があり数える対象日がないため、
    # 均一化の対象に含めず、A の2回目にもペナルティは付かない
    constraint, shifts, _ = _make_constraint(
        {"A": [4], "B": [4]},
        sundays={6, 13, 20},
        hopes={("B", 6): 4, ("B", 13): 4, ("B", 20): 4},
    )
    penalties = constraint.add_sunday_holiday_work_constraints()
    constraint.model.Add(shifts[("A", 6)] == 1)
    constraint.model.Add(shifts[("A", 13)] == 1)

    solver, status = _solve_min_penalty(constraint, penalties)
    assert status == cp_model.OPTIMAL
    assert solver.Value(sum(penalties)) == 0
