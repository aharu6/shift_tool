from datetime import date
from types import SimpleNamespace

import pandas as pd
import pytest
from ortools.sat.python import cp_model

from create_calender import CalendarCreator
from optimizer.method.staff_name_matching import normalize_name_index
from optimizer.mode2.concurrent_shift.concurrent_constraints import ConcurrentConstraints
from optimizer.mode2.concurrent_shift.meeting_constraints import MeetingConstraints
from optimizer.mode2.primary_shift.weekly_placement_optimizer import WeeklyPlacementOptimizer
from optimizer.mode2.shift_optimizer import ShiftOptimizer
from optimizer.mode2.mode2 import Mode2Optimizer


def _concurrent_constraint(days=26):
    constraint = ConcurrentConstraints.__new__(ConcurrentConstraints)
    constraint.model = cp_model.CpModel()
    constraint.staff = pd.DataFrame(index=["A", "B", "C"])
    constraint.days, constraint.year, constraint.month = days, 2026, 6
    constraint.holiday_dates = {date(2026, 6, 3)}
    constraint.get_eligible_sections = {
        "A": [18, 19, 24, 27],
        "B": [18, 19, 24, 27],
        "C": [],
    }
    constraint.hope_list = pd.DataFrame(7, index=constraint.staff.index, columns=range(1, days + 1))
    constraint.hope_list.loc["B", 1] = 10
    constraint.hope_day_column_map = {day: day for day in range(1, days + 1)}
    constraint.debug_enabled = False
    constraint.optimizer = SimpleNamespace(
        get_attendance_status=lambda staff, day: not (staff == "B" and day == 26)
    )
    constraint.concurrent_shifts = {
        (staff, day, section): constraint.model.NewBoolVar(f"{staff}_{day}_{section}")
        for staff in constraint.staff.index
        for day in range(1, days + 1)
        for section in (1, 2, 8, 15)
    }
    return constraint


def test_mode2_concurrent_days_eligibility_and_objective():
    constraint = _concurrent_constraint()
    penalties = constraint.add_mode2_safety_wg()
    constraint.add_mode2_heart_team()
    constraint.add_mode2_nst()
    penalties += constraint.add_mode2_infection_control()
    constraint.model.Minimize(sum(penalties))
    solver = cp_model.CpSolver()
    assert solver.Solve(constraint.model) == cp_model.OPTIMAL
    shifts = constraint.concurrent_shifts
    assert solver.Value(shifts["A", 26, 8]) == 1
    assert solver.Value(shifts["B", 26, 8]) == 0
    assert solver.Value(shifts["A", 19, 8]) == 0
    assert sum(solver.Value(shifts[name, 2, 1]) for name in ("A", "B", "C")) == 1
    assert sum(solver.Value(shifts[name, 4, 2]) for name in ("A", "B", "C")) == 1
    assert solver.Value(shifts["B", 1, 15]) == 1
    assert solver.Value(shifts["A", 1, 15]) == 0
    for name in ("A", "B", "C"):
        assert solver.Value(shifts[name, 3, 15]) == 0
        assert solver.Value(shifts[name, 3, 2]) == 0


def test_extended_december_manager_meeting_restarts_week_count_in_january():
    constraint = MeetingConstraints.__new__(MeetingConstraints)
    constraint.model = cp_model.CpModel()
    constraint.year, constraint.month, constraint.days = 2028, 12, 34
    constraint.staff = pd.DataFrame(
        {"主任以上": [True], "Floor": [1], "Floor2": [None], "Floor3": [None]},
        index=["A"],
    )
    constraint.holiday_dates = set()
    constraint.hope_list = pd.DataFrame(7, index=["A"], columns=range(1, 35))
    constraint.hope_day_column_map = {day: day for day in range(1, 35)}
    constraint.debug_enabled = False
    shifts = {
        day: constraint.model.NewBoolVar(f"meeting_{day}")
        for day in range(1, 35)
    }
    constraint.optimizer = SimpleNamespace(
        get_attendance_status=lambda staff, day: True,
        get_concurrent_assignment_var=lambda staff, day, section: shifts[day],
    )
    constraint._meeting_candidates = set()

    penalties = constraint.fixed_manager_meeting()

    assert constraint._meeting_candidates == {("A", day, 6) for day in (4, 18, 32)}
    assert len(penalties) == 3


