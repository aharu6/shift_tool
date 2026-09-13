import sys
from pathlib import Path

import pandas as pd
from ortools.sat.python import cp_model

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from optimizer.primary_shift.work_constraints import WorkConstraints
from optimizer.base_constraint import BaseConstraint


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
    model = cp_model.CpModel()
    optimizer = DummyTuesdayPorifaOptimizer(day_three_requests)
    for staff in optimizer.staff.index:
        for day in range(1, optimizer.days + 1):
            optimizer.shifts[(staff, day, 11)] = model.NewBoolVar(
                f"porifa_{staff}_{day}"
            )
            optimizer.shifts[(staff, day, 17)] = model.NewBoolVar(
                f"ake_{staff}_{day}"
            )
            optimizer.shifts[(staff, day, 1)] = model.NewBoolVar(
                f"dispensing_{staff}_{day}"
            )
            model.Add(optimizer.shifts[(staff, day, 17)] == 0)

    constraint = WorkConstraints(model, optimizer)
    constraint.eligible_sections = constraint.get_eligible_sections
    constraint.tuesday_porifa_week_num = 1
    constraint.add_section_requests()
    return model, optimizer


def test_build_section_availability_collects_chemo_staff_ids():
    model = cp_model.CpModel()
    optimizer = DummyOptimizer()
    optimizer.shifts[("Name1", 1, 9)] = model.NewBoolVar("shift_Name1_1_9")
    optimizer.shifts[("Name1", 1, 17)] = model.NewBoolVar("ake_Name1_1")
    model.Add(optimizer.shifts[("Name1", 1, 17)] == 0)

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


def test_saturday_primary_chemo_requirement_is_zero():
    model = cp_model.CpModel()
    optimizer = DummyWorkOptimizer()

    constraint = WorkConstraints(model, optimizer)
    requirements = constraint._get_section_min_requirements(
        day=1,
        weekday=5,
        is_holiday=False,
        prev_day_is_holiday=False,
    )

    assert requirements["化療"] == 0


def test_saturday_dual_eligible_staff_link_dispensing_to_concurrent_chemo():
    model = cp_model.CpModel()
    optimizer = DummySaturdayDualEligibleOptimizer()

    for staff in optimizer.staff.index:
        optimizer.shifts[(staff, 1, 1)] = model.NewBoolVar(f"dispensing_{staff}")
        optimizer.shifts[(staff, 1, 9)] = model.NewBoolVar(f"chemo_{staff}")
        optimizer.shifts[(staff, 1, 17)] = model.NewBoolVar(f"ake_{staff}")
        model.Add(optimizer.shifts[(staff, 1, 17)] == 0)
        optimizer.concurrent_shifts[(staff, 1, 11)] = model.NewBoolVar(f"concurrent_chemo_{staff}")

    constraint = WorkConstraints(model, optimizer)
    constraint.eligible_sections = constraint.get_eligible_sections
    constraint.add_section_requests()

    solver = cp_model.CpSolver()
    status = solver.Solve(model)

    assert status in (cp_model.OPTIMAL, cp_model.FEASIBLE)
    assert sum(solver.Value(optimizer.shifts[(staff, 1, 1)]) for staff in optimizer.staff.index) == 5
    assert sum(solver.Value(optimizer.concurrent_shifts[(staff, 1, 11)]) for staff in optimizer.staff.index) == 2
    for staff in optimizer.staff.index:
        assert solver.Value(optimizer.concurrent_shifts[(staff, 1, 11)]) <= solver.Value(optimizer.shifts[(staff, 1, 1)])


def test_saturday_non_dual_staff_cannot_receive_concurrent_chemo():
    model = cp_model.CpModel()
    optimizer = DummySaturdayDualEligibleOptimizer()
    non_dual_staff = "Name5"
    optimizer.staff.loc[non_dual_staff, "Floor2"] = None

    for staff in optimizer.staff.index:
        optimizer.shifts[(staff, 1, 1)] = model.NewBoolVar(f"dispensing_{staff}")
        optimizer.shifts[(staff, 1, 9)] = model.NewBoolVar(f"chemo_{staff}")
        optimizer.shifts[(staff, 1, 17)] = model.NewBoolVar(f"ake_{staff}")
        model.Add(optimizer.shifts[(staff, 1, 17)] == 0)
        optimizer.concurrent_shifts[(staff, 1, 11)] = model.NewBoolVar(
            f"concurrent_chemo_{staff}"
        )

    constraint = WorkConstraints(model, optimizer)
    constraint.eligible_sections = constraint.get_eligible_sections
    constraint.add_section_requests()

    solver = cp_model.CpSolver()
    status = solver.Solve(model)

    assert status in (cp_model.OPTIMAL, cp_model.FEASIBLE)
    assert solver.Value(optimizer.concurrent_shifts[(non_dual_staff, 1, 11)]) == 0


def test_tuesday_porifa_assigns_all_members_when_everyone_is_available():
    model, optimizer = _build_tuesday_porifa_constraint()

    solver = cp_model.CpSolver()
    status = solver.Solve(model)

    assert status in (cp_model.OPTIMAL, cp_model.FEASIBLE)
    assert sum(
        solver.Value(optimizer.shifts[(staff, 3, 11)])
        for staff in optimizer.staff.index
    ) == len(optimizer.staff.index)


def test_tuesday_porifa_is_not_held_when_any_member_is_unavailable():
    model, optimizer = _build_tuesday_porifa_constraint([7, 0, 7])

    solver = cp_model.CpSolver()
    status = solver.Solve(model)

    assert status in (cp_model.OPTIMAL, cp_model.FEASIBLE)
    assert sum(
        solver.Value(optimizer.shifts[(staff, 3, 11)])
        for staff in optimizer.staff.index
    ) == 0
