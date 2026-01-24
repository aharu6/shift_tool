from optimizer.base_constraint import BaseConstraint

class WorkConstraints(BaseConstraint):
    """勤務に関する基本制約"""
    def apply(self):
        self._add_basic_constraints()
        self.add_eligible_section_constraints()
        self.add_on_call_primary_section_constraint()
        
    def _add_basic_constraints(self):
        """専属業務は1人1日1セクションのみ"""
        # 1. 専属業務は1人1日1セクションのみ
        for staff in self.staff.index:
            for day in range(1, self.days + 1):
                self.model.Add(
                    sum(self.shifts[(staff, day, section)] for section in self.primary_sections) <= 1
                )
                
                # 兼務業務は専属業務がある場合のみ割り当て可能
                has_primary = self.model.NewBoolVar(f'has_primary_{staff}_{day}')
                self.model.Add(
                    sum(self.shifts[(staff, day, section)] for section in self.primary_sections) >= 1
                ).OnlyEnforceIf(has_primary)
                
                # 専属業務がない場合は兼務業務も割り当てない
                for c_section in self.concurrent_sections:
                    self.model.Add(
                        self.concurrent_shifts[(staff, day, c_section)] == 0
                    ).OnlyEnforceIf(has_primary.Not())
        
    #条件.xlsxによる割り当て可能な業務名の制約
    def add_eligible_section_constraints(self):
        """条件.xlsxによる割り当て可能な業務名の制約"""
        for staff in self.staff.index:
            pass
            
    
    def add_on_call_primary_section_constraint(self):
        """当直に割り当てられている日に専属業務を休みにしない !=0"""
        for staff in self.staff.index:
            for day in range(1,self.days +1):
                oncall_assigned = []
                for other_staff in self.staff.index:
                    if staff != other_staff:
                        oncall_assigned.append(self.night_shifts.get((staff,other_staff,day),0))
                        oncall_assigned.append(self.night_shifts.get((other_staff,staff,day),0))
                if oncall_assigned:
                    self.model.Add(
                        sum(oncall_assigned) <= sum(
                            self.shifts[(staff,day,section)] for section in self.primary_sections
                        )
                    )
                        