def test_extended_december_meeting_dates_and_porifa_candidates():
    constraint = MeetingConstraints.__new__(MeetingConstraints)
    constraint.model = cp_model.CpModel()
    constraint.year, constraint.month, constraint.days = 2026, 12, 34
    constraint.staff = pd.DataFrame(columns=["主任以上"])
    constraint.holiday_dates = set()
    constraint._get_porifa_staff_ids = lambda day: ["A"]
    constraint._porifa_members_have_no_day_off_request = lambda staff, day: True

    assert set(constraint._collect_available_porifa_weeks(4)) == {1, 2, 3, 4}
    assert constraint.second_friday_conference() == []
    assert constraint.fixed_medical_safety_working_group() == []
    assert constraint.general_meeting() == []
    assert constraint.yakushin() == []


def test_extended_december_monthly_meetings_do_not_count_january_as_december():
    constraint = MeetingConstraints.__new__(MeetingConstraints)
    constraint.model = cp_model.CpModel()
    constraint.year, constraint.month, constraint.days = 2026, 12, 34
    constraint.staff = pd.DataFrame(
        {"主任以上": [True], "Floor": [13], "Floor2": [2], "Floor3": [None]},
        index=["A"],
    )
    constraint.get_eligible_sections = {"A": [25]}
    constraint.hope_list = pd.DataFrame(7, index=["A"], columns=range(1, 35))
    constraint.hope_day_column_map = {day: day for day in range(1, 35)}
    constraint.debug_enabled = False
    constraint._meeting_candidates = set()
    shifts = {
        (day, section): constraint.model.NewBoolVar(f"meeting_{day}_{section}")
        for day in range(1, 35) for section in (7, 9, 17)
    }
    constraint.optimizer = SimpleNamespace(
        get_attendance_status=lambda staff, day: True,
        get_concurrent_assignment_var=lambda staff, day, section: shifts[day, section],
    )

    constraint.second_friday_conference()
    constraint.fixed_medical_safety_working_group()
    constraint.general_meeting()
    constraint.yakushin()

    assert constraint._meeting_candidates == {
        ("A", 3, 9), ("A", 11, 7), ("A", 18, 7), ("A", 25, 17)
    }


def test_heart_team_assignment_is_required_when_candidates_exist():
    constraint = _concurrent_constraint(days=2)
    constraint.add_mode2_heart_team()
    for name in ("A", "B"):
        constraint.model.Add(constraint.concurrent_shifts[name, 2, 1] == 0)
    assert cp_model.CpSolver().Solve(constraint.model) == cp_model.INFEASIBLE


def test_ict_is_soft_and_only_on_eligible_tuesday_afternoon():
    constraint = _concurrent_constraint(days=4)
    constraint.staff["ICT"] = [True, True, False]
    constraint.concurrent_shifts.update({
        (staff, day, 3): constraint.model.NewBoolVar(f"ict_{staff}_{day}")
        for staff in constraint.staff.index for day in range(1, 5)
        if (staff, day, 3) not in constraint.concurrent_shifts
    })
    terms = []
    constraint.optimizer.register_objective_term = lambda name, term: terms.append(term)
    constraint.add_mode2_ict()
    constraint.model.Add(constraint.concurrent_shifts["A", 2, 3] == 0)
    constraint.model.Minimize(sum(terms))
    solver = cp_model.CpSolver()
    assert solver.Solve(constraint.model) == cp_model.OPTIMAL
    assert solver.Value(constraint.concurrent_shifts["B", 2, 3]) == 1
    assert solver.Value(constraint.concurrent_shifts["C", 2, 3]) == 0
    assert solver.Value(constraint.concurrent_shifts["B", 1, 3]) == 0
    assert solver.ObjectiveValue() == 10


