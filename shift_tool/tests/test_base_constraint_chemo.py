import sys
from pathlib import Path

import pandas as pd
from ortools.sat.python import cp_model

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from optimizer.primary_shift.work_constraints import WorkConstraints
from optimizer.base_constraint import BaseConstraint
from config.section_configs import SECTION_CONFIGS, make_section_configs


class DummyOptimizer:
    def __init__(self):
        self.staff = pd.DataFrame(
            {
                "Floor": [6],
                "Floor2": [8],
                "Floor3": [None],
                "緩和回診": [False],
                "心不全回診": [False],
                "ポリファーマシーチーム": [False],
                "実習": [False],
                "NST": [False],
                "マスター管理": [False],
                "RI": [False],
                "医薬品安全使用WG": [False],
            },
            index=["Name1"],
        )
        self.days = 1
        self.year = 2026
        self.month = 1
        self.holidays = []
        self.shifts = {}
        self.concurrent_shifts = {}
        self.hope_list = pd.DataFrame(index=["Name1"])
        self.primary_sections = []
        self.concurrent_sections = []
        self.night_shifts = {}


class DummyConstraint(BaseConstraint):
    def apply(self):
        return None


def test_make_section_configs_preserves_metadata_and_uses_fresh_available_lists():
    assigned_lists = {
        section_name: [] for section_name in SECTION_CONFIGS
    }
    required_staff = ["Name1"]
    required_list = []

    first_configs = make_section_configs(
        assigned_lists,
        required_staff,
        required_list,
    )
    second_configs = make_section_configs(
        assigned_lists,
        required_staff,
        required_list,
    )

    assert set(first_configs) == set(SECTION_CONFIGS)
    assert first_configs["1-2F"]["section_id"] == 4
    assert first_configs["1-2F"]["assigned_list"] is assigned_lists["1-2F"]
    assert first_configs["1-2F"]["required_staff"] is required_staff
    assert first_configs["1-2F"]["required_list"] is required_list
    assert first_configs["1-2F"]["check_day_off"] is True
    assert first_configs["NST"]["check_oncall_next"] is False
    assert first_configs["課長"]["check_oncall_next"] is True
    assert first_configs["1-2F"]["available_list"] is not second_configs["1-2F"]["available_list"]


class DummyWorkOptimizer:
    def __init__(self):
        self.staff = pd.DataFrame(
            {
                "Floor": [6],
                "Floor2": [None],
                "Floor3": [None],
                "緩和回診": [False],
                "心不全回診": [False],
                "ポリファーマシーチーム": [False],
                "実習": [False],
                "NST": [False],
                "マスター管理": [False],
                "RI": [False],
                "医薬品安全使用WG": [False],
            },
            index=["Name1"],
        )
        self.days = 1
        self.year = 2026
        self.month = 1
        self.holidays = []
        self.shifts = {}
        self.concurrent_shifts = {}
        self.hope_list = pd.DataFrame(index=["Name1"])
        self.primary_sections = [9]
        self.concurrent_sections = []
        self.night_shifts = {}
        self.prev_month_oncall_staff_ids = []
        self.objective_terms = {}

    def register_objective_term(self, name, expr):
        self.objective_terms[name] = expr


class DummySaturdayDualEligibleOptimizer:
    def __init__(self):
        self.staff = pd.DataFrame(
            {
                "Floor": [6, 6, 6, 6, 6],
                "Floor2": [8, 8, 8, 8, 8],
                "Floor3": [None, None, None, None, None],
                "緩和回診": [False, False, False, False, False],
                "心不全回診": [False, False, False, False, False],
                "ポリファーマシーチーム": [False, False, False, False, False],
                "実習": [False, False, False, False, False],
                "NST": [False, False, False, False, False],
                "マスター管理": [False, False, False, False, False],
                "RI": [False, False, False, False, False],
                "医薬品安全使用WG": [False, False, False, False, False],
                "日曜出勤": [True, True, True, True, True],
            },
            index=["Name1", "Name2", "Name3", "Name4", "Name5"],
        )
        self.days = 1
        self.year = 2026
        self.month = 8
        self.holidays = []
        self.shifts = {}
        self.concurrent_shifts = {}
        self.hope_list = pd.DataFrame(
            {1: [7, 7, 7, 7, 7]},
            index=["Name1", "Name2", "Name3", "Name4", "Name5"],
        )
        self.primary_sections = [1, 9]
        self.concurrent_sections = [11]
        self.night_shifts = {}
        self.prev_month_oncall_staff_ids = []
        self.objective_terms = {}

    def register_objective_term(self, name, expr):
        self.objective_terms[name] = expr


