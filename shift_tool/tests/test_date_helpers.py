import datetime

import pandas as pd
from ortools.sat.python import cp_model

from optimizer.base_constraint import BaseConstraint


class DummyOptimizer:
    def __init__(self, hope_list, holidays):
        self.staff = pd.DataFrame(index=[1])
        self.days = 31
        self.year = 2026
        self.month = 1
        self.holidays = holidays
        self.shifts = {}
        self.concurrent_shifts = {}
        self.hope_list = hope_list
        self.primary_sections = []
        self.concurrent_sections = []
        self.night_shifts = {}


class DummyConstraint(BaseConstraint):
    def apply(self):
        return None


def build_constraint(hope_columns):
    hope_list = pd.DataFrame([[7] * len(hope_columns)], index=[1], columns=hope_columns)
    holidays = [(datetime.date(2026, 1, 1), "元日")]
    model = cp_model.CpModel()
    optimizer = DummyOptimizer(hope_list=hope_list, holidays=holidays)
    return DummyConstraint(model, optimizer)


def test_weekday_and_holiday_judgement():
    constraint = build_constraint([1, 2, 3])

    assert constraint._get_weekday(1) == 3  # 2026-01-01 は木曜
    assert constraint._is_holiday(1) is True
    assert constraint._is_holiday(2) is False


def test_hope_value_with_numeric_day_columns():
    constraint = build_constraint([1, 2, 3])
    constraint.hope_list.loc[1, 2] = 0

    assert constraint._get_hope_value(1, 2) == 0


def test_hope_value_with_string_day_columns():
    constraint = build_constraint(["1", "2", "3"])
    constraint.hope_list.loc[1, "3"] = 8

    assert constraint._get_hope_value(1, 3) == 8


def test_hope_value_with_date_columns():
    columns = [pd.Timestamp("2026-01-01"), pd.Timestamp("2026-01-02")]
    constraint = build_constraint(columns)
    constraint.hope_list.loc[1, pd.Timestamp("2026-01-02")] = 5

    assert constraint._get_hope_value(1, 2) == 5
