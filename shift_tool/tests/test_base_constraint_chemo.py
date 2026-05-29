import sys
from pathlib import Path

import pandas as pd
from ortools.sat.python import cp_model

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

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
            },
            index=[1],
        )
        self.days = 1
        self.year = 2026
        self.month = 1
        self.holidays = []
        self.shifts = {}
        self.concurrent_shifts = {}
        self.hope_list = pd.DataFrame(index=[1])
        self.primary_sections = []
        self.concurrent_sections = []
        self.night_shifts = {}


class DummyConstraint(BaseConstraint):
    def apply(self):
        return None


def test_build_section_availability_collects_chemo_staff_ids():
    model = cp_model.CpModel()
    optimizer = DummyOptimizer()
    optimizer.shifts[(1, 1, 9)] = model.NewBoolVar("shift_1_1_9")

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
        chemo_staff_ids=chemo_staff_ids,
    )

    assert chemo_staff_ids == [1]
    assert len(section_configs["化療"]["available_list"]) == 1
