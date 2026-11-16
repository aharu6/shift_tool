"""work_constraints の公平性計算から外来スタッフを除外するテスト（TODO :152）。"""
from types import SimpleNamespace

import pandas as pd
from ortools.sat.python import cp_model

from optimizer.mode1.primary_shift.work_constraints import WorkConstraints


def _make_work_constraints(staff, eligible_sections, primary_sections, floors):
    model = cp_model.CpModel()
    work_vars = {}

    def get_primary_work_var(staff_name, day):
        key = (staff_name, day)
        if key not in work_vars:
            work_vars[key] = model.NewBoolVar(f"work_{staff_name}_{day}")
        return work_vars[key]

    constraint = WorkConstraints.__new__(WorkConstraints)
    constraint.model = model
    constraint.days = 5
    constraint.staff = pd.DataFrame(
        {"Floor": [floors[name] for name in staff]},
        index=staff,
    )
    constraint.eligible_sections = eligible_sections
    constraint.get_eligible_sections = eligible_sections
    constraint.primary_sections = primary_sections
    constraint._work_day_vars = {}
    constraint._day_off_vars = {}
    constraint._staff_max_consecutive_work_vars = {}
    constraint._staff_max_consecutive_off_vars = {}
    constraint.optimizer = SimpleNamespace(
        get_primary_work_var=get_primary_work_var,
    )
    return constraint


def test_streak_fairness_excludes_outpatient_staff():
    # 外来セクション16も担当可能なスタッフは、他セクションの
    # 連勤・連休公平性グループに混ざらない
    constraint = _make_work_constraints(
        staff=["一般A", "一般B", "外来C"],
        eligible_sections={"一般A": [4], "一般B": [4], "外来C": [4, 16]},
        primary_sections=[4],
        floors={"一般A": 1, "一般B": 1, "外来C": 9},
    )
    constraint.add_consecutive_streak_fairness_penalties()

    assert "一般A" in constraint._staff_max_consecutive_work_vars
    assert "一般B" in constraint._staff_max_consecutive_work_vars
    assert "外来C" not in constraint._staff_max_consecutive_work_vars
    assert "外来C" not in constraint._staff_max_consecutive_off_vars


def test_primary_section_fairness_skips_outpatient_floor():
    # 外来（Floor 9 → セクション16）は専属業務の公平性計算の対象外
    constraint = _make_work_constraints(
        staff=["外来A", "外来B"],
        eligible_sections={"外来A": [16], "外来B": [16]},
        primary_sections=[16],
        floors={"外来A": 9, "外来B": 9},
    )
    penalties = constraint.add_primary_section_fairness_penalties()

    assert penalties == []
    var_names = [v.name for v in constraint.model.Proto().variables]
    assert not any(name.startswith("primary_section_count_16") for name in var_names)


def _make_year_end_constraint():
    model = cp_model.CpModel()
    work_vars = {}

    def get_primary_work_var(staff_name, day):
        key = (staff_name, day)
        if key not in work_vars:
            work_vars[key] = model.NewBoolVar(f"work_{staff_name}_{day}")
        return work_vars[key]

    constraint = WorkConstraints.__new__(WorkConstraints)
    constraint.model = model
    constraint.year = 2026
    constraint.month = 12
    constraint.days = 31
    constraint.staff = pd.DataFrame(
        {"Floor": [1, 1, 1, 9]},
        index=["前年2日", "前年1日", "前年0日", "外来"],
    )
    constraint.get_eligible_sections = {
        "前年2日": [1], "前年1日": [1], "前年0日": [1], "外来": [16],
    }
    constraint.previous_year_december_30_staff = {"前年2日", "外来"}
    constraint.previous_december_31_staff = {"前年2日"}
    constraint.previous_january_1_staff = {"前年1日"}
    constraint.previous_january_2_staff = set()
    constraint.previous_january_3_staff = set()
    constraint.optimizer = SimpleNamespace(
        get_primary_work_var=get_primary_work_var,
    )
    return constraint, model, work_vars


def test_year_end_balance_penalties_weighted_by_previous_count():
    constraint, model, work_vars = _make_year_end_constraint()
    penalties = constraint.add_year_end_balance_penalties()

    # 年末年始は12/30・12/31の2日。前年勤務がある2名×2日分だけ生成される
    # （前年0日と外来は対象外）
    assert len(penalties) == 4

    # 前年2日のスタッフの12/30出勤=係数2、前年1日のスタッフの12/31出勤=係数1
    model.Add(work_vars[("前年2日", 30)] == 1)
    model.Add(work_vars[("前年1日", 31)] == 1)
    model.Minimize(sum(penalties))
    solver = cp_model.CpSolver()
    assert solver.Solve(model) == cp_model.OPTIMAL
    assert solver.ObjectiveValue() == 3