def test_ict_candidates_exclude_unavailable_staff():
    constraint = _concurrent_constraint(days=2)
    constraint.staff["ICT"] = [True, True, True]
    constraint.staff["休職"] = [False, False, True]
    constraint.hope_list.loc["B", 2] = 9
    assert constraint._mode2_ict_available_staff(1) == []
    assert constraint._mode2_ict_available_staff(2) == ["A"]


def test_saturday_chemo_uses_dispensing_and_requires_at_least_one():
    constraint = _concurrent_constraint(days=6)
    constraint.get_eligible_sections["A"] = [1, 9]
    constraint.get_eligible_sections["B"] = [1, 9]
    constraint.get_eligible_sections["C"] = [9]
    constraint.shifts = {
        (staff, day, 1): constraint.model.NewBoolVar(f"dispensing_{staff}_{day}")
        for staff in constraint.staff.index for day in range(1, 7)
    }
    constraint.concurrent_shifts.update({
        (staff, day, 11): constraint.model.NewBoolVar(f"chemo_{staff}_{day}")
        for staff in constraint.staff.index for day in range(1, 7)
    })
    terms = []
    constraint.optimizer.register_objective_term = lambda name, term: terms.append(term)
    constraint.add_mode2_saturday_chemo()
    constraint.model.Minimize(sum(terms))
    solver = cp_model.CpSolver()
    assert solver.Solve(constraint.model) == cp_model.OPTIMAL
    for staff in ("A", "B"):
        assert solver.Value(constraint.concurrent_shifts[staff, 6, 11]) == 1
        assert solver.Value(constraint.shifts[staff, 6, 1]) == 1
    assert solver.Value(constraint.concurrent_shifts["C", 6, 11]) == 0
    constraint.model.Add(constraint.concurrent_shifts["A", 6, 11] == 0)
    constraint.model.Add(constraint.concurrent_shifts["B", 6, 11] == 0)
    assert cp_model.CpSolver().Solve(constraint.model) == cp_model.INFEASIBLE


def test_saturday_chemo_with_one_or_no_candidates():
    for candidate_count, expected in ((1, cp_model.OPTIMAL), (0, cp_model.INFEASIBLE)):
        constraint = _concurrent_constraint(days=6)
        constraint.get_eligible_sections = {
            "A": [1, 9] if candidate_count else [],
            "B": [],
            "C": [],
        }
        constraint.shifts = {
            (staff, day, 1): constraint.model.NewBoolVar(f"dispensing_{staff}_{day}")
            for staff in constraint.staff.index for day in range(1, 7)
        }
        constraint.concurrent_shifts.update({
            (staff, day, 11): constraint.model.NewBoolVar(f"chemo_{staff}_{day}")
            for staff in constraint.staff.index for day in range(1, 7)
        })
        terms = []
        constraint.optimizer.register_objective_term = lambda name, term: terms.append(term)
        constraint.add_mode2_saturday_chemo()
        constraint.model.Minimize(sum(terms))
        solver = cp_model.CpSolver()
        assert solver.Solve(constraint.model) == expected
        if candidate_count:
            assert solver.Value(constraint.concurrent_shifts["A", 6, 11]) == 1
            assert solver.ObjectiveValue() == 10000


def test_general_meeting_includes_morning_only_hope():
    constraint = MeetingConstraints.__new__(MeetingConstraints)
    fixture = _concurrent_constraint(days=26)
    constraint.model = fixture.model
    constraint.staff = fixture.staff
    constraint.days, constraint.year, constraint.month = 26, 2026, 6
    constraint.debug_enabled = False
    constraint.hope_list = fixture.hope_list
    constraint.hope_day_column_map = fixture.hope_day_column_map
    constraint.hope_list.loc["A", 26] = 9
    assignments = {
        staff: constraint.model.NewBoolVar(f"meeting_{staff}")
        for staff in constraint.staff.index
    }
    constraint.optimizer = SimpleNamespace(
        get_attendance_status=lambda staff, day: staff != "B",
        get_concurrent_assignment_var=lambda staff, day, section: assignments[staff],
    )
    constraint.general_meeting()
    solver = cp_model.CpSolver()
    assert solver.Solve(constraint.model) == cp_model.OPTIMAL
    assert [solver.Value(assignments[staff]) for staff in ("A", "B", "C")] == [1, 0, 1]


