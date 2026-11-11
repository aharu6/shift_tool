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