import pandas as pd
import pytest

from create_calender import CalendarCreator, _pivot_staff_day_wide


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


def test_save_results_creates_all_csv_outputs(tmp_path, monkeypatch):
    from types import SimpleNamespace

    monkeypatch.chdir(tmp_path)
    df_result = pd.DataFrame(
        [
            {"Name": "NameB", "日付": 1, "当直": "当直担当（相方: NameA）", "勤務状態": "出勤"},
            {"Name": "NameB", "日付": 2, "当直": "なし", "勤務状態": "非出勤"},
            {"Name": "NameA", "日付": 1, "当直": "当直相方（担当: NameB）", "勤務状態": "未判定"},
            {"Name": "NameA", "日付": 2, "当直": "なし", "勤務状態": "出勤"},
            {"Name": "NameC", "日付": 1, "当直": "なし", "勤務状態": "非出勤"},
            {"Name": "NameC", "日付": 2, "当直": "なし", "勤務状態": "非出勤"},
        ]
    )
    hope_list = pd.DataFrame(
        [
            {"Name": "NameB", "1": "有", "2": "休み"},
            {"Name": "NameA", "1": "学会", "2": "出勤"},
            {"Name": "NameC", "1": "出勤", "2": "休み"},
        ]
    )
    optimizer = SimpleNamespace(
        staff=pd.DataFrame(
            {
                "Floor": [1, 1, 1],
                "Floor2": [None, None, None],
                "Floor3": [None, None, None],
            },
            index=["NameB", "NameA", "NameC"],
        )
    )

    CalendarCreator().save_results(df_result, hope_list, optimizer, 2026, 10)

    output_files = [
        "Shift_2026_10.csv",
        "Shift_wide_2026_10.csv",
        "oncall_shift_long_2026_10.csv",
        "oncall_shift_wide_2026_10.csv",
        "work_status_wide_2026_10.csv",
    ]
    for filename in output_files:
        content = (tmp_path / "result" /"debug" / filename).read_bytes()
        assert content.startswith(b"\xef\xbb\xbf")

    wide = pd.read_csv(tmp_path / "result" / "debug" / "Shift_wide_2026_10.csv")
    assert list(wide.iloc[:, 0]) == ["NameB", "NameA","NameC"]
    assert wide.loc[wide.iloc[:, 0] == "NameB", "1"].iloc[0] == "当直担当（相方: NameA）"

    oncall_long = pd.read_csv(tmp_path / "result" / "debug" / "oncall_shift_long_2026_10.csv")
    name_b_day_one = oncall_long[(oncall_long["Name"] == "NameB") & (oncall_long["日付"] == 1)]
    assert name_b_day_one["希望内容"].iloc[0] == "有"
    assert name_b_day_one["勤務状態"].iloc[0] == "出勤"

    oncall_wide = pd.read_csv(tmp_path / "result" /"debug" / "oncall_shift_wide_2026_10.csv")
    name_b_oncall = oncall_wide[oncall_wide.iloc[:, 0] == "NameB"].iloc[0]
    assert name_b_oncall["1"] == "◎"
    assert name_b_oncall["2"] == "○"
    assert name_b_oncall["当直回数"] == 1
    name_c_oncall = oncall_wide[oncall_wide.iloc[:, 0] == "NameC"].iloc[0]
    assert name_c_oncall["1"] == "指"
    assert name_c_oncall["2"] == "休み"

    work_status_wide = pd.read_csv(tmp_path / "result" / "debug" / "work_status_wide_2026_10.csv")
    name_b_status = work_status_wide[work_status_wide.iloc[:, 0] == "NameB"].iloc[0]
    assert name_b_status["1"] == "◎"
    assert name_b_status["2"] == "○"


