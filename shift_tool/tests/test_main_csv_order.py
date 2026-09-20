import pandas as pd

from main import _pivot_staff_day_wide


def test_pivot_staff_day_wide_keeps_staff_input_order():
    df = pd.DataFrame(
        [
            {"スタッフ": "NameB", "日付": 1, "専属業務": "A"},
            {"スタッフ": "NameA", "日付": 1, "専属業務": "B"},
            {"スタッフ": "NameC", "日付": 1, "専属業務": "C"},
        ]
    )

    wide = _pivot_staff_day_wide(df, value_column="専属業務", fill_value="休み")

    assert list(wide.index) == ["NameB", "NameA", "NameC"]


def test_pivot_staff_day_wide_fills_missing_cells():
    df = pd.DataFrame(
        [
            {"スタッフ": "NameB", "日付": 1, "当直": "当直担当（相方: NameA）"},
            {"スタッフ": "NameA", "日付": 2, "当直": "なし"},
        ]
    )

    wide = _pivot_staff_day_wide(df, value_column="当直", fill_value="なし")

    assert wide.loc["NameB", 2] == "なし"
    assert wide.loc["NameA", 1] == "なし"
