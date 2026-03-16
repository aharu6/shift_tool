"""
    #12.兼務業務の割り当て
    def add_current_assignment(self):       
        
        #兼務業務毎の必要人数
        concurrent_required_num = {
            '心不全回診':1,
            'NST回診':1,
            'ICT回診':1,        
            '緩和回診(兼任)':1,
        }#会議は該当する役職者であればなるべく全員参加
        
        for day in range(1,self.days +1):
            for c_section in self.concurrent_sections:
                ecligible_staff = []
                for staff in self.staff.index:
                    if c_section in self.staff.columns and self.staff.loc[staff,c_section] == True:
                        ecligible_staff.append(staff)
                
                if ecligible_staff:
                    required_count = concurrent_required_num.get(c_section,0)
                    if c_section == 'RI':
                        self.model.Add(
                            sum(self.concurrent_shifts[(staff,day,c_section)]
                                for staff in ecligible_staff) <= 1
                        )
                    else:
                        self.model.Add(
                            sum(self.concurrent_shifts[(staff,day,c_section)]
                                for staff in ecligible_staff)==required_count
                        )
                    
                    for staff in self.staff.index:
                        if staff not in ecligible_staff:
                            self.model.Add(
                                self.concurrent_shifts[(staff,day,c_section)]==0
                            )
                            
        #1人あたりの兼務業務数を制限 当直を含める場合のみ１日２つまで
        for staff in self.staff.index:
            for day in range(1,self.days +1):
                self.model.Add(
                    sum(self.concurrent_shifts[(staff,day,c_section)]
                        for c_section in self.concurrent_sections)<=2
                )
    
"""
from optimizer.base_constraint import BaseConstraint
from datetime import datetime
class ConcurrentConstraints(BaseConstraint):
    def __init__(self, model, optimizer):
        super().__init__(model, optimizer)

    def apply(self):
        """
        兼務業務の制約を適用する関数
        - 兼務業務は専属業務をもつスタッフ飲みに割り当てる
        - スタッフの業務可能な条件.xlsxの条件に基づいて割り当てる
        - 各兼務業務の必要人数を確保する
        """
        self.add_concurrent_porifa()
        #self.add_concurrent_ri()
        pass
        

    def add_concurrent_ri(self):
        """
        RI
        - 月〜土は1名
        - 日曜祝日は0名、上で定義済み
        - 休み希望の日は配置しない,上で定義済み
        - 配置可能なスタッフがいない場合は0人でも許容
        - TODO:割り振りの優先度 name == > name == > name == > 条件シートの優先度
        """
        pass
        
    def add_concurrent_porifa(self):
        """
        金曜午後のポリファーマシーの配置
        火曜1日は専属業務で配置
        - メンバー全員が出勤可能の日に開催する
        - 1人でも参加不可のスタッフがいればその日は対象外とする
        - 火曜日に開催されていればその週は開催しない
        """
        for day in range(1,self.days+1):
            
            floor_porifa_id = 10
            #配置可能なスタッフリスト
            assigned_porifa_stafff = []
            #必須メンバーのリスト
            required_porifa_staff = []
            #セクション設定を定義
            section_configs = {
                'ポリファーマシー':{
                    'section_id': floor_porifa_id,
                    'assigned_list': assigned_porifa_stafff,
                    'available_list': [],
                    'check_day_off':True,
                    'check_oncall_next' :True,
                    'required_staff': required_porifa_staff
                }
            }
            self._build_section_availability(
                section_configs=section_configs,day = day,
                required_staff_12=None,
                required_staff_12_assigned=None,
                required_staff_12_available=None,
                di_eligible_staff_ids=None,
                porifa_staff_ids=None
            )
            #曜日、祝日、前日祝日を取得
            weekday = self._get_weekday(day)
            is_wekday = weekday <=4 #月〜金
            is_holiday = self._is_holiday(day)
            is_monday = weekday == 0
            is_tuesday = weekday ==1
            is_friday = weekday == 4
            prev_day_is_holiday = day >1 and self._is_holiday(day-1)
            
            
            if is_friday and not is_holiday:
                pass