@pytest.mark.parametrize(
    ("hope", "work_status", "expected", "periods"),
    [
        ("AM有PM出", "出勤", "AM有PM出", (False, True)),
        ("AM指\nPM出", "出勤", "AM指\nPM出", (False, True)),
        ("PM有", "出勤", "PM有", (True, False)),
        ("AM指", "非出勤", "指", None),
        ("AM指PM有", "出勤", "", None),
        ("AM指PM有", "非出勤", "AM指PM有", (False, False)),
    ],
)
def test_save_results_half_day_marks_match_actual_work_status(
    tmp_path, monkeypatch, hope, work_status, expected, periods
):
    from types import SimpleNamespace
    from optimizer.mode2.shift_optimizer import ShiftOptimizer

    monkeypatch.chdir(tmp_path)
    result = pd.DataFrame([
        {"Name": "A", "日付": 1, "当直": "なし", "勤務状態": work_status}
    ])
    hopes = pd.DataFrame({"Name": ["A"], "1": [hope]})
    optimizer = SimpleNamespace(staff=pd.DataFrame(
        {"Floor": [1], "Floor2": [None], "Floor3": [None]}, index=["A"]
    ))

    CalendarCreator().save_results(result, hopes, optimizer, 2026, 10)

    attendance = pd.read_excel(
        tmp_path / "result" / "work_status_wide_2026_10.xlsx", skiprows=[1]
    ).fillna("").set_index("Name")
    assert attendance.loc["A", 1] == expected

    mode2 = ShiftOptimizer.__new__(ShiftOptimizer)
    mode2.mode1_attendance_list = attendance
    mode2.hope_input = hopes.set_index("Name")
    mode2.hope_day_column_map = {1: "1"}
    if periods is None:
        with pytest.raises(ValueError, match="出勤表.*希望表"):
            mode2.get_period_attendance_status("A", 1, "AM")
    else:
        assert tuple(
            mode2.get_period_attendance_status("A", 1, period)
            for period in ("AM", "PM")
        ) == periods


def test_save_results_oncall_marks_take_priority_over_half_day_hopes(tmp_path, monkeypatch):
    from types import SimpleNamespace

    monkeypatch.chdir(tmp_path)
    result = pd.DataFrame([
        {"Name": "A", "日付": 1, "当直": "当直担当", "勤務状態": "出勤"},
        {"Name": "A", "日付": 2, "当直": "なし", "勤務状態": "非出勤"},
    ])
    hopes = pd.DataFrame({"Name": ["A"], "1": ["AM有PM出"], "2": ["AM指"]})
    optimizer = SimpleNamespace(staff=pd.DataFrame(
        {"Floor": [1], "Floor2": [None], "Floor3": [None]}, index=["A"]
    ))

    CalendarCreator().save_results(result, hopes, optimizer, 2026, 10)

    attendance = pd.read_excel(
        tmp_path / "result" / "work_status_wide_2026_10.xlsx", skiprows=[1]
    ).set_index("Name")
    assert attendance.loc["A", 1] == "AM有PM出◎"
    assert attendance.loc["A", 2] == "○"


@pytest.mark.parametrize(("hope", "time_mark", "oncall", "expected"), [
    ("AM出", "AM出PM出", True, "AM出PM出◎"),
    ("PM出", "AM指", True, "AM指◎"),
    ("AM出", "PM指", False, "PM指"),
])
def test_save_results_preserves_selected_periods_with_oncall(
    tmp_path, monkeypatch, hope, time_mark, oncall, expected
):
    from types import SimpleNamespace
    from optimizer.mode2.shift_optimizer import ShiftOptimizer

    monkeypatch.chdir(tmp_path)
    result = pd.DataFrame([{
        "Name": "A", "日付": 1, "勤務状態": "出勤",
        "当直": "当直担当" if oncall else "なし", "勤務時間": time_mark,
    }])
    hopes = pd.DataFrame({"Name": ["A"], "1": [hope]})
    optimizer = SimpleNamespace(staff=pd.DataFrame(
        {"Floor": [1], "Floor2": [None], "Floor3": [None]}, index=["A"]
    ))
    CalendarCreator().save_results(result, hopes, optimizer, 2026, 10)
    attendance = pd.read_excel(
        tmp_path / "result" / "work_status_wide_2026_10.xlsx", skiprows=[1]
    ).fillna("").set_index("Name")
    assert attendance.loc["A", 1] == expected
    mode2 = ShiftOptimizer.__new__(ShiftOptimizer)
    mode2.mode1_attendance_list = attendance
    mode2.hope_input = hopes.set_index("Name")
    mode2.hope_day_column_map = {1: "1"}
    expected_periods = (True, True) if time_mark == "AM出PM出" else (
        (False, True) if time_mark == "AM指" else (True, False)
    )
    assert tuple(mode2.get_period_attendance_status("A", 1, p) for p in ("AM", "PM")) == expected_periods


