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