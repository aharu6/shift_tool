"""#170・#176 希望の転記と赤文字のテスト。

- 出勤希望（出・出×・×出など）は実際に出勤した日にだけ転記し、
  出×・×出・出当×は「出」に統一する
- 当直不可のみ・当直希望のみ・希望なしは転記しない
- 希望由来の表示は赤文字。当直希望が通った日の◎も赤文字
- mode2 は「出」を出勤として読む
"""
from types import SimpleNamespace

import openpyxl
import pandas as pd
import pytest

from create_calender import CalendarCreator


def _run_save_results(tmp_path, monkeypatch, result_rows, hope_rows):
    monkeypatch.chdir(tmp_path)
    df_result = pd.DataFrame(result_rows)
    hope_list = pd.DataFrame(hope_rows)
    optimizer = SimpleNamespace(
        staff=pd.DataFrame(
            {"Floor": [1] * len(hope_rows), "Floor2": [None] * len(hope_rows),
             "Floor3": [None] * len(hope_rows)},
            index=[row["Name"] for row in hope_rows],
        )
    )
    CalendarCreator().save_results(df_result, hope_list, optimizer, 2026, 10)
    return tmp_path / "result" / "work_status_wide_2026_10.xlsx"


def _cell(xlsx_path, name, day):
    workbook = openpyxl.load_workbook(xlsx_path)
    sheet = workbook.active
    day_column = None
    for cell in sheet[1]:
        if cell.value == day:
            day_column = cell.column
    for row in sheet.iter_rows(min_row=3):
        if row[0].value == name:
            cell = sheet.cell(row=row[0].row, column=day_column)
            color = cell.font.color.rgb if cell.font and cell.font.color else None
            return cell.value, color
    raise AssertionError(f"{name} の行が見つからない")


RED = "FFFF0000"


def test_work_hope_is_transcribed_and_red(tmp_path, monkeypatch):
    path = _run_save_results(
        tmp_path, monkeypatch,
        [{"Name": "A", "日付": 1, "当直": "なし", "勤務状態": "出勤"}],
        [{"Name": "A", "1": "出"}],
    )
    value, color = _cell(path, "A", 1)
    assert value == "出"
    assert color == RED


@pytest.mark.parametrize("hope", ["出×", "×出", "出当×", "出\n×"])
def test_oncall_blocked_work_hopes_are_unified_to_shutsu(tmp_path, monkeypatch, hope):
    path = _run_save_results(
        tmp_path, monkeypatch,
        [{"Name": "A", "日付": 1, "当直": "なし", "勤務状態": "出勤"}],
        [{"Name": "A", "1": hope}],
    )
    value, color = _cell(path, "A", 1)
    assert value == "出"
    assert color == RED


def test_work_hope_is_hidden_when_not_attending(tmp_path, monkeypatch):
    path = _run_save_results(
        tmp_path, monkeypatch,
        [{"Name": "A", "日付": 1, "当直": "なし", "勤務状態": "非出勤"}],
        [{"Name": "A", "1": "出"}],
    )
    value, color = _cell(path, "A", 1)
    assert value == "指"
    assert color != RED


def test_oncall_blocked_only_hope_is_not_transcribed(tmp_path, monkeypatch):
    path = _run_save_results(
        tmp_path, monkeypatch,
        [{"Name": "A", "日付": 1, "当直": "なし", "勤務状態": "出勤"}],
        [{"Name": "A", "1": "×"}],
    )
    value, color = _cell(path, "A", 1)
    assert value in (None, "")
    assert color != RED


def test_granted_oncall_hope_makes_oncall_mark_red(tmp_path, monkeypatch):
    path = _run_save_results(
        tmp_path, monkeypatch,
        [{"Name": "A", "日付": 1, "当直": "当直担当", "勤務状態": "出勤"}],
        [{"Name": "A", "1": "◎"}],
    )
    value, color = _cell(path, "A", 1)
    assert value == "◎"
    assert color == RED


def test_ungranted_oncall_hope_is_not_transcribed(tmp_path, monkeypatch):
    path = _run_save_results(
        tmp_path, monkeypatch,
        [{"Name": "A", "日付": 1, "当直": "なし", "勤務状態": "出勤"}],
        [{"Name": "A", "1": "◎"}],
    )
    value, color = _cell(path, "A", 1)
    assert value in (None, "")
    assert color != RED


def test_oncall_without_hope_is_not_red(tmp_path, monkeypatch):
    path = _run_save_results(
        tmp_path, monkeypatch,
        [{"Name": "A", "日付": 1, "当直": "当直担当", "勤務状態": "出勤"}],
        [{"Name": "A", "1": ""}],
    )
    value, color = _cell(path, "A", 1)
    assert value == "◎"
    assert color != RED


def test_leave_hopes_are_transcribed_and_red(tmp_path, monkeypatch):
    path = _run_save_results(
        tmp_path, monkeypatch,
        [
            {"Name": "A", "日付": 1, "当直": "なし", "勤務状態": "非出勤"},
            {"Name": "A", "日付": 2, "当直": "なし", "勤務状態": "非出勤"},
        ],
        [{"Name": "A", "1": "有", "2": "育休"}],
    )
    assert _cell(path, "A", 1) == ("有", RED)
    assert _cell(path, "A", 2) == ("育休", RED)


@pytest.mark.parametrize(
    ("hope", "expected"),
    [("学会", "学"), ("学", "学"), ("研修", "研"), ("研", "研")],
)
def test_gakkai_kenshu_display_is_unified(tmp_path, monkeypatch, hope, expected):
    # 書き出し時はコード6=研、コード11=学に統一する
    path = _run_save_results(
        tmp_path, monkeypatch,
        [{"Name": "A", "日付": 1, "当直": "なし", "勤務状態": "出勤"}],
        [{"Name": "A", "1": hope}],
    )
    assert _cell(path, "A", 1) == (expected, RED)


def test_oncall_only_suffix_name_still_matches(tmp_path, monkeypatch):
    """希望表で「（◎のみ）」付きの名前でも、当直希望が通った◎が赤くなる。"""
    path = _run_save_results(
        tmp_path, monkeypatch,
        [{"Name": "A", "日付": 1, "当直": "当直担当", "勤務状態": "出勤"}],
        [{"Name": "A（◎のみ）", "1": "◎"}],
    )
    value, color = _cell(path, "A", 1)
    assert value == "◎"
    assert color == RED


@pytest.mark.parametrize("mark", ["出", "出勤", "出×", "×出", "出当×"])
def test_mode2_reads_work_marks_as_attending(mark):
    from optimizer.mode2.shift_optimizer import ShiftOptimizer

    mode2 = ShiftOptimizer.__new__(ShiftOptimizer)
    mode2.mode1_attendance_list = pd.DataFrame([[mark]], index=["A"], columns=[1])
    mode2.hope_input = pd.DataFrame({"1": [mark]}, index=["A"])
    mode2.hope_day_column_map = {1: "1"}
    assert mode2.get_period_attendance_status("A", 1, "AM") is True
    assert mode2.get_period_attendance_status("A", 1, "PM") is True