def test_master_request_rejects_invalid_input_and_accepts_multiple(monkeypatch):
    optimizer = SimpleNamespace(
        days=30,
        staff=pd.DataFrame(index=["A", "B"]),
        get_attendance_status=lambda staff, day: day != 5,
        concurrent_constraints=SimpleNamespace(
            get_eligible_sections={"A": [21], "B": []},
            _get_hope_value=lambda staff, day, default: 7,
            _hope_matches=lambda value, targets: value in targets,
        ),
    )
    responses = iter(["B", "A", "5", "AM", "A", "6", "AM", "A", "7", "PM", ""])
    monkeypatch.setattr("builtins.input", lambda prompt: next(responses))
    assert Mode2Optimizer._read_master_requests(optimizer) == {
        ("A", 6, "AM"), ("A", 7, "PM")
    }


def test_master_request_full_name_with_spaces_matches_staff_file(monkeypatch, capsys):
    staff = normalize_name_index(
        pd.DataFrame({"Name": ["山田　太郎"]}), source_label="staff"
    )
    optimizer = SimpleNamespace(
        days=30,
        staff=staff,
        get_attendance_status=lambda staff, day: True,
        concurrent_constraints=SimpleNamespace(
            get_eligible_sections={"山田太郎": [21]},
            _get_hope_value=lambda staff, day, default: 7,
            _hope_matches=lambda value, targets: value in targets,
        ),
    )
    responses = iter([" 山田 太郎 ", "6", "AM", "山田　太郎", "7", "PM", ""])
    prompts = []

    def read_input(prompt):
        prompts.append(prompt)
        return next(responses)

    monkeypatch.setattr("builtins.input", read_input)
    assert Mode2Optimizer._read_master_requests(optimizer) == {
        ("山田太郎", 6, "AM"), ("山田太郎", 7, "PM")
    }
    assert "フルネーム" in capsys.readouterr().out
    assert "フルネーム" in prompts[0]


def test_known_simultaneous_duties_are_incompatible():
    optimizer = ShiftOptimizer.__new__(ShiftOptimizer)
    optimizer.model = cp_model.CpModel()
    optimizer.staff = pd.DataFrame(index=["A"])
    optimizer.days, optimizer.year, optimizer.month = 1, 2026, 6
    optimizer.concurrent_shifts = {
        ("A", 1, section): optimizer.model.NewBoolVar(f"duty_{section}")
        for section in (1, 2, 3, 4, 5, 8, 9, 12, 13, 14, 15)
    }
    optimizer.master_shifts = {
        ("A", 1, period): optimizer.model.NewBoolVar(f"master_{period}")
        for period in ("AM", "PM")
    }
    optimizer.add_concurrent_time_conflicts()
    optimizer.model.Add(optimizer.concurrent_shifts["A", 1, 4] == 1)
    optimizer.model.Add(optimizer.concurrent_shifts["A", 1, 5] == 1)
    assert cp_model.CpSolver().Solve(optimizer.model) == cp_model.INFEASIBLE


def test_mode2_attendance_reads_extended_december_work_status_values():
    optimizer = ShiftOptimizer.__new__(ShiftOptimizer)
    optimizer.mode1_attendance_list = pd.DataFrame(
        [[*([0] * 31), 1, 0, "◎"]],
        index=["A"],
        columns=range(1, 35),
    )

    assert optimizer.get_attendance_status("A", 32)
    assert not optimizer.get_attendance_status("A", 33)
    assert optimizer.get_attendance_status("A", 34)


