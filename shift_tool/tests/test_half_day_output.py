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
    workbook = openpyxl.load_workbook(path, rich_text=True)
    sheet = workbook.active
    day_column = [c.column for c in sheet[1] if c.value == 1][0]
    for r in sheet.iter_rows(min_row=3):
        if r[0].value == row["Name"]:
            cell = sheet.cell(row=r[0].row, column=day_column)
            color = cell.font.color.rgb if cell.font and cell.font.color else None
            return ("" if cell.value is None else cell.value), color, path
    raise AssertionError("スタッフ行が見つからない")


def _segments(value, color):
    """セルの表示を (文字列, 赤字か) の部分列に分解する。"""
    from openpyxl.cell.rich_text import CellRichText

    if isinstance(value, CellRichText):
        parts = []
        for block in value:
            font = getattr(block, "font", None)
            rgb = None
            if font is not None and getattr(font, "color", None) is not None:
                rgb = getattr(font.color, "rgb", None)
            parts.append((block.text, rgb == RED))
        return parts
    text = "" if value is None else str(value)
    return [(text, color == RED)] if text else []


def _base_row(**overrides):
    row = {
        "Name": "A", "日付": 1, "当直": "なし", "勤務状態": "出勤",
        "AM勤務": 1, "PM勤務": 1, "勤務時間": "",
    }
    row.update(overrides)
    return row


@pytest.mark.parametrize(
    ("am", "pm", "hope", "expected", "red_parts"),
    [
        # 希望で両半日とも指定された日は全体が赤字
        (0, 1, "AM有PM出", "AM有PM出", ["AM有PM出"]),
        (0, 1, "AM指\nPM出", "AM指PM出", ["AM指PM出"]),
        # 希望で指定された半日だけが赤字（もう半日はソルバーの決定）
        (1, 0, "PM有", "AM出PM有", ["PM有"]),
        (1, 0, "AM出", "AM出PM指", ["AM出"]),
        (0, 1, "PM出", "AM指PM出", ["PM出"]),
    ],
)
def test_split_day_mark_is_composed_from_periods(tmp_path, monkeypatch, am, pm, hope, expected, red_parts):
    value, color, _ = _run(
        tmp_path, monkeypatch,
        _base_row(AM勤務=am, PM勤務=pm),
        hope,
    )
    assert str(value) == expected
    segments = _segments(value, color)
    assert "".join(text for text, _ in segments) == expected
    assert [text for text, is_red in segments if is_red] == red_parts


@pytest.mark.parametrize(
    ("hope", "red_parts"),
    [
        ("AM出", ["AM出"]),  # AM出希望で両半日出勤になった日
        ("PM出", ["PM出"]),  # PM出希望で両半日出勤になった日
    ],
)
def test_full_work_day_from_half_day_hope(tmp_path, monkeypatch, hope, red_parts):
    # 半日希望でもソルバーが両半日入れた日は「AM出PM出」と表示され、
    # 希望した半日だけが赤字になる
    value, color, _ = _run(
        tmp_path, monkeypatch,
        _base_row(AM勤務=1, PM勤務=1, 勤務時間="AM出PM出"),
        hope,
    )
    assert str(value) == "AM出PM出"
    segments = _segments(value, color)
    assert [text for text, is_red in segments if is_red] == red_parts
    assert [text for text, is_red in segments if not is_red] == [
        part for part in ("AM出", "PM出") if part not in red_parts
    ]


def test_full_work_day_from_half_day_hope_with_oncall(tmp_path, monkeypatch):
    value, color, _ = _run(
        tmp_path, monkeypatch,
        _base_row(AM勤務=1, PM勤務=1, 勤務時間="AM出PM出", 当直="当直担当"),
        "PM出",
    )
    assert str(value) == "AM出PM出◎"
    segments = _segments(value, color)
    # 希望したPM出だけ赤字。当直は希望していないので◎は黒
    assert [text for text, is_red in segments if is_red] == ["PM出"]


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
    assert str(value) == "AM有PM出◎"
    segments = _segments(value, color)
    # 希望で指定された両半日は赤字。当直は希望していないので◎は黒
    assert [text for text, is_red in segments if is_red] == ["AM有", "PM出"]
    assert [text for text, is_red in segments if not is_red] == ["◎"]
