from optimizer.mode1.base_constraint import BaseConstraint
from datetime import datetime
from config.sections import PRIMARY_SECTIONS
from config.floor_mapping import FLOOR_MAPPING
from config.concurrent_sections import CONCURRENT_SECTIONS

class WorkRequests(BaseConstraint):
    """
    出勤希望を叶える
    - スタッフ条件により決まる出勤を反映する
    - 希望リストに基づく出勤希望を反映する
    """
    def apply(self):
        self.eligible_sections = self.get_eligible_sections#割り当て可能な業務名の制約を取得
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
                    if self._hope_matches(self._get_hope_value(staff, day), {1}):  # 出勤希望
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
                        
    