def test_saturday_chemo_allows_master_pm_but_not_am():
    def build(period):
        optimizer = ShiftOptimizer.__new__(ShiftOptimizer)
        optimizer.model = cp_model.CpModel()
        optimizer.staff = pd.DataFrame(index=["A"])
        optimizer.days, optimizer.year, optimizer.month = 6, 2026, 6
        optimizer.concurrent_shifts = {
            ("A", day, section): optimizer.model.NewBoolVar(f"duty_{day}_{section}")
            for day in range(1, 7) for section in range(1, 18)
        }
        optimizer.master_shifts = {
            ("A", day, p): optimizer.model.NewBoolVar(f"master_{day}_{p}")
            for day in range(1, 7) for p in ("AM", "PM")
        }
        optimizer.shifts = {
            ("A", day, 3): optimizer.model.NewBoolVar(f"admission_{day}")
            for day in range(1, 7)
        }
        optimizer.add_concurrent_time_conflicts()
        optimizer.model.Add(optimizer.concurrent_shifts["A", 6, 11] == 1)
        optimizer.model.Add(optimizer.master_shifts["A", 6, period] == 1)
        return optimizer.model

    assert cp_model.CpSolver().Solve(build("AM")) == cp_model.INFEASIBLE
    assert cp_model.CpSolver().Solve(build("PM")) == cp_model.OPTIMAL


def test_extended_december_time_conflicts_use_actual_january_weekday():
    def build(master_period):
        optimizer = ShiftOptimizer.__new__(ShiftOptimizer)
        optimizer.model = cp_model.CpModel()
        optimizer.staff = pd.DataFrame(index=["A"])
        optimizer.days, optimizer.year, optimizer.month = 34, 2026, 12
        optimizer.concurrent_shifts = {
            ("A", day, section): optimizer.model.NewBoolVar(f"duty_{day}_{section}")
            for day in range(1, 35) for section in range(1, 18)
        }
        optimizer.master_shifts = {
            ("A", day, period): optimizer.model.NewBoolVar(f"master_{day}_{period}")
            for day in range(1, 35) for period in ("AM", "PM")
        }
        optimizer.shifts = {
            ("A", day, 3): optimizer.model.NewBoolVar(f"admission_{day}")
            for day in range(1, 35)
        }
        optimizer.add_concurrent_time_conflicts()
        optimizer.model.Add(optimizer.concurrent_shifts["A", 33, 11] == 1)
        optimizer.model.Add(optimizer.master_shifts["A", 33, master_period] == 1)
        return optimizer.model

    assert cp_model.CpSolver().Solve(build("AM")) == cp_model.INFEASIBLE
    assert cp_model.CpSolver().Solve(build("PM")) == cp_model.OPTIMAL


def test_extended_december_porifa_selection_stays_within_december():
    optimizer = ShiftOptimizer.__new__(ShiftOptimizer)
    optimizer.days, optimizer.year, optimizer.month = 34, 2026, 12
    optimizer.staff = pd.DataFrame({"ポリファーマシーチーム": [True]}, index=["A"])
    optimizer.mode1_attendance_list = pd.DataFrame(
        "", index=["A"], columns=range(1, 35)
    )
    optimizer.holidays = []

    assert optimizer._select_porifa_days() == (4, 8)

    optimizer.mode1_attendance_list.loc["A", [4, 11, 18]] = "休み"
    assert optimizer._select_porifa_days() == (25, 29)

    optimizer.mode1_attendance_list.loc["A", 25] = "休み"
    with pytest.raises(ValueError, match="候補日が存在しません"):
        optimizer._select_porifa_days()


