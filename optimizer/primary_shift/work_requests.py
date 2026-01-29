from optimizer.base_constraint import BaseConstraint
from datetime import datetime
from config.sections import PRIMARY_SECTIONS
from config.floor_mapping import FLOOR_MAPPING
from config.concurrent_sections import CONCURRENT_SECTIONS

class WorkRequests(BaseConstraint):
    """スタッフ条件により決まる出勤を反映するクラス"""
    def apply(self):
        self.name6_day16to23()
        self.fixed_6_on_requests()
        self.fixed_6_second_friday()
        
    def name6_day16to23(self):
        """
        name6の6日から23日まで出勤希望(ソフト制約)
        - 配置はDI
        """
        print("name6の6日から23日まで出勤希望を反映します。")
        staff_requests = self.hope_list.loc[6]  #name ==6のスタッフ希望を取得
        for day in range(6,24):             
            if staff_requests.iloc[day-1] == 0:
                continue
            for staff in self.staff.index:
                if staff=='6' or staff==6:
                    self.model.Add(self.shifts[(staff,day,8)] == 1)
                    
    
    def fixed_6_on_requests(self):
        """name6は火曜・金曜になるべく出勤、ソフト制約"""
        print("name6の火曜・金曜の出勤希望を反映します。")
        staff_requests = self.hope_list.loc[6]  #name ==6のスタッフ希望を取得
        for day in range(1,self.days +1):
            if staff_requests.iloc[day-1] == 0:
                continue#休み希望があればスキップ
            if datetime(self.year,self.month,day).weekday() in [1,4]:
                self.model.Add(self.shifts[(6,day,8)] == 1)

    
    def fixed_6_second_friday(self):
        """name ==6は第二金曜日は病棟担当者カンファレンスのため出勤,配置はDI"""
        print("name6の第二金曜日の出勤希望を反映します。")
        fridays = [day for day in range(1,self.days+1) if datetime(self.year,self.month,day).weekday()==4]
        if len(fridays) >=2:
            #休み希望のチェック　
            staff_requests = self.hope_list.loc[6]  
            if staff_requests.iloc[fridays[1]-1] ==0:
                return#休み希望があればスキップ
            second_friday = fridays[1]
            self.model.Add(self.shifts[(6,second_friday,8)]== 1)
    
    
    