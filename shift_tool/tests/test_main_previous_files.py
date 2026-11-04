from pathlib import Path

import main
import pandas as pd


def test_extract_previous_month_oncall_staff_ids_uses_only_oncall_mark():
    previous_month_shift = pd.DataFrame(
        {
            "Name": ["Staff A", "Staff B", "Staff C（◎のみ）"],
            "-1": ["◎", "○", ""],
            "-2": ["", "◎", "◎"],
            "-9": ["◎", "◎", "◎"],
        }
    )

    assert main._extract_previous_month_oncall_staff_ids(previous_month_shift) == {
        0: ["Staff A"],
        -1: ["Staff B", "Staff C"],
    }


def test_load_previous_month_shift_reads_numeric_excel_day_headers(
    tmp_path, monkeypatch
):
    shift_path = tmp_path / "previous.xlsx"
    pd.DataFrame(
        {
            "blank": [None, None, None],
            "○月": ["指定休：○日", "大木　孝夫", "平野　享"],
            29.0: [None, "◎", "○"],
            30.0: [None, "○", "◎"],
        }
    ).to_excel(shift_path, index=False)
    monkeypatch.setattr(main.tkinter.filedialog, "askopenfilename", lambda **_: str(shift_path))

    loaded = main._load_previous_month_shift()
    cleaned = main._cleaning_previous_month_shift(loaded)

    assert list(cleaned.columns) == ["Name", "-1", "-2"]
    assert main._extract_previous_month_oncall_staff_ids(cleaned) == {
        0: ["平野 享"],
        -1: ["大木 孝夫"],
    }


def test_sum_previous_month_shifts_counts_oncalls_across_files():
    previous_shifts = [
        pd.DataFrame({"Name": ["Staff A", "Staff B"], "1": ["◎", "○"]}),
        pd.DataFrame({"Name": ["Staff A", "Staff B"], "1": ["", "◎"]}),
    ]

    assert main._sum_previous_month_shifts(previous_shifts) == {
        "Staff A": 1,
        "Staff B": 1,
    }


def test_count_previous_months_with_two_oncalls_counts_exact_monthly_totals():
    previous_shifts = [
        pd.DataFrame(
            {
                "Name": ["Staff A", "Staff B", "Staff C", "Staff D", "Staff D"],
                "1": ["◎", "◎", "", "◎", ""],
                "2": ["◎", "", "", "", "◎"],
            }
        ),
        pd.DataFrame(
            {
                "Name": ["Staff A", "Staff B", "Staff D"],
                "1": ["◎", "◎", "◎"],
                "2": ["", "◎", "◎"],
            }
        ),
    ]

    assert main._count_previous_months_with_two_oncalls(previous_shifts) == {
        "Staff A": 1,
        "Staff B": 1,
        "Staff D": 2,
    }


def test_count_previous_months_with_two_oncalls_handles_empty_history():
    assert main._count_previous_months_with_two_oncalls([]) == {}


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


def test_load_previous_january_staff_reads_previous_year_file(tmp_path, monkeypatch):
    result_dir = tmp_path / "result"
    result_dir.mkdir()
    pd.DataFrame(
        {
            "Name": ["Staff A", "Staff B", "Staff C", "Staff D"],
            "1": ["勤務", "休", "有", "勤務"],
        }
    ).to_csv(
        result_dir / "Shift_cleaned_2025_01.csv",
        index=False,
        encoding="utf-8-sig",
    )
    staff_df = pd.DataFrame(
        {
            "Name": ["Staff A", "Staff B", "Staff C", "Staff D"],
            "Floor": ["病棟", "病棟", "病棟", "外来"],
        }
    )
    monkeypatch.chdir(tmp_path)

    assert main._load_previous_january_staff(2026, 1, staff_df) == {"Staff A"}


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


def test_weekly_schedule_shows_palliative_care_am_and_pm_names(tmp_path, monkeypatch):
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
            "兼務業務": ["緩和回診"],
            "当直": ["なし"],
        }
    )
    staff_info = pd.DataFrame(
        {"Name": ["Staff A"], "表示名": ["表示A"]},
        index=pd.Index(["Staff A"], name="Name"),
    )

    main.mk_weekly_shift_schedule(shift, 2026, 9, tmp_path, staff_info)

    weekly_sheet = captured_sheets[0]
    assert weekly_sheet.loc["調剤室", "09/01 (火曜日)"] == "AM表示A"
    assert weekly_sheet.loc["その他", "09/01 (火曜日)"] == "PM表示A"


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