from pathlib import Path

import main
import pandas as pd


def test_find_previous_month_file_accepts_legacy_unpadded_month(tmp_path, monkeypatch):
    result_dir = tmp_path / "result"
    result_dir.mkdir()
    legacy_file = result_dir / "Shift_wide_2026_8.csv"
    legacy_file.write_text("Name,1\nNameA,休み\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    assert main._find_previous_month_file("Shift_wide", 2026, 9) == Path(
        "result/Shift_wide_2026_8.csv"
    )


def test_find_previous_month_file_prefers_padded_month(tmp_path, monkeypatch):
    result_dir = tmp_path / "result"
    result_dir.mkdir()
    padded_file = result_dir / "Shift_wide_2026_08.csv"
    legacy_file = result_dir / "Shift_wide_2026_8.csv"
    padded_file.touch()
    legacy_file.touch()
    monkeypatch.chdir(tmp_path)

    assert main._find_previous_month_file("Shift_wide", 2026, 9) == Path(
        "result/Shift_wide_2026_08.csv"
    )


def test_load_previous_year_december_30_staff_supports_staff_column(tmp_path, monkeypatch):
    result_dir = tmp_path / "result"
    result_dir.mkdir()
    pd.DataFrame(
        {
            "スタッフ": ["Staff A", "Staff B", "Staff C", "Staff D"],
            "29": ["勤務", "休", "勤務", "勤務"],
            "30": ["勤務", "休", "有", "調剤室"],
        }
    ).to_csv(result_dir / "Shift_wide_2025_12.csv", index=False, encoding="utf-8-sig")
    monkeypatch.chdir(tmp_path)

    assert main._load_previous_year_december_30_staff(2026) == {
        "Staff A",
        "Staff D",
    }


def test_load_previous_year_december_30_staff_returns_empty_for_missing_day(tmp_path, monkeypatch):
    result_dir = tmp_path / "result"
    result_dir.mkdir()
    pd.DataFrame({"Name": ["Staff A"], "29": ["勤務"]}).to_csv(
        result_dir / "Shift_wide_2025_12.csv", index=False
    )
    monkeypatch.chdir(tmp_path)

    assert main._load_previous_year_december_30_staff(2026) == set()


def test_weekly_schedule_uses_display_name_from_staff_index(tmp_path, monkeypatch):
    captured_sheets = []
    monkeypatch.setattr(
        pd.DataFrame,
        "to_excel",
        lambda frame, *args, **kwargs: captured_sheets.append(frame.copy()),
    )
    shift = pd.DataFrame(
        {
            "Name": ["Staff A"],
            "日付": [1],
            "専属業務": ["調剤室"],
            "兼務業務": [""],
            "当直": ["なし"],
        }
    )
    staff_info = pd.DataFrame(
        {"Name": [" Staff A "], "表示名": ["表示A"]},
        index=pd.Index(["Staff A"], name="Name"),
    )

    main.mk_weekly_shift_schedule(shift, 2026, 9, tmp_path, staff_info)

    assert captured_sheets[0].loc["調剤室", "09/01 (火曜日)"] == "表示A"


def test_weekly_schedule_marks_oncall_display_name(tmp_path, monkeypatch):
    captured_sheets = []
    monkeypatch.setattr(
        pd.DataFrame,
        "to_excel",
        lambda frame, *args, **kwargs: captured_sheets.append(frame.copy()),
    )
    shift = pd.DataFrame(
        {
            "Name": ["Staff A", "Staff B"],
            "日付": [1, 2],
            "専属業務": ["調剤室", "監査_AM"],
            "兼務業務": ["", ""],
            "当直": ["当直担当（相方: Staff B）", "当直相方（担当: Staff A）"],
        }
    )
    staff_info = pd.DataFrame(
        {"Name": ["Staff A", "Staff B"], "表示名": ["表示A", "表示B"]},
        index=pd.Index(["Staff A", "Staff B"], name="Name"),
    )

    main.mk_weekly_shift_schedule(shift, 2026, 9, tmp_path, staff_info)

    assert captured_sheets[0].loc["調剤室", "09/01 (火曜日)"] == "表示A ◎"
    assert captured_sheets[0].loc["監査_AM", "09/02 (水曜日)"] == "表示B ◎"