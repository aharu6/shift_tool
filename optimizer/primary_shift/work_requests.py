from optimizer.base_constraint import BaseConstraint
from datetime import datetime
from config.sections import PRIMARY_SECTIONS
from config.floor_mapping import FLOOR_MAPPING
from config.concurrent_sections import CONCURRENT_SECTIONS
from optimizer.primary_shift.work_constraints import WorkConstraints

class WorkRequests(BaseConstraint):
    """
    出勤希望を叶える
    - スタッフ条件により決まる出勤を反映する
    - 希望リストに基づく出勤希望を反映する
    """
    def apply(self):
        self.eligible_sections = WorkConstraints._get_eligible_section_constraints(self)#割り当て可能な業務名の制約を取得
        self.name6_day16to23()
        self.fixed_6_on_requests()
        self.fixed_6_second_friday()
        self.apply_day_on_requests()

    def _is_non_working_day(self, day):
        return datetime(self.year, self.month, day).weekday() == 6 or self._is_holiday(day)

    def _get_day_on_request_sections(self, staff, day):
        """
        出勤希望(hope==1)を適用する対象セクションを返す。
        - 平日: スタッフの配置可能セクション全体
        - 日曜祝日: 運用上許可するセクションのみ
        """
        eligible_sections = [s for s in self.primary_sections if s in self.eligible_sections[staff]]

        if self._is_non_working_day(day):
            # 日曜祝日はこのセクションのみ出勤希望を許可（運用に合わせて調整）
            non_working_day_allowed_sections = {1, 8}  # 調剤室, DI
            return [s for s in eligible_sections if s in non_working_day_allowed_sections]

        return eligible_sections
    
    def apply_day_on_requests(self):         
            """
            出勤希望は叶える
            - 配置可能なセクションに割り当てる
            - 日曜祝日は運用上許可したセクションのみ対象にする
            """
            for staff in self.staff.index:
                staff_requests = self.hope_list.loc[staff]

                for day in range(1, self.days + 1):
                    if staff_requests.iloc[day] ==1:
                        target_sections = self._get_day_on_request_sections(staff, day)
                        if not target_sections:
                            print(
                                f"⚠️ Day {day} スタッフ{staff}: 出勤希望ありだが、"
                                "日曜祝日運用で割り当て可能セクションがないため希望制約をスキップ"
                            )#TODO:ない場合は調剤室またはDIを割り当てる、祝日の水曜日はセットがあるので5階病棟を半日割り当てる
                            continue

                        if (staff, day, 17) in self.shifts:
                            self.model.Add(
                                sum(self.shifts[(staff,day,section)] for section in target_sections) == 1
                            ).OnlyEnforceIf(self.shifts[(staff, day, 17)].Not())
                        else:
                            self.model.Add(
                                sum(self.shifts[(staff,day,section)] for section in target_sections) == 1
                            )
                        
    def name6_day16to23(self):
        """
        name6の6日から23日まで出勤希望(ソフト制約)
        - 配置はDI
        - 日曜祝日でも希望あれば叶えるので、is_non_working_dayのチェックはしない
        """
        print("name6の6日から23日まで出勤希望を反映します。")
        staff_requests = self.hope_list.loc[6]  #name ==6のスタッフ希望を取得
        for day in range(6,24):             
            if staff_requests.iloc[day] == 0:
                continue
            #日曜祝日でも希望あれば叶えるので、is_non_working_dayのチェックはしない
            for staff in self.staff.index:
                if staff=='6' or staff==6:
                    self.model.Add(self.shifts[(staff,day,8)] == 1)
                    
    
    def fixed_6_on_requests(self):
        """name6は火曜・金曜になるべく出勤、ソフト制約"""
        print("name6の火曜・金曜の出勤希望を反映します。")
        staff_requests = self.hope_list.loc[6]  #name ==6のスタッフ希望を取得
        for day in range(1,self.days +1):
            if staff_requests.iloc[day] == 0:
                continue#休み希望があればスキップ
            if self._is_non_working_day(day):
                continue #日曜祝日ならスキップ
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
            if self._is_non_working_day(second_friday):
                return #第二金曜日が日曜祝日ならスキップ
            self.model.Add(self.shifts[(6,second_friday,8)]== 1)
    
    
    