"""
#203: 当日の必要業務の候補者でないスタッフの出勤扱いのテスト。

課長・部長・RIなど「当日の必要人数の対象にはならない業務」だけを
持つスタッフは、従来は平日でも候補者になれず全日休みに固定され、
しかも指定休の集計から除外されていたため、指定休の上限が効かずに
毎日「指」になっていた。

修正後の期待動作（平日）:
- 一律で休みに固定しない（ソルバーが出勤/休みを選べる）
- 出勤人数（period_candidates）のカウントには含めない
- 指定休の集計から除外しない（上限が効く）
- 休み希望・出勤希望・学会/研修希望は従来どおり反映される
- 日曜・祝日は従来どおり（日曜出勤FALSEなら休み）
- 共通セクション（休み・明け・研修・学会）しか持たないスタッフは
  従来どおり休みに固定される
"""

import datetime
from types import SimpleNamespace

import jpholiday
import pandas as pd
from ortools.sat.python import cp_model

from optimizer.mode1.constraint_diagnostics import TrackedCpModel
from optimizer.mode1.primary_shift.work_constraints import WorkConstraints


# 課長のように「必要業務ではない所属業務（25）」だけを持つスタッフ
DUTY_ELIGIBLE = [25, 0, 17, 28, 29]
# 共通セクションしか持たないスタッフ
UNIVERSAL_ELIGIBLE = [0, 17, 28, 29]
# 調剤室（当日の必要業務に含まれる）を持つスタッフ
DISPENSING_ELIGIBLE = [1, 0, 17, 28, 29]


def _constraint(year, month, staff_eligible, hopes, sunday_work):
    """1日分だけ apply_attendance_constraints を適用できる制約スタブ。

    当日の必要業務は調剤室（1）のみとし、出勤目標人数は0に固定する
    （候補者判定そのものの検証に絞るため）。
    """
    constraint = WorkConstraints.__new__(WorkConstraints)
    constraint.year = year
    constraint.month = month
    constraint.holiday_dates = {
        date for date, _ in jpholiday.month_holidays(year, month)
    }
    constraint.model = TrackedCpModel()
    constraint.days = 1
    names = list(staff_eligible)
    constraint.staff = pd.DataFrame(
        {
            "休職": {name: False for name in names},
            "日曜出勤": {name: sunday_work.get(name, False) for name in names},
        }
    )
    constraint.eligible_sections = dict(staff_eligible)
    constraint.get_eligible_sections = constraint.eligible_sections
    constraint.hope_list = pd.DataFrame({1: hopes})
    constraint.hope_day_column_map = {1: 1}
    constraint.debug_enabled = False
    constraint._fixed_off_days = set()
    constraint._offrequest_excluded_days = set()
    constraint.prev_month_oncall_staff_ids = set()
    work = {
        name: constraint.model.NewBoolVar(f"work_{name}") for name in names
    }
    constraint.optimizer = SimpleNamespace(
        get_primary_work_var=lambda name, day: work[name],
        register_objective_term=lambda name, term: None,
    )
    constraint._is_year_end_or_new_year = lambda **kwargs: None
    constraint._get_had_oncall_yesterday_var = (
        lambda name, day: constraint.model.NewConstant(0)
    )
    constraint._get_daily_attendance_target = lambda day: 0
    constraint._attendance_section_ids = lambda day: {1}
    constraint.add_sunday_holiday_work_constraints = lambda: []
    constraint.add_consecutive_work_constraints = lambda: []
    return constraint, work


def _solve(model):
    return cp_model.CpSolver().Solve(model)


def test_duty_section_staff_is_not_forced_off_on_weekday():
    """平日: 所属業務を持つ候補外スタッフは休みに固定されない。"""
    # 2026-12-01 は火曜日
    assert datetime.date(2026, 12, 1).weekday() == 1
    constraint, work = _constraint(
        2026, 12, {"K": DUTY_ELIGIBLE}, {"K": 7}, {}
    )
    constraint.apply_attendance_constraints()

    # 出勤人数のカウントには含めない
    _, candidates, _ = constraint.period_candidates[1]
    assert "K" not in candidates
    # 指定休の集計から除外しない・固定休みにもしない
    assert ("K", 1) not in constraint._offrequest_excluded_days
    assert ("K", 1) not in constraint._fixed_off_days
    # 出勤を選べる（休みに固定されていない）
    constraint.model.Add(work["K"] == 1)
    assert _solve(constraint.model) == cp_model.OPTIMAL


