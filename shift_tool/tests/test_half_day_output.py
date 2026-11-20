"""半日出力のテスト。

mode1の結果（AM勤務/PM勤務）が分かれる日は、出勤表に半日の印を出す。
休む側の時間帯は希望の休暇種別を使い、種別がなければ「指」とする。
印は mode2 が同じ時間帯の出勤として読み戻せること。
"""
from types import SimpleNamespace

import openpyxl
import pandas as pd
import pytest

from create_calender import CalendarCreator

RED = "FFFF0000"


def _run(tmp_path, monkeypatch, row, hope):
    monkeypatch.chdir(tmp_path)
    df_result = pd.DataFrame([row])
    hope_list = pd.DataFrame([{"Name": row["Name"], "1": hope}])
    optimizer = SimpleNamespace(
        staff=pd.DataFrame(
            {"Floor": [1], "Floor2": [None], "Floor3": [None]},
            index=[row["Name"]],
        )
    )
    CalendarCreator().save_results(df_result, hope_list, optimizer, 2026, 10)
    path = tmp_path / "result" / "work_status_wide_2026_10.xlsx"
    workbook = openpyxl.load_workbook(path)
    sheet = workbook.active
    day_column = [c.column for c in sheet[1] if c.value == 1][0]
    for r in sheet.iter_rows(min_row=3):
        if r[0].value == row["Name"]:
            cell = sheet.cell(row=r[0].row, column=day_column)
            color = cell.font.color.rgb if cell.font and cell.font.color else None
            return ("" if cell.value is None else cell.value), color, path
    raise AssertionError("スタッフ行が見つからない")


def _base_row(**overrides):
    row = {
        "Name": "A", "日付": 1, "当直": "なし", "勤務状態": "出勤",
        "AM勤務": 1, "PM勤務": 1, "勤務時間": "",
    }
    row.update(overrides)
    return row


@pytest.mark.parametrize(
    ("am", "pm", "hope", "expected"),
    [
        (0, 1, "AM有PM出", "AM有PM出"),   # AM有給・PM出勤（希望で確定）
        (1, 0, "PM有", "AM出PM有"),       # PM有給（希望で確定）
        (1, 0, "AM出", "AM出PM指"),       # AM出希望でPMはソルバーが入れなかった
        (0, 1, "PM出", "AM指PM出"),       # PM出希望でAMはソルバーが入れなかった
        (0, 1, "AM指\nPM出", "AM指PM出"),  # 改行入り希望は正規化して出す
    ],
)
def test_split_day_mark_is_composed_from_periods(tmp_path, monkeypatch, am, pm, hope, expected):
    value, color, _ = _run(
        tmp_path, monkeypatch,
        _base_row(AM勤務=am, PM勤務=pm),
        hope,
    )
    assert value == expected
    assert color == RED


def test_split_day_mark_is_read_back_by_mode2(tmp_path, monkeypatch):
    from optimizer.mode2.shift_optimizer import ShiftOptimizer

    _, _, path = _run(
        tmp_path, monkeypatch,
        _base_row(AM勤務=0, PM勤務=1),
        "AM有PM出",
    )
    attendance = pd.read_excel(path, skiprows=[1]).fillna("").set_index("Name")
    mode2 = ShiftOptimizer.__new__(ShiftOptimizer)
    mode2.mode1_attendance_list = attendance
    mode2.hope_input = pd.DataFrame({"1": ["AM有PM出"]}, index=["A"])
    mode2.hope_day_column_map = {1: "1"}
    assert mode2.get_period_attendance_status("A", 1, "AM") is False
    assert mode2.get_period_attendance_status("A", 1, "PM") is True


def test_full_day_rows_are_unchanged(tmp_path, monkeypatch):
    value, _, _ = _run(tmp_path, monkeypatch, _base_row(), "出")
    assert value == "出"

    value, _, _ = _run(
        tmp_path, monkeypatch,
        _base_row(勤務状態="非出勤", AM勤務=0, PM勤務=0),
        "有",
    )
    assert value == "有"


def test_split_day_with_oncall_prefix(tmp_path, monkeypatch):
    value, color, _ = _run(
        tmp_path, monkeypatch,
        _base_row(AM勤務=0, PM勤務=1, 当直="当直担当"),
        "AM有PM出",
    )
    assert value == "AM有PM出◎"
    assert color == RED
