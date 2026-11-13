import datetime

import pandas as pd
import pytest
from ortools.sat.python import cp_model

from optimizer.method.base_constraint import BaseConstraint


class DummyOptimizer:
    def __init__(self, hope_list, holidays):
        self.staff = pd.DataFrame(index=["Name1"])
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
    hope_list = pd.DataFrame([[7] * len(hope_columns)], index=["Name1"], columns=hope_columns)
    holidays = [(datetime.date(2026, 1, 1), "元日")]
    model = cp_model.CpModel()
    optimizer = DummyOptimizer(hope_list=hope_list, holidays=holidays)
    return DummyConstraint(model, optimizer)


def test_weekday_and_holiday_judgement():
    constraint = build_constraint([1, 2, 3])

    assert constraint._get_weekday(1) == 3  # 2026-01-01 は木曜
    assert constraint._is_holiday(1) is True
    assert constraint._is_holiday(2) is True  # 年始特別休日


def test_hope_value_with_numeric_day_columns():
    constraint = build_constraint([1, 2, 3])
    constraint.hope_list.loc["Name1", 2] = 0

    assert constraint._get_hope_value("Name1", 2) == 0


def test_hope_value_with_string_day_columns():
    constraint = build_constraint(["1", "2", "3"])
    constraint.hope_list.loc["Name1", "3"] = 8

    assert constraint._get_hope_value("Name1", 3) == 8


def test_hope_value_with_date_columns():
    columns = [pd.Timestamp("2026-01-01"), pd.Timestamp("2026-01-02")]
    constraint = build_constraint(columns)
    constraint.hope_list.loc["Name1", pd.Timestamp("2026-01-02")] = 5

    assert constraint._get_hope_value("Name1", 2) == 5


def test_extended_december_dates_and_new_year_holidays():
    optimizer = DummyOptimizer(
        hope_list=pd.DataFrame([[7]], index=["Name1"], columns=[1]),
        holidays=[(datetime.date(2027, 1, 1), "元日")],
    )
    optimizer.year = 2026
    optimizer.month = 12
    optimizer.days = 34
    constraint = DummyConstraint(cp_model.CpModel(), optimizer)

    assert constraint._get_date(31) == datetime.date(2026, 12, 31)
    assert constraint._get_date(32) == datetime.date(2027, 1, 1)
    assert constraint._get_date(34) == datetime.date(2027, 1, 3)
    assert constraint._get_weekday(32) == 4
    assert all(constraint._is_holiday(day) for day in (30, 31, 32, 33, 34))


def test_extended_december_timestamp_hope_columns_map_to_next_year():
    columns = [pd.Timestamp("2026-12-01"), pd.Timestamp("2027-01-01")]
    optimizer = DummyOptimizer(
        hope_list=pd.DataFrame([[7, 14]], index=["Name1"], columns=columns),
        holidays=[],
    )
    optimizer.year = 2026
    optimizer.month = 12
    optimizer.days = 34
    constraint = DummyConstraint(cp_model.CpModel(), optimizer)

    assert constraint._get_hope_value("Name1", 1) == 7
    assert constraint._get_hope_value("Name1", 32) == 14


def test_extended_date_mapping_rejects_nonpositive_day():
    constraint = build_constraint([1])

    with pytest.raises(ValueError, match="1以上"):
        constraint._get_date(0)


def test_timestamp_outside_period_does_not_enter_hope_map():
    columns = [
        pd.Timestamp("2025-12-31"),
        pd.Timestamp("2026-01-01"),
        pd.Timestamp("2026-02-01"),
    ]
    constraint = build_constraint(columns)

    assert constraint.hope_day_column_map == {1: columns[1]}


def test_extended_december_duplicate_excel_columns_refer_to_january():
    columns = list(range(1, 32)) + ["1.1", "2.1", "3.1"]
    values = [7] * 31 + [14, 8, 0]
    optimizer = DummyOptimizer(
        hope_list=pd.DataFrame([values], index=["Name1"], columns=columns),
        holidays=[],
    )
    optimizer.year, optimizer.month, optimizer.days = 2026, 12, 34
    constraint = DummyConstraint(cp_model.CpModel(), optimizer)

    assert [constraint.hope_day_column_map[day] for day in (32, 33, 34)] == [
        "1.1", "2.1", "3.1"
    ]
    assert [constraint._get_hope_value("Name1", day) for day in (1, 32, 33, 34)] == [
        7, 14, 8, 0
    ]


def test_extended_december_missing_january_column_does_not_use_positional_fallback():
    optimizer = DummyOptimizer(
        hope_list=pd.DataFrame([[7, 14]], index=["Name1"], columns=[1, "note"]),
        holidays=[],
    )
    optimizer.year, optimizer.month, optimizer.days = 2026, 12, 34
    constraint = DummyConstraint(cp_model.CpModel(), optimizer)

    with pytest.raises(ValueError, match="32"):
        constraint._get_hope_value("Name1", 32)


def test_extended_december_duplicate_january_columns_are_rejected():
    optimizer = DummyOptimizer(
        hope_list=pd.DataFrame(
            [[14, 8]], index=["Name1"], columns=["1.1", pd.Timestamp("2027-01-01")]
        ),
        holidays=[],
    )
    optimizer.year, optimizer.month, optimizer.days = 2026, 12, 34

    with pytest.raises(ValueError, match="重複.*32"):
        DummyConstraint(cp_model.CpModel(), optimizer)
