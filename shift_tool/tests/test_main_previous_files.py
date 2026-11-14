from pathlib import Path
from get_previous_data import GetPreviousData
import main
import pandas as pd
import pytest
from create_calender import CalendarCreator

def test_extract_previous_month_oncall_staff_ids_uses_only_oncall_mark():
    previous_month_shift = pd.DataFrame(
        {
            "Name": ["Staff A", "Staff B", "Staff C（◎のみ）"],
            "-1": ["◎", "○", ""],
            "-2": ["", "◎", "◎"],
            "-9": ["◎", "◎", "◎"],
        }
    )

    assert GetPreviousData._extract_previous_month_oncall_staff_ids(previous_month_shift) == {
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
    assert GetPreviousData._extract_previous_month_oncall_staff_ids(cleaned) == {
        0: ["平野 享"],
        -1: ["大木 孝夫"],
    }


def test_sum_previous_month_shifts_counts_oncalls_across_files():
    previous_shifts = [
        pd.DataFrame({"Name": ["Staff A", "Staff B"], "1": ["◎", "○"]}),
        pd.DataFrame({"Name": ["Staff A", "Staff B"], "1": ["", "◎"]}),
    ]

    assert GetPreviousData._sum_previous_month_shifts(previous_shifts) == {
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

    assert GetPreviousData._count_previous_months_with_two_oncalls(previous_shifts) == {
        "Staff A": 1,
        "Staff B": 1,
        "Staff D": 2,
    }


def test_count_previous_months_with_two_oncalls_handles_empty_history():
    assert GetPreviousData._count_previous_months_with_two_oncalls([]) == {}


def test_find_previous_month_file_accepts_legacy_unpadded_month(tmp_path, monkeypatch):
    result_dir = tmp_path / "result"
    result_dir.mkdir()
    legacy_file = result_dir / "Shift_wide_2026_8.csv"
    legacy_file.write_text("Name,1\nNameA,休み\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    assert GetPreviousData._find_previous_month_file("Shift_wide", 2026, 9) == Path(
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

    assert GetPreviousData._find_previous_month_file("Shift_wide", 2026, 9) == Path(
        "result/Shift_wide_2026_08.csv"
    )


def test_load_previous_year_december_30_staff_from_selected_shift(tmp_path, monkeypatch):
    staff_path = tmp_path / "staff.xlsx"
    staff = pd.DataFrame({
        "Name": ["Staff A", "Staff B", "Staff C", "Staff D", "Staff E", "Staff F"],
        "Floor": ["病棟", "病棟", "病棟", "病棟", "外来", "病棟"],
    })
    with pd.ExcelWriter(staff_path) as writer:
        staff.to_excel(writer, sheet_name="member_list", index=False, startrow=1)
    monkeypatch.setattr("tkinter.filedialog.askopenfilename", lambda **_: str(staff_path))
    previous = pd.DataFrame({
        "Name": ["指定休：9日", "Staff A", "Staff B", "Staff C", "Staff D", "Staff E", "Staff F（◎のみ）"],
        30.0: ["", "勤務", "休", "有", None, "◎", "◎"],
    })

    assert GetPreviousData._load_previous_year_december_30_staff(2026, previous) == {
        "StaffA", "StaffD", "StaffF",
    }


def test_load_previous_year_december_30_staff_rejects_missing_day():
    with pytest.raises(ValueError, match="30日列"):
        GetPreviousData._load_previous_year_december_30_staff(
            2026, pd.DataFrame({"Name": ["Staff A"], "29": ["勤務"]})
        )


def test_load_previous_year_december_30_staff_rejects_cancelled_staff_selection(monkeypatch):
    monkeypatch.setattr("tkinter.filedialog.askopenfilename", lambda **_: "")
    with pytest.raises(ValueError, match="選択されませんでした"):
        GetPreviousData._load_previous_year_december_30_staff(
            2026, pd.DataFrame({"Name": ["Staff A"], "30": ["勤務"]})
        )


def test_load_previous_year_december_30_staff_rejects_unknown_name(tmp_path, monkeypatch):
    staff_path = tmp_path / "staff.xlsx"
    with pd.ExcelWriter(staff_path) as writer:
        pd.DataFrame({"Name": ["Staff A"], "Floor": ["病棟"]}).to_excel(
            writer, sheet_name="member_list", index=False, startrow=1
        )
    monkeypatch.setattr("tkinter.filedialog.askopenfilename", lambda **_: str(staff_path))
    with pytest.raises(ValueError, match="StaffB"):
        GetPreviousData._load_previous_year_december_30_staff(
            2026, pd.DataFrame({"Name": ["Staff B"], "30": ["勤務"]})
        )


@pytest.mark.parametrize("floor", ["外来", 9, 9.0])
def test_load_previous_year_december_30_staff_excludes_outpatient_floor(tmp_path, monkeypatch, floor):
    staff_path = tmp_path / "staff.xlsx"
    with pd.ExcelWriter(staff_path) as writer:
        pd.DataFrame({"Name": ["Staff A"], "Floor": [floor]}).to_excel(
            writer, sheet_name="member_list", index=False, startrow=1
        )
    monkeypatch.setattr("tkinter.filedialog.askopenfilename", lambda **_: str(staff_path))
    assert GetPreviousData._load_previous_year_december_30_staff(
        2026, pd.DataFrame({"Name": ["Staff A"], "30": [None]})
    ) == set()


@pytest.mark.parametrize(("mark", "worked"), [
    ("", True), ("◎", True), ("○", True), ("調剤室", True),
    ("指", False), ("産", False), ("研", False), ("学会", False), (0, False),
])
def test_load_previous_year_december_30_staff_classifies_marks(tmp_path, monkeypatch, mark, worked):
    staff_path = tmp_path / "staff.xlsx"
    with pd.ExcelWriter(staff_path) as writer:
        pd.DataFrame({"Name": ["Staff A"], "Floor": ["病棟"]}).to_excel(
            writer, sheet_name="member_list", index=False, startrow=1
        )
    monkeypatch.setattr("tkinter.filedialog.askopenfilename", lambda **_: str(staff_path))
    result = GetPreviousData._load_previous_year_december_30_staff(
        2026, pd.DataFrame({"Name": ["Staff A"], "30": [mark]})
    )
    assert ("StaffA" in result) is worked


@pytest.mark.parametrize(("month", "days"), [(12, (30, 31)), (1, (1, 2, 3))])
def test_previous_year_worked_staff_uses_one_selected_shift_and_conditions(tmp_path, monkeypatch, month, days):
    staff_path = tmp_path / "staff.xlsx"
    shift_path = tmp_path / "shift.xlsx"
    staff = pd.DataFrame({"Name": ["Staff A", "Staff B", "Staff C", "Staff D"],
                          "Floor": ["病棟", "病棟", "外来", "病棟"]})
    with pd.ExcelWriter(staff_path) as writer:
        staff.to_excel(writer, sheet_name="member_list", index=False, startrow=1)
    shift = pd.DataFrame({
        "空": [None] * 4, "名前": staff["Name"],
        days[0]: [None, "指", "◎", "研"],
        days[1]: ["指", "◎", None, "○"],
        **({days[2]: ["学会", "有", "出", "出"]} if len(days) == 3 else {}),
    })
    shift.to_excel(shift_path, index=False)
    selections = iter([str(shift_path), str(staff_path)])
    monkeypatch.setattr("tkinter.filedialog.askopenfilename", lambda **_: next(selections))

    frame = GetPreviousData._load_previous_year_end_shift(2027, month)
    result = GetPreviousData._load_previous_year_worked_staff(2027, month, frame, days)
    assert result[days[0]] == {"StaffA"}
    assert result[days[1]] == {"StaffB", "StaffD"}
    if month == 1:
        assert result[3] == {"StaffD"}


@pytest.mark.parametrize(("month", "days", "missing"), [
    (12, (30, 31), 31), (1, (1, 2, 3), 2), (1, (1, 2, 3), 3),
])
def test_previous_year_worked_staff_rejects_missing_day(month, days, missing):
    frame = pd.DataFrame({"Name": ["Staff A"], **{str(day): ["出"] for day in days if day != missing}})
    with pytest.raises(ValueError, match=f"{missing}日列"):
        GetPreviousData._load_previous_year_worked_staff(2027, month, frame, days)


def test_previous_year_end_shift_rejects_cancel(monkeypatch):
    monkeypatch.setattr("tkinter.filedialog.askopenfilename", lambda **_: "")
    with pytest.raises(ValueError, match="選択されませんでした"):
        GetPreviousData._load_previous_year_end_shift(2027, 1)


@pytest.mark.parametrize("month", [1, 12])
def test_previous_year_end_shift_dialog_identifies_previous_year(month, monkeypatch):
    dialogs = []

    def cancel(**kwargs):
        dialogs.append(kwargs["title"])
        return ""

    monkeypatch.setattr("tkinter.filedialog.askopenfilename", cancel)
    with pytest.raises(ValueError):
        GetPreviousData._load_previous_year_end_shift(2027, month)
    assert f"2026年{month}月" in dialogs[0]


def test_previous_year_worked_staff_rejects_duplicate_day(monkeypatch):
    frame = pd.DataFrame([["Staff A", "出", "休"]], columns=["Name", "31", "31"])
    with pytest.raises(ValueError, match="31日列"):
        GetPreviousData._load_previous_year_worked_staff(2027, 12, frame, (31,))


def test_load_december_carryover_reads_work_and_oncall_assignments(tmp_path, monkeypatch):
    debug_dir = tmp_path / "result" / "debug"
    debug_dir.mkdir(parents=True)
    rows = []
    for day in (32, 33, 34):
        rows.extend([
            {
                "Name": "StaffA", "日付": day, "勤務状態": "出勤",
                "当直": "当直担当（相方: StaffB）",
            },
            {
                "Name": "StaffB", "日付": day, "勤務状態": "出勤",
                "当直": "当直相方（担当: StaffA）",
            },
            {"Name": "StaffC", "日付": day, "勤務状態": "非出勤", "当直": "なし"},
        ])
    pd.DataFrame(rows).to_csv(
        debug_dir / "Shift_2026_12.csv", index=False, encoding="utf-8-sig"
    )
    monkeypatch.chdir(tmp_path)

    carryover = GetPreviousData._load_december_carryover(
        2027, ["StaffA", "StaffB", "StaffC"]
    )

    assert carryover == {
        "attendance": {
            ("StaffA", 1): True, ("StaffB", 1): True, ("StaffC", 1): False,
            ("StaffA", 2): True, ("StaffB", 2): True, ("StaffC", 2): False,
            ("StaffA", 3): True, ("StaffB", 3): True, ("StaffC", 3): False,
        },
        "oncall_pairs": {
            1: ("StaffA", "StaffB"),
            2: ("StaffA", "StaffB"),
            3: ("StaffA", "StaffB"),
        },
    }


def test_load_december_carryover_rejects_missing_january_day(tmp_path, monkeypatch):
    debug_dir = tmp_path / "result" / "debug"
    debug_dir.mkdir(parents=True)
    rows = [
        {"Name": "StaffA", "日付": day, "勤務状態": "出勤", "当直": "なし"}
        for day in (32, 33)
    ]
    pd.DataFrame(rows).to_csv(debug_dir / "Shift_2026_12.csv", index=False)
    monkeypatch.chdir(tmp_path)

    with pytest.raises(ValueError, match="1月1〜3日"):
        GetPreviousData._load_december_carryover(2027, ["StaffA"])


def test_load_december_carryover_rejects_ambiguous_oncall_role(tmp_path, monkeypatch):
    debug_dir = tmp_path / "result" / "debug"
    debug_dir.mkdir(parents=True)
    rows = []
    for day in (32, 33, 34):
        rows.extend([
            {
                "Name": "StaffA", "日付": day, "勤務状態": "出勤",
                "当直": "当直担当（相方: StaffB）",
            },
            {
                "Name": "StaffB", "日付": day, "勤務状態": "出勤",
                "当直": "当直担当（相方: StaffA）",
            },
        ])
    pd.DataFrame(rows).to_csv(debug_dir / "Shift_2026_12.csv", index=False)
    monkeypatch.chdir(tmp_path)

    with pytest.raises(ValueError, match="役割が不正"):
        GetPreviousData._load_december_carryover(2027, ["StaffA", "StaffB"])


def test_load_december_carryover_requires_previous_december_result(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    with pytest.raises(ValueError, match="見つかりません"):
        GetPreviousData._load_december_carryover(2027, ["StaffA"])


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

    CalendarCreator.mk_weekly_shift_schedule(shift, 2026, 9, tmp_path, staff_info)

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

    CalendarCreator.mk_weekly_shift_schedule(shift, 2026, 9, tmp_path, staff_info)

    weekly_sheet = captured_sheets[0]
    assert weekly_sheet.loc["調剤室", "09/01 (火曜日)"] == "AM表示A"
    assert weekly_sheet.loc["その他", "09/01 (火曜日)"] == "緩和回診:\nPM表示A"


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

    CalendarCreator.mk_weekly_shift_schedule(shift, 2026, 9, tmp_path, staff_info)

    assert captured_sheets[0].loc["調剤室", "09/01 (火曜日)"] == "表示A ◎"
    assert captured_sheets[0].loc["監査_AM", "09/02 (水曜日)"] == "表示B ◎"