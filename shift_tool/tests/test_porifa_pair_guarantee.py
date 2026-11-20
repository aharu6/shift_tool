"""#177 ポリファーマシー候補ペア保証（mode1ソフト制約）のテスト。

- mode2 が実施日を選べるよう、金曜＋翌火曜の両日ともチーム全員が
  出勤するペアを少なくとも1つ確保することにボーナスを付ける
- 希望で全ペアが塞がっている月は制約を入れない
- 確保できない場合でも解なしにはならない（ソフト制約）
"""
import datetime
from types import SimpleNamespace

import pandas as pd
from ortools.sat.python import cp_model

from optimizer.method.half_day import parse_half_day
from optimizer.mode1.primary_shift.work_constraints import WorkConstraints

MEMBERS = ["A", "B", "C"]
# 2026年12月の金曜は 4, 11, 18, 25。ペアは (金曜, 金曜+4)
PAIRS = [(4, 8), (11, 15), (18, 22), (25, 29)]


def _make_constraint(hopes=None, raw_hopes=None, holidays=(), team=None):
    """WorkConstraints のスタブを作る。

    hopes: {(スタッフ名, 日): 希望コード}
    raw_hopes: {(スタッフ名, 日): 半日希望の文字列}（get_half_day_hope 用）
    team: {スタッフ名: ポリファーマシーチーム所属か}
    """
    days = 31
    names = MEMBERS + ["D"]
    team = team or {name: name in MEMBERS for name in names}
    model = cp_model.CpModel()
    shifts = {
        (staff, day): model.NewBoolVar(f"shift_{staff}_{day}")
        for staff in names
        for day in range(1, days + 1)
    }
    hope_list = pd.DataFrame(7, index=names, columns=range(1, days + 1))
    for (staff, day), value in (hopes or {}).items():
        hope_list.loc[staff, day] = value
    terms = {}
    constraint = WorkConstraints.__new__(WorkConstraints)
    constraint.model = model
    constraint.staff = pd.DataFrame(
        {"ポリファーマシーチーム": [team[name] for name in names]},
        index=names,
    )
    constraint.days = days
    constraint.year, constraint.month = 2026, 12
    constraint.holiday_dates = set()
    constraint.hope_list = hope_list
    constraint.hope_day_column_map = {day: day for day in range(1, days + 1)}
    constraint.debug_enabled = False
    constraint.optimizer = SimpleNamespace(
        get_primary_work_var=lambda staff, day: shifts.get((staff, day)),
        get_half_day_hope=lambda staff, day: parse_half_day(
            (raw_hopes or {}).get((staff, day))
        ),
        register_objective_term=lambda name, expr: terms.__setitem__(name, expr),
    )
    constraint._get_weekday = lambda day: datetime.date(2026, 12, day).weekday()
    constraint._is_holiday = lambda day: day in holidays
    return constraint, shifts, terms


def _solve(constraint, terms):
    constraint.model.Minimize(sum(terms.values()))
    solver = cp_model.CpSolver()
    status = solver.Solve(constraint.model)
    return solver, status


def test_pair_is_secured_when_feasible():
    constraint, shifts, terms = _make_constraint()
    secured = constraint.add_porifa_pair_guarantee()
    assert secured is not None
    solver, status = _solve(constraint, terms)
    assert status in (cp_model.OPTIMAL, cp_model.FEASIBLE)
    assert solver.Value(secured) == 1
    # 少なくとも1ペアで全員が両日とも出勤している
    assert any(
        all(
            solver.Value(shifts[(member, day)]) == 1
            for member in MEMBERS
            for day in pair
        )
        for pair in PAIRS
    )


def test_soft_when_all_pairs_blocked_by_assignment():
    constraint, shifts, terms = _make_constraint()
    secured = constraint.add_porifa_pair_guarantee()
    # A を全ペア日で出勤不可にしても、解なしにはならずペナルティを受けるだけ
    for pair in PAIRS:
        for day in pair:
            constraint.model.Add(shifts[("A", day)] == 0)
    solver, status = _solve(constraint, terms)
    assert status in (cp_model.OPTIMAL, cp_model.FEASIBLE)
    assert solver.Value(secured) == 0


def test_no_constraint_when_hopes_block_all_pairs():
    hopes = {("A", friday): 4 for friday, _ in PAIRS}  # A が全金曜に終日有休
    constraint, _, terms = _make_constraint(hopes=hopes)
    assert constraint.add_porifa_pair_guarantee() is None
    assert terms == {}


def test_pm_leave_half_day_hope_blocks_pairs():
    raw_hopes = {("A", friday): "PM有" for friday, _ in PAIRS}
    constraint, _, terms = _make_constraint(raw_hopes=raw_hopes)
    assert constraint.add_porifa_pair_guarantee() is None
    assert terms == {}


def test_am_only_hope_still_counts_as_attendable():
    # AM出希望だけなら PM はソルバーが決められるため、ペアは成立しうる
    raw_hopes = {("A", day): "AM出" for pair in PAIRS for day in pair}
    constraint, _, terms = _make_constraint(raw_hopes=raw_hopes)
    secured = constraint.add_porifa_pair_guarantee()
    assert secured is not None
    solver, status = _solve(constraint, terms)
    assert status in (cp_model.OPTIMAL, cp_model.FEASIBLE)
    assert solver.Value(secured) == 1


def test_holiday_friday_pairs_are_skipped():
    constraint, shifts, terms = _make_constraint(holidays={4, 11, 18})
    secured = constraint.add_porifa_pair_guarantee()
    assert secured is not None
    solver, status = _solve(constraint, terms)
    assert status in (cp_model.OPTIMAL, cp_model.FEASIBLE)
    assert solver.Value(secured) == 1
    # 残った (25, 29) ペアで確保される
    assert all(
        solver.Value(shifts[(member, day)]) == 1
        for member in MEMBERS
        for day in (25, 29)
    )
