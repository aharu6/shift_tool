from optimizer.base_constraint import BaseConstraint
from datetime import datetime
from config.sections import PRIMARY_SECTIONS
from config.floor_mapping import FLOOR_MAPPING
from config.concurrent_sections import CONCURRENT_SECTIONS

class WorkRequests(BaseConstraint):
    """スタッフ条件により決まる出勤を反映するクラス"""
    def apply(self):
        self.name6_day16to23()
    
    def name6_day16to23(self):
        """
        name6の16日から23日まで出勤希望(ソフト制約)
        - 配置はDI
        """
        print("name6の16日から23日まで出勤希望を反映します。")
        print(self.staff.index)
        print(self.staff)
        for day in range(16,24):
            for staff in self.staff.index:
                if staff=='6':
                    self.model.Add(
                        self.shifts[(staff,day,8)]==1
                    )
