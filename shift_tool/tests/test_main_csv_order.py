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
