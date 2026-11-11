from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest
from ortools.sat.python import cp_model

from get_previous_data import GetPreviousData
from optimizer.mode1.mode1 import Mode1Optimizer
from optimizer.mode1.night_shift.oncall_constraints import OncallConstraints


def _inputs(monkeypatch, *values):
    answers = iter(values)
    monkeypatch.setattr("builtins.input", lambda _: next(answers))


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("Shift_cleaned_2026_08.xlsx", (2026, 8)),
        ("Shift_2026-8 copy.xlsx", (2026, 8)),
        ("当直2026年8月.xlsx", (2026, 8)),
    ],
)
def test_history_filename_year_month(name, expected):
    assert GetPreviousData._history_file_year_month(Path(name)) == expected


def test_unknown_year_month_prompts_and_retries(monkeypatch):
    _inputs(monkeypatch, "2026-13", "2026-09")
    assert GetPreviousData._history_file_year_month(Path("9月.xlsx")) == (2026, 9)


def test_duplicate_month_including_manually_entered_month_selects_one(monkeypatch):
    files = [Path("2026_09.xlsx"), Path("9月.xlsx"), Path("2026_10.xlsx")]
    _inputs(monkeypatch, "2026-09", "3", "2")
    assert GetPreviousData._select_previous_month_history_files(files) == [
        Path("9月.xlsx"), Path("2026_10.xlsx")
    ]


@pytest.mark.parametrize("answers", [("0",), ("2026-09", "0")])
def test_history_selection_can_be_cancelled(monkeypatch, answers):
    _inputs(monkeypatch, *answers)
    assert GetPreviousData._select_previous_month_history_files(
        [Path("9月.xlsx"), Path("2026_09.xlsx")]
    ) is None


@pytest.mark.parametrize(("answer", "expected"), [("y", []), ("n", None)])
def test_empty_history_requires_confirmation(tmp_path, monkeypatch, answer, expected):
    monkeypatch.setattr(
        GetPreviousData, "_load_previous_month_shifts_files_path", lambda: str(tmp_path)
    )
    _inputs(monkeypatch, "invalid", answer)
    assert GetPreviousData._load_previous_month_shifts_files() == expected


@pytest.mark.parametrize("answer", ["y", "n"])
def test_failed_history_requires_confirmation(tmp_path, monkeypatch, answer):
    good = tmp_path / "2026_08.xlsx"
    bad = tmp_path / "2026_09.xlsx"
    pd.DataFrame(
        {"blank": [None], "8月": ["Staff A"], 1: ["◎"], "備考": ["◎"]}
    ).to_excel(good, index=False)
    bad.write_text("not an Excel file")
    _inputs(monkeypatch, answer)

    shifts = GetPreviousData._read_previous_month_shifts_files([good, bad])

    if answer == "n":
        assert shifts is None
    else:
        assert len(shifts) == 1
        assert GetPreviousData._sum_previous_month_shifts(shifts) == {"StaffA": 1}
        assert GetPreviousData._count_previous_months_with_two_oncalls(shifts) == {}


def test_history_without_day_columns_is_reported(tmp_path, monkeypatch, capsys):
    path = tmp_path / "2026_08.xlsx"
    pd.DataFrame({"blank": [None], "8月": ["Staff A"], "備考": ["◎"]}).to_excel(
        path, index=False
    )
    _inputs(monkeypatch, "n")
    assert GetPreviousData._read_previous_month_shifts_files([path]) is None
    assert "日付列" in capsys.readouterr().out


def test_selected_history_is_counted_once_per_month(tmp_path, monkeypatch):
    for filename, marks in [
        ("2026_08.xlsx", ["◎", "◎"]),
        ("2026_08 copy.xlsx", ["◎", ""]),
        ("9月.xlsx", ["", "◎"]),
    ]:
        pd.DataFrame(
            {"blank": [None], "月": ["Staff A"], 1: marks[:1], 2: marks[1:]}
        ).to_excel(tmp_path / filename, index=False)
    monkeypatch.setattr(
        GetPreviousData, "_load_previous_month_shifts_files_path", lambda: str(tmp_path)
    )
    _inputs(monkeypatch, "2026-09", "2")

    files = GetPreviousData._load_previous_month_shifts_files()
    shifts = GetPreviousData._read_previous_month_shifts_files(files)

    assert len(files) == 2
    assert GetPreviousData._sum_previous_month_shifts(shifts) == {"StaffA": 3}
    assert GetPreviousData._count_previous_months_with_two_oncalls(shifts) == {"StaffA": 1}


@pytest.mark.parametrize("files", [None, []])
def test_mode1_stops_when_history_selection_or_loading_is_cancelled(monkeypatch, files):
    _inputs(monkeypatch, "2026", "10", "9")
    monkeypatch.setattr("tkinter.filedialog.askopenfilename", lambda **_: "staff.xlsx")
    monkeypatch.setattr(GetPreviousData, "_load_previous_month_shift", lambda: None)
    monkeypatch.setattr(GetPreviousData, "_cleaning_previous_month_shift", lambda _: None)
    monkeypatch.setattr(
        GetPreviousData, "_extract_previous_month_oncall_staff_ids", lambda _: {}
    )
    monkeypatch.setattr(
        GetPreviousData, "_load_previous_month_oncall_staff_ids", lambda **_: {}
    )
    monkeypatch.setattr(GetPreviousData, "_load_previous_month_shifts_files", lambda: files)
    monkeypatch.setattr(
        GetPreviousData, "_read_previous_month_shifts_files", lambda _: None
    )

    assert Mode1Optimizer.mode1_initial_shift() == 1


def test_fairness_excludes_outpatient_qualification_senior_and_ineligible():
    constraint = OncallConstraints.__new__(OncallConstraints)
    constraint.model = cp_model.CpModel()
    names = ["A", "B", "Outpatient", "Senior", "Ineligible"]
    constraint.staff = pd.DataFrame(
        {"主任以上": [False, False, False, True, False],
         "当直": [True, True, True, True, False]},
        index=names,
    )
    constraint.get_eligible_sections = {name: [] for name in names}
    constraint.get_eligible_sections["Outpatient"] = [16]
    constraint.monthly_oncall_counts = {
        name: constraint.model.NewIntVar(0, 2, f"monthly_{name}") for name in names
    }
    constraint.optimizer = SimpleNamespace(
        previous_month_oncall_counts={name: 1 for name in names if name != "B"},
        previous_oncall_counts={
            "A": 1, "B": 4, "Outpatient": 99, "Senior": 99, "Ineligible": 99,
        },
    )

    month_penalties = constraint.add_oncall_prev_month_balance_penalties()
    fairness_penalties = constraint.add_oncall_fairness_penalties()
    for count in constraint.monthly_oncall_counts.values():
        constraint.model.Add(count == 1)
    constraint.model.Minimize(sum(month_penalties) + sum(fairness_penalties))
    solver = cp_model.CpSolver()

    assert solver.Solve(constraint.model) == cp_model.OPTIMAL
    assert len(month_penalties) == 1
    assert solver.Value(month_penalties[0]) == 1
    assert len(fairness_penalties) == 1
    assert solver.Value(fairness_penalties[0]) == 3