def test_dispensing_counts_overlapping_pm_duties_once():
    constraint = WeeklyPlacementOptimizer.__new__(WeeklyPlacementOptimizer)
    constraint.model = cp_model.CpModel()
    constraint.staff = pd.DataFrame({"必須メンバー": [False]}, index=["A"])
    constraint.days, constraint.year, constraint.month = 1, 2026, 6
    constraint.holiday_dates = set()
    constraint.hope_list = pd.DataFrame()
    constraint.hope_day_column_map = {}
    constraint.debug_enabled = False
    constraint.eligible_sections = {"A": [1]}
    terms = []
    constraint.optimizer = SimpleNamespace(
        register_objective_term=lambda name, term: terms.append(term),
        master_shifts={
            ("A", 1, period): constraint.model.NewBoolVar(f"master_{period}")
            for period in ("AM", "PM")
        },
    )
    for var in constraint.optimizer.master_shifts.values():
        constraint.model.Add(var == 0)
    constraint.shifts = {
        ("A", 1, section): constraint.model.NewBoolVar(f"primary_{section}")
        for section in (1, 3, 4, 5, 6, 7, 8, 9)
    }
    constraint.concurrent_shifts = {
        ("A", 1, section): constraint.model.NewBoolVar(f"concurrent_{section}")
        for section in (1, 2, 3, 4, 5, 8, 9, 10, 12, 15)
    }
    for (_, _, section), var in constraint.shifts.items():
        constraint.model.Add(var == int(section == 1))
    for (_, _, section), var in constraint.concurrent_shifts.items():
        constraint.model.Add(var == int(section in (4, 5)))
    constraint.add_daily_staffing_targets()
    constraint.model.Minimize(sum(terms))
    solver = cp_model.CpSolver()
    assert solver.Solve(constraint.model) == cp_model.OPTIMAL
    shortages = {
        label: solver.Value(var)
        for _, label, var, _ in constraint.optimizer.staffing_shortages
    }
    assert shortages["調剤AM"] == 6
    assert shortages["調剤PM"] == 7


def test_saturday_admission_and_chemo_count_in_correct_periods():
    constraint = WeeklyPlacementOptimizer.__new__(WeeklyPlacementOptimizer)
    constraint.model = cp_model.CpModel()
    constraint.staff = pd.DataFrame({"必須メンバー": [False, False]}, index=["A", "B"])
    constraint.days, constraint.year, constraint.month = 6, 2026, 6
    constraint.holiday_dates = set()
    constraint.hope_list = pd.DataFrame()
    constraint.hope_day_column_map = {}
    constraint.debug_enabled = False
    constraint.eligible_sections = {"A": [1, 9], "B": [3]}
    terms = []
    constraint.optimizer = SimpleNamespace(
        register_objective_term=lambda name, term: terms.append(term),
        master_shifts={
            (staff, day, period): constraint.model.NewBoolVar(f"master_{staff}_{day}_{period}")
            for staff in constraint.staff.index
            for day in range(1, 7)
            for period in ("AM", "PM")
        },
    )
    constraint.shifts = {
        (staff, day, section): constraint.model.NewBoolVar(f"primary_{staff}_{day}_{section}")
        for staff in constraint.staff.index
        for day in range(1, 7)
        for section in (1, 3, 4, 5, 6, 7, 8, 9)
    }
    constraint.concurrent_shifts = {
        (staff, day, section): constraint.model.NewBoolVar(f"concurrent_{staff}_{day}_{section}")
        for staff in constraint.staff.index
        for day in range(1, 7)
        for section in (1, 2, 3, 4, 5, 7, 8, 9, 10, 11, 12, 15)
    }
    for (staff, day, section), var in constraint.shifts.items():
        constraint.model.Add(var == int((staff, section) in {("A", 1), ("B", 3)}))
    for (staff, day, section), var in constraint.concurrent_shifts.items():
        constraint.model.Add(var == int((staff, day, section) == ("A", 6, 11)))
    for (staff, day, period), var in constraint.optimizer.master_shifts.items():
        constraint.model.Add(var == int((staff, day, period) == ("A", 6, "PM")))

    constraint.add_daily_staffing_targets()
    constraint.model.Minimize(sum(terms))
    solver = cp_model.CpSolver()
    assert solver.Solve(constraint.model) == cp_model.OPTIMAL
    shortages = {
        label: solver.Value(var)
        for day, label, var, _ in constraint.optimizer.staffing_shortages
        if day == 6
    }
    assert shortages["調剤AM"] == 4
    assert shortages["調剤PM"] == 4
    assert shortages["化療_AM"] == 1
    assert shortages["化療_PM"] == 1


