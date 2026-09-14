from pathlib import Path

import main


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