from optimizer.base_constraint import BaseConstraint

class WorkConstraints(BaseConstraint):
    """勤務に関する基本制約"""
    def apply(self):
        self._add_basic_constraints()
        
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
        