def test_sunday_uses_manager_or_other_eligible_floor():
    constraint = WeeklyPlacementOptimizer.__new__(WeeklyPlacementOptimizer)
    constraint.model = cp_model.CpModel()
    constraint.staff = pd.DataFrame(
        {"ポリファーマシーチーム": [False, False, False]},
        index=["A", "B", "C"],
    )
    constraint.days, constraint.year, constraint.month = 7, 2026, 6
    constraint.holiday_dates = set()
    constraint.primary_sections = (0, 1, 6, 10, 11, 17, 25, 26)
    constraint.get_eligible_sections = {
        "A": [1, 25], "B": [6], "C": [1, 26]
    }
    constraint.mode1_attendance_list = pd.DataFrame(
        "", index=constraint.staff.index, columns=range(1, 8)
    )
    constraint.optimizer = SimpleNamespace(
        porifa_tuesday=2,
        _normalize_attendance_mark=lambda value: value,
        get_attendance_status=lambda staff, day: True,
    )
    constraint.shifts = {
        (staff, day, section): constraint.model.NewBoolVar(f"{staff}_{day}_{section}")
        for staff in constraint.staff.index
        for day in range(1, 8)
        for section in constraint.primary_sections
        if section not in (0, 17)
    }
    constraint.apply_exclusive_assignment()
    solver = cp_model.CpSolver()
    assert solver.Solve(constraint.model) == cp_model.OPTIMAL
    assert solver.Value(constraint.shifts["A", 7, 25]) == 1
    assert solver.Value(constraint.shifts["B", 7, 6]) == 1
    assert solver.Value(constraint.shifts["C", 7, 26]) == 1


def test_weekly_excel_palliative_times_and_nst(tmp_path):
    data = pd.DataFrame({
        "Name": ["A", "B", "C"],
        "日付": [1, 4, 4],
        "専属業務": ["調剤室", "4階", "調剤室"],
        "兼務業務": ["緩和回診", "緩和回診", "NST回診"],
        "当直": ["なし", "当直担当", "なし"],
    })
    files = CalendarCreator.mk_weekly_shift_schedule(data, 2026, 6, tmp_path)
    assert len(files) == 1
    sheet = pd.read_excel(files[0], index_col=0)
    assert "AMA" in sheet.loc["調剤室", "06/01 (月曜日)"]
    assert "PMA" in sheet.loc["その他", "06/01 (月曜日)"]
    assert "PMB ◎" in sheet.loc["4階", "06/04 (木曜日)"]
    assert "AMB ◎" in sheet.loc["その他", "06/04 (木曜日)"]
    assert "NST回診" in sheet.loc["その他", "06/04 (木曜日)"]


def test_weekly_excel_saturday_chemo_ict_and_master(tmp_path):
    data = pd.DataFrame({
        "Name": ["A", "B"],
        "日付": [6, 2],
        "専属業務": ["調剤室", "4階"],
        "兼務業務": ["化療,マスター管理", "ICT回診"],
        "マスター時間帯": ["PM", ""],
        "当直": ["なし", "なし"],
    })
    files = CalendarCreator.mk_weekly_shift_schedule(data, 2026, 6, tmp_path)
    sheet = pd.read_excel(files[0], index_col=0)
    assert sheet.loc["調剤室", "06/06 (土曜日)"] == "AMA"
    assert sheet.loc["化療", "06/06 (土曜日)"] == "PMA"
    assert "マスター管理" in sheet.loc["その他", "06/06 (土曜日)"]
    assert "PMA" in sheet.loc["その他", "06/06 (土曜日)"]
    assert "ICT回診" in sheet.loc["その他", "06/02 (火曜日)"]


