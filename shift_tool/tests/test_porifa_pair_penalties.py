"""ポリファーマシー連続週ペアのペナルティ（add_porifa_pair_penalties）のテスト。

ペア判定は作成する月の中だけで行う。12月作成時は作成期間に翌1月1〜3日も
含まれるが、その金曜・火曜はペア判定の対象にしない。
"""
from types import SimpleNamespace

from ortools.sat.python import cp_model

from optimizer.mode1.primary_shift.work_constraints import WorkConstraints


def _make_constraint(friday_days, tuesday_days, year=2026, month=12):
    model = cp_model.CpModel()
    constraint = WorkConstraints.__new__(WorkConstraints)
    constraint.model = model
    constraint.year, constraint.month = year, month
    fri_vars = {
        day: model.NewBoolVar(f"fri_{day}") for day in friday_days
    }
    tue_vars = {
        day: model.NewBoolVar(f"tue_{day}") for day in tuesday_days
    }
    constraint.optimizer = SimpleNamespace(
        porifa_friday_vars=fri_vars,
        porifa_tuesday_vars=tue_vars,
    )
    return constraint, fri_vars, tue_vars


def test_january_friday_is_not_counted():
    # 12月作成時、金曜が翌1月1日（32日目）しかない場合は
    # 月内の金曜がないためペナルティ自体を作らない
    constraint, _, _ = _make_constraint([32], [29])
    assert constraint.add_porifa_pair_penalties() == []


def test_unpaired_holdings_within_month_are_penalized():
    # 12月4日（金）と12月29日（火）は連続週ペアではないため、
    # 両方開催するとペナルティが付く（25日・29日のペア候補がある前提）
    constraint, fri_vars, tue_vars = _make_constraint([4, 25], [29])
    penalties = constraint.add_porifa_pair_penalties()
    assert len(penalties) == 1
    constraint.model.Add(fri_vars[4] == 1)
    constraint.model.Add(fri_vars[25] == 0)
    constraint.model.Add(tue_vars[29] == 1)
    solver = cp_model.CpSolver()
    assert solver.Solve(constraint.model) in (cp_model.OPTIMAL, cp_model.FEASIBLE)
    assert solver.Value(penalties[0]) == 1


def test_paired_holdings_within_month_are_not_penalized():
    # 12月25日（金・第4週）と12月29日（火・第5週）は連続週ペア
    constraint, fri_vars, tue_vars = _make_constraint([25], [29])
    penalties = constraint.add_porifa_pair_penalties()
    assert len(penalties) == 1
    constraint.model.Add(fri_vars[25] == 1)
    constraint.model.Add(tue_vars[29] == 1)
    solver = cp_model.CpSolver()
    assert solver.Solve(constraint.model) in (cp_model.OPTIMAL, cp_model.FEASIBLE)
    assert solver.Value(penalties[0]) == 0