def test_duty_section_staff_reflects_off_hope():
    """平日: 休み希望（0）があれば従来どおり休みになる。"""
    constraint, work = _constraint(
        2026, 12, {"K": DUTY_ELIGIBLE}, {"K": 0}, {}
    )
    constraint.apply_attendance_constraints()
    solver = cp_model.CpSolver()
    assert solver.Solve(constraint.model) == cp_model.OPTIMAL
    assert solver.Value(work["K"]) == 0


def test_duty_section_staff_reflects_work_hope():
    """平日: 出勤希望（1）があれば出勤に固定される。"""
    constraint, work = _constraint(
        2026, 12, {"K": DUTY_ELIGIBLE}, {"K": 1}, {}
    )
    constraint.apply_attendance_constraints()
    constraint.model.Add(work["K"] == 0)
    assert _solve(constraint.model) == cp_model.INFEASIBLE


def test_duty_section_staff_reflects_gakkai_hope():
    """平日: 学会希望（11）があれば出勤に固定される。"""
    constraint, work = _constraint(
        2026, 12, {"K": DUTY_ELIGIBLE}, {"K": 11}, {}
    )
    constraint.apply_attendance_constraints()
    constraint.model.Add(work["K"] == 0)
    assert _solve(constraint.model) == cp_model.INFEASIBLE


def test_duty_section_staff_reflects_training_hope():
    """平日: 研修希望（6）があれば出勤に固定される。"""
    constraint, work = _constraint(
        2026, 12, {"K": DUTY_ELIGIBLE}, {"K": 6}, {}
    )
    constraint.apply_attendance_constraints()
    constraint.model.Add(work["K"] == 0)
    assert _solve(constraint.model) == cp_model.INFEASIBLE


def test_universal_only_staff_is_still_forced_off_on_weekday():
    """平日: 共通セクションしか持たないスタッフは従来どおり休み固定。"""
    constraint, work = _constraint(
        2026, 12, {"U": UNIVERSAL_ELIGIBLE}, {"U": 7}, {}
    )
    constraint.apply_attendance_constraints()
    assert ("U", 1) in constraint._offrequest_excluded_days
    assert ("U", 1) in constraint._fixed_off_days
    constraint.model.Add(work["U"] == 1)
    assert _solve(constraint.model) == cp_model.INFEASIBLE


def test_duty_section_staff_is_forced_off_on_sunday():
    """日曜: 日曜出勤FALSEの所属業務スタッフは従来どおり休み。"""
    # 2026-11-01 は日曜日
    assert datetime.date(2026, 11, 1).weekday() == 6
    constraint, work = _constraint(
        2026, 11, {"K": DUTY_ELIGIBLE}, {"K": 7}, {"K": False}
    )
    constraint.apply_attendance_constraints()
    constraint.model.Add(work["K"] == 1)
    assert _solve(constraint.model) == cp_model.INFEASIBLE


def test_dispensing_candidate_is_unchanged():
    """調剤室を持つ通常スタッフは従来どおり候補者になる。"""
    constraint, work = _constraint(
        2026, 12, {"D": DISPENSING_ELIGIBLE}, {"D": 7}, {}
    )
    constraint.apply_attendance_constraints()
    _, candidates, _ = constraint.period_candidates[1]
    assert "D" in candidates
    assert ("D", 1) not in constraint._offrequest_excluded_days


def test_offrequest_cap_applies_to_duty_section_staff():
    """指定休の上限（0日）が、所属業務スタッフにも効くことを確認する。

    出勤制約の後に指定休制約まで通して適用し、上限0日なら
    候補外だった平日も出勤せざるを得ないことを検証する。
    共通セクションのみのスタッフは集計対象外のまま（制約なし）。
    """
    constraint, work = _constraint(
        2026,
        12,
        {"K": DUTY_ELIGIBLE, "U": UNIVERSAL_ELIGIBLE},
        {"K": 7, "U": 7},
        {},
    )
    constraint.offrequest_day = 0
    off_vars = {}
    for name in ("K", "U"):
        off_var = constraint.model.NewBoolVar(f"off_{name}")
        constraint.model.Add(off_var + work[name] == 1)
        off_vars[name] = off_var
    constraint._get_dayoff_var = lambda staff, day: off_vars[staff]
    constraint.apply_attendance_constraints()
    constraint.apply_offrequest_constraints()

    solver = cp_model.CpSolver()
    assert solver.Solve(constraint.model) == cp_model.OPTIMAL
    # 上限0日なので K は出勤するしかない
    assert solver.Value(work["K"]) == 1
    # U は従来どおり休み固定
    assert solver.Value(work["U"]) == 0