class DummyTuesdayPorifaOptimizer:
    def __init__(self, day_three_requests=None):
        staff_names = ["Porifa1", "Porifa2", "Porifa3"]
        self.staff = pd.DataFrame(
            {
                "Floor": [8, 8, 8],
                "Floor2": [None, None, None],
                "Floor3": [None, None, None],
                "緩和回診": [False, False, False],
                "心不全回診": [False, False, False],
                "ポリファーマシーチーム": [True, True, True],
                "実習": [False, False, False],
                "NST": [False, False, False],
                "マスター管理": [False, False, False],
                "RI": [False, False, False],
                "医薬品安全使用WG": [False, False, False],
                "日曜出勤": [True, True, True],
            },
            index=staff_names,
        )
        self.days = 3
        self.year = 2026
        self.month = 2
        self.holidays = []
        self.shifts = {}
        self.concurrent_shifts = {}
        self.hope_list = pd.DataFrame(
            {
                1: [7, 7, 7],
                2: [7, 7, 7],
                3: day_three_requests or [7, 7, 7],
            },
            index=staff_names,
        )
        self.primary_sections = [11]
        self.concurrent_sections = []
        self.night_shifts = {}
        self.porifa_tuesday_vars = {}
        self.porifa_friday_vars = {}
        self.prev_month_oncall_staff_ids = []
        self.objective_terms = {}

    def register_objective_term(self, name, expr):
        self.objective_terms[name] = expr


def _build_tuesday_porifa_constraint(day_three_requests=None):
    """火曜日のポリファーマシーチームの制約を構築する

    Args:
        day_three_requests (list, optional): 3日目の希望シフトのリスト。デフォルトはNone。

    Returns:
        tuple: モデルとオプティマイザのタプル。
    """
    model = cp_model.CpModel()
    optimizer = DummyTuesdayPorifaOptimizer(day_three_requests)
    for staff in optimizer.staff.index:
        for day in range(1, optimizer.days + 1):
            # ポリファーマシーチームのシフト変数を作成する
            optimizer.shifts[(staff, day, 11)] = model.NewBoolVar(
                f"porifa_{staff}_{day}"
            )
            # 明けのシフト変数を作成する
            optimizer.shifts[(staff, day, 17)] = model.NewBoolVar(
                f"ake_{staff}_{day}"
            )
            # 調剤室のシフト変数を作成する
            optimizer.shifts[(staff, day, 1)] = model.NewBoolVar(
                f"dispensing_{staff}_{day}"
            )
            # 
            model.Add(optimizer.shifts[(staff, day, 17)] == 0)

    constraint = WorkConstraints(model, optimizer)
    constraint.eligible_sections = constraint.get_eligible_sections
    constraint.tuesday_porifa_week_num = 1
    constraint.add_section_requests()
    return model, optimizer