def test_weekly_excel_saturday_admission_moves_to_dispensing_pm(tmp_path):
    data = pd.DataFrame({
        "Name": ["A"],
        "日付": [6],
        "専属業務": ["入退院センター"],
        "兼務業務": [""],
        "当直": ["なし"],
    })
    files = CalendarCreator.mk_weekly_shift_schedule(data, 2026, 6, tmp_path)
    sheet = pd.read_excel(files[0], index_col=0)
    assert sheet.loc["入退院センター", "06/06 (土曜日)"] == "AMA"
    assert sheet.loc["調剤室", "06/06 (土曜日)"] == "PMA"


def test_weekly_excel_holiday_saturday_admission_is_unchanged(tmp_path):
    data = pd.DataFrame({
        "Name": ["A"],
        "日付": [3],
        "専属業務": ["入退院センター"],
        "兼務業務": [""],
        "当直": ["なし"],
    })
    files = CalendarCreator.mk_weekly_shift_schedule(data, 2025, 5, tmp_path)
    sheet = pd.read_excel(files[0], index_col=0)
    assert sheet.loc["入退院センター", "05/03 (土曜日)"] == "A"
    assert pd.isna(sheet.loc["調剤室", "05/03 (土曜日)"])


def test_weekly_excel_spans_december_and_january_in_calendar_order(tmp_path):
    data = pd.DataFrame({
        "Name": ["A", "B", "C", "D", "E", "F"],
        "日付": [29, 30, 31, 32, 33, 34],
        "専属業務": ["調剤室"] * 6,
        "兼務業務": ["", "", "緩和回診", "ポリファーマシー", "化療", ""],
        "当直": ["なし"] * 6,
    })

    files = CalendarCreator.mk_weekly_shift_schedule(data, 2026, 12, tmp_path)

    assert len(files) == 1
    sheet = pd.read_excel(files[0], index_col=0)
    assert list(sheet.columns) == [
        "12/29 (火曜日)", "12/30 (水曜日)", "12/31 (木曜日)",
        "01/01 (金曜日)", "01/02 (土曜日)", "01/03 (日曜日)",
    ]
    assert sheet.loc["調剤室", "12/31 (木曜日)"] == "PMC"
    assert "ポリファーマシーチーム" in sheet.loc["その他", "01/01 (金曜日)"]
    assert sheet.loc["化療", "01/02 (土曜日)"] == "PME"


def test_weekly_excel_iso_week_year_rollover(tmp_path):
    data = pd.DataFrame({
        "Name": ["A", "B", "C"],
        "日付": [30, 31, 32],
        "専属業務": ["調剤室"] * 3,
        "兼務業務": ["", "", "ポリファーマシー"],
        "当直": ["なし"] * 3,
    })

    files = CalendarCreator.mk_weekly_shift_schedule(data, 2018, 12, tmp_path)

    assert [file.name for file in files] == [
        "Shift_week_2018_12_week52.xlsx", "Shift_week_2018_12_week1.xlsx"
    ]
    first, second = [pd.read_excel(file, index_col=0) for file in files]
    assert list(first.columns) == ["12/30 (日曜日)"]
    assert list(second.columns) == ["12/31 (月曜日)", "01/01 (火曜日)"]
    assert "C" in second.loc["その他", "01/01 (火曜日)"]


@pytest.mark.parametrize("day", [0, 1.5, 35, None])
def test_weekly_excel_rejects_invalid_day(tmp_path, day):
    data = pd.DataFrame({
        "Name": ["A"], "日付": [day], "専属業務": ["調剤室"],
        "兼務業務": [""], "当直": ["なし"],
    })

    with pytest.raises(ValueError, match="日付が不正"):
        CalendarCreator.mk_weekly_shift_schedule(data, 2026, 12, tmp_path)