@pytest.mark.parametrize("date_headers", [False, True])
def test_save_results_extended_december_keeps_january_hopes_and_counts(
    tmp_path, monkeypatch, date_headers
):
    from types import SimpleNamespace

    monkeypatch.chdir(tmp_path)
    df_result = pd.DataFrame([
        {
            "Name": "NameA",
            "日付": day,
            "当直": "当直担当" if day in (30, 32, 34) else "なし",
            "勤務状態": "出勤" if day in (30, 32, 34) else "非出勤",
        }
        for day in range(1, 35)
    ])
    headers = (
        list(pd.date_range("2026-12-01", periods=34))
        if date_headers else list(range(1, 32)) + ["1.1", "2.1", "3.1"]
    )
    hope_list = pd.DataFrame([["NameA"] + [""] * 31 + ["有", "特", "夏"]],
                             columns=["Name"] + headers)
    optimizer = SimpleNamespace(staff=pd.DataFrame(
        {"Floor": [1], "Floor2": [None], "Floor3": [None]}, index=["NameA"]
    ))

    CalendarCreator().save_results(df_result, hope_list, optimizer, 2026, 12)

    debug_dir = tmp_path / "result" / "debug"
    long = pd.read_csv(debug_dir / "oncall_shift_long_2026_12.csv")
    assert long.set_index("日付").loc[[32, 33, 34], "希望内容"].tolist() == ["有", "特", "夏"]
    wide = pd.read_csv(debug_dir / "oncall_shift_wide_2026_12.csv").iloc[0]
    assert wide["当直回数"] == 1
    assert wide["翌1月当直回数"] == 2
    calendar = pd.read_excel(tmp_path / "result" / "work_status_wide_2026_12.xlsx", header=None)
    assert calendar.iloc[1, 32:35].tolist() == ["金", "土", "日"]


def test_save_results_rejects_missing_january_hope_columns(tmp_path, monkeypatch):
    from types import SimpleNamespace

    monkeypatch.chdir(tmp_path)
    data = pd.DataFrame([{"Name": "A", "日付": 32, "当直": "なし", "勤務状態": "出勤"}])
    hopes = pd.DataFrame({"Name": ["A"], "1": [""]})
    optimizer = SimpleNamespace(staff=pd.DataFrame(index=["A"]))

    with pytest.raises(ValueError, match="32"):
        CalendarCreator().save_results(data, hopes, optimizer, 2026, 12)

    assert not (tmp_path / "result").exists()


def test_save_results_rejects_ambiguous_january_hope_columns(tmp_path, monkeypatch):
    from types import SimpleNamespace

    monkeypatch.chdir(tmp_path)
    data = pd.DataFrame([{"Name": "A", "日付": 32, "当直": "なし", "勤務状態": "出勤"}])
    hopes = pd.DataFrame([["A", "有", "特"]],
                         columns=["Name", "1.1", pd.Timestamp("2027-01-01")])

    with pytest.raises(ValueError, match="重複.*32"):
        CalendarCreator().save_results(data, hopes, SimpleNamespace(), 2026, 12)

    assert not (tmp_path / "result").exists()
