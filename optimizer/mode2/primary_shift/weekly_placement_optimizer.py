import pandas as pd
import numbers 
import jpholiday
from optimizer.mode2.concurrent_shift import MeetingConstraints
from optimizer.mode2.concurrent_shift.concurrent_constraints import ConcurrentConstraints
from config.section_configs import make_section_configs
from optimizer.method.base_constraint import BaseConstraint

class WeeklyPlacementOptimizer(BaseConstraint):
    def __init__(self,model,optimizer):
        super().__init__(model,optimizer)
        self.mode1_attendance_list = optimizer.mode1_attendance_list
        

    """勤務に関する基本制約"""
    def apply(self):
        self.eligible_sections = self.get_eligible_sections
        self.apply_exclusive_assignment()
        self.add_daily_staffing_targets()
        
    #専属業務を1日１つ割り当てる
    def apply_exclusive_assignment(self):
        placement_sections = [
            section
            for section in self.primary_sections
            if section not in {0,17}
        ]
        
        porifa_members = set(
            self.staff.index[self.staff["ポリファーマシーチーム"]]
        )
        
        for staff in self.staff.index:
            for day in range(1, self.days + 1):
                day_column = next(
                    (
                        column
                        for column in self.mode1_attendance_list.columns
                        if str(column).strip() == str(day)
                    ),
                    None,
                )
                if day_column is None:
                    raise KeyError(f"出勤表に {day} 日の列がありません")
                
                value = self.mode1_attendance_list.loc[staff,day_column]
                is_assignment_day = pd.isna(value) or self.optimizer._normalize_attendance_mark(value) in {"","◎"}
                
                eligible_sections = [
                    section
                    for section in self.get_eligible_sections.get(staff,[])
                    if section in placement_sections
                    and section not in {12, 13, 18, 19, 21, 22, 24, 27}
                ]

                if self._get_weekday(day) == 6 or self._is_holiday(day):
                    if 26 in eligible_sections:
                        eligible_sections = [26]
                    elif 25 in eligible_sections:
                        eligible_sections = [25]
                    elif 1 in eligible_sections:
                        eligible_sections = [1]
                    else:
                        eligible_sections = [
                            section for section in eligible_sections
                            if section in {3, 4, 5, 6, 7, 8, 9, 14, 16}
                        ]
                
                if day==self.optimizer.porifa_tuesday:
                    if staff in porifa_members:
                        eligible_sections = [
                            section for section in eligible_sections if section == 11
                        ]
                    else:
                        eligible_sections = [
                            section for section in eligible_sections if section !=11
                        ]
                else:
                    eligible_sections = [
                        section for section in eligible_sections if section != 11
                    ]
                        
                assignment_vars = [
                    self.shifts[(staff,day,section)]
                    for section in eligible_sections
                    if (staff,day,section) in self.shifts
                ]
                
                self.model.Add(sum(assignment_vars) == int(is_assignment_day))
                
                # 専属業務の割り当てができないセクションの変数を0に設定
                #担当以外の専属業務が割り当てられないように
                eligible_sections_set = set(eligible_sections)
                ineligible_assignemet_vars = [
                    self.shifts[(staff, day, section)]
                    for section in placement_sections
                    if section not in eligible_sections_set
                ]
                self.model.Add(sum(ineligible_assignemet_vars) == 0)

    def _add_staffing_target(self, day, label, count, target):
        bound = len(self.staff) + target
        shortage = self.model.NewIntVar(0, target, f"staffing_shortage_{label}_{day}")
        excess = self.model.NewIntVar(0, bound, f"staffing_excess_{label}_{day}")
        self.model.Add(count - target == excess - shortage)
        self.optimizer.register_objective_term(
            f"staffing_{label}_{day}", 10000 * (shortage + excess)
        )
        self.optimizer.staffing_shortages.append((day, label, shortage, target))
        self.optimizer.staffing_excesses.append((day, label, excess, target))

    def add_daily_staffing_targets(self):
        self.optimizer.staffing_shortages = []
        self.optimizer.staffing_excesses = []
        section_targets = {
            "1-2F": 4,
            "3F": 5,
            "4F": 6,
            "5F": 7,
            "化療": 9,
            "DI": 8,
            "入退院センター": 3,
        }
        for day in range(1, self.days + 1):
            weekday = self._get_weekday(day)
            if weekday == 6 or self._is_holiday(day):
                continue
            previous_holiday = day > 1 and self._is_holiday(day - 1)
            di_target = 2 if weekday == 0 else 1
            if self.month in {1, 7, 9, 11} and day > self.days - 5:
                di_target = 2
            chemo_target = 2 if weekday == 5 else 4
            if weekday != 5 and any(
                self._hope_matches(self._get_hope_value(staff, day, default=7), {3})
                and 6 in {
                    self._get_staff_column_value(staff, column)
                    for column in ("Floor", "Floor2", "Floor3")
                }
                for staff in self.staff.index
            ):
                chemo_target = 3
            targets = {
                "1-2F": 3,
                "3F": 5 if weekday == 1 else 4,
                "4F": 5 if weekday == 0 else 4,
                "5F": 5 if weekday in (0, 2) or (weekday == 1 and previous_holiday) else 4,
                "化療": chemo_target,
                "DI": di_target,
                "入退院センター": 1,
            }
            for label, section in section_targets.items():
                count = sum(self.shifts[(staff, day, section)] for staff in self.staff.index)
                self._add_staffing_target(day, label, count, targets[label])

            required_members = [
                staff for staff in self.staff.index
                if self._is_enabled_value(self._get_staff_column_value(staff, "必須メンバー"))
                and 4 in self.eligible_sections.get(staff, [])
            ]
            member_shortage = self.model.NewBoolVar(f"required_12f_shortage_{day}")
            self.model.Add(
                sum(self.shifts[(staff, day, 4)] for staff in required_members)
                + member_shortage >= 1
            )
            self.optimizer.register_objective_term(
                f"required_12f_{day}", 10000 * member_shortage
            )
            self.optimizer.staffing_shortages.append(
                (day, "1-2F必須メンバー", member_shortage, 1)
            )

            morning = []
            afternoon = []
            for staff in self.staff.index:
                hope = self._get_hope_value(staff, day, default=7)
                dispensing = self.shifts[(staff, day, 1)]
                admission = self.shifts[(staff, day, 3)]
                for period, counts, absent_hope in (
                    ("AM", morning, 10), ("PM", afternoon, 9)
                ):
                    if self._hope_matches(hope, {absent_hope}):
                        continue
                    base_sections = [dispensing]
                    if period == "AM" or weekday != 5:
                        base_sections.append(admission)
                    if weekday == 5 and period == "AM":
                        base_sections.append(self.shifts[(staff, day, 9)])

                    busy_sections = [2] if period == "AM" else [1, 4, 8, 15]
                    if (weekday == 0 and period == "PM") or (
                        weekday == 3 and period == "AM"
                    ):
                        busy_sections.append(5)
                    if weekday == 4 and period == "PM":
                        busy_sections.append(10)
                    busy = self.model.NewBoolVar(f"dispensing_busy_{staff}_{day}_{period}")
                    self.model.AddMaxEquality(
                        busy,
                        [self.concurrent_shifts[(staff, day, section)] for section in busy_sections],
                    )
                    counted = self.model.NewBoolVar(f"dispensing_count_{staff}_{day}_{period}")
                    self.model.Add(counted <= sum(base_sections))
                    self.model.Add(counted + busy <= 1)
                    self.model.Add(counted >= sum(base_sections) - busy)
                    counts.append(counted)
            if weekday == 4:
                am_target, pm_target = (7, 6) if (day - 1) // 7 % 2 == 0 else (6, 5)
            elif weekday == 5:
                am_target, pm_target = 6, 5
            else:
                am_target = pm_target = 7
            self._add_staffing_target(day, "調剤AM", sum(morning), am_target)
            self._add_staffing_target(day, "調剤PM", sum(afternoon), pm_target)