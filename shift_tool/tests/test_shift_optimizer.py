from optimizer.shift_optimizer import ShiftOptimizer
import pandas as pd


def test_get_days_in_month_leap_year_february():
    optimizer = ShiftOptimizer.__new__(ShiftOptimizer)
    optimizer.year = 2024
    optimizer.month = 2

    assert optimizer._get_days_in_month() == 29


def test_get_days_in_month_non_leap_february():
    optimizer = ShiftOptimizer.__new__(ShiftOptimizer)
    optimizer.year = 2026
    optimizer.month = 2

    assert optimizer._get_days_in_month() == 28


def test_get_oncall_pair_normalizes_order():
    optimizer = ShiftOptimizer.__new__(ShiftOptimizer)
    expected = object()
    optimizer.night_shifts = {("NameA", "NameB", 3): expected}

    assert optimizer.get_oncall_pair("NameA", "NameB", 3) is expected
    assert optimizer.get_oncall_pair("NameB", "NameA", 3) is expected


def test_get_oncall_pair_same_staff_returns_none():
    optimizer = ShiftOptimizer.__new__(ShiftOptimizer)
    optimizer.night_shifts = {}

    assert optimizer.get_oncall_pair("NameA", "NameA", 3) is None


def test_normalize_boolean_column_handles_staff_availability_values():
    values = pd.Series([False, True, 0, 1, "FALSE", "当直不可", "当直可", None])

    normalized = ShiftOptimizer._normalize_boolean_column(values)

    assert normalized.tolist() == [False, True, False, True, False, False, True, False]