def test_build_section_availability_collects_chemo_staff_ids():
    model = cp_model.CpModel()
    optimizer = DummyOptimizer()
    optimizer.shifts[("Name1", 1)] = model.NewBoolVar("shift_Name1_1")

    constraint = DummyConstraint(model, optimizer)
    chemo_staff_ids = []
    section_configs = {
        "化療": {
            "section_id": 9,
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
        chemo_staff_ids=chemo_staff_ids,
    )

    assert chemo_staff_ids == ["Name1"]
    assert len(section_configs["化療"]["available_list"]) == 1


def test_build_section_availability_uses_daily_work_var_for_day_two():
    model = cp_model.CpModel()
    optimizer = DummyOptimizer()
    optimizer.days = 2
    work_var = model.NewBoolVar("shift_Name1_2_2")
    optimizer.shifts[("Name1", 2)] = work_var

    constraint = DummyConstraint(model, optimizer)
    constraint.get_eligible_sections = {"Name1": [11]}
    porifa_staff_ids = []
    section_configs = {
        "ポリファーマシー": {
            "section_id": 11,
            "assigned_list": [],
            "available_list": [],
            "check_day_off": True,
        }
    }

    constraint._build_section_availability(
        section_configs=section_configs,
        day=2,
        year=optimizer.year,
        porifa_staff_ids=porifa_staff_ids,
    )

    assert section_configs["ポリファーマシー"]["assigned_list"] == [work_var]
    assert porifa_staff_ids == ["Name1"]


def test_saturday_primary_chemo_requirement_is_two():
    model = cp_model.CpModel()
    optimizer = DummyWorkOptimizer()

    constraint = WorkConstraints(model, optimizer)
    requirements = constraint._get_section_min_requirements(
        day=1,
        weekday=5,
        is_holiday=False,
        prev_day_is_holiday=False,
    )

    assert requirements["化療"] == 2


def test_saturday_chemo_shortage_penalty_for_one_available_staff():
    model = cp_model.CpModel()
    optimizer = DummyWorkOptimizer()
    assigned_chemo = [model.NewBoolVar("chemo_Name1")]
    model.Add(assigned_chemo[0] == 1)

    constraint = WorkConstraints(model, optimizer)
    shortage, excess = constraint._add_shortage_penalty(
        assigned_vars=assigned_chemo,
        effective_required=2,
        required_count=2,
        day=1,
        section_name="chemo",
    )

    solver = cp_model.CpSolver()
    status = solver.Solve(model)

    assert status in (cp_model.OPTIMAL, cp_model.FEASIBLE)
    assert solver.Value(shortage) == 1
    assert solver.Value(excess) == 0
    assert "chemo_shortage_1" in optimizer.objective_terms


def test_saturday_chemo_shortage_penalty_is_zero_for_two_staff():
    model = cp_model.CpModel()
    optimizer = DummyWorkOptimizer()
    assigned_chemo = [
        model.NewBoolVar("chemo_Name1"),
        model.NewBoolVar("chemo_Name2"),
    ]
    model.Add(sum(assigned_chemo) == 2)

    constraint = WorkConstraints(model, optimizer)
    shortage, excess = constraint._add_shortage_penalty(
        assigned_vars=assigned_chemo,
        effective_required=2,
        required_count=2,
        day=1,
        section_name="chemo",
    )

    solver = cp_model.CpSolver()
    status = solver.Solve(model)

    assert status in (cp_model.OPTIMAL, cp_model.FEASIBLE)
    assert solver.Value(shortage) == 0
    assert solver.Value(excess) == 0


def test_daily_work_var_is_used_for_section_availability():
    model = cp_model.CpModel()
    optimizer = DummyOptimizer()
    work_var = model.NewBoolVar("work_Name1_2")
    optimizer.shifts[("Name1", 2)] = work_var
    constraint = DummyConstraint(model, optimizer)
    constraint.get_eligible_sections = {"Name1": [11]}
    assigned_porifa_ids = []
    section_configs = {
        "ポリファーマシー": {
            "section_id": 11,
            "assigned_list": [],
            "available_list": [],
            "check_day_off": True,
        }
    }

    constraint._build_section_availability(
        section_configs=section_configs,
        day=2,
        year=optimizer.year,
        porifa_staff_ids=assigned_porifa_ids,
    )

    assert section_configs["ポリファーマシー"]["assigned_list"] == [work_var]
    assert assigned_porifa_ids == ["Name1"]
