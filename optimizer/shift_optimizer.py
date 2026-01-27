from ortools.sat.python import cp_model
import pandas as pd
from datetime import datetime,timedelta
from config.sections import PRIMARY_SECTIONS
from config.concurrent_sections import CONCURRENT_SECTIONS
from config.floor_mapping import FLOOR_MAPPING
from config.hope_mapping import HOPE_MAPPING
from optimizer.work_constraints import WorkConstraints  
from optimizer.work_requests import WorkRequests
from optimizer.meeting_constraints import MeetingConstraints
from optimizer.oncall_constraints import OncallConstraints
class ShiftOptimizer:
    def __init__(self,year,month,staff_list_pass,hope_list):
        """
        シフト最適化
        専任業務を定義

        Args:
            year (_type_): 作成する年
            month (_type_): 作成する月
            staff_list_pass (_type_): スタッフ条件
            hope_list (_type_): 希望の休みリスト        
        """
        self.model = cp_model.CpModel()
        self.year = year
        self.month = month
        self.days = self._get_days_in_month()
        self.staff = pd.read_excel(staff_list_pass,sheet_name="member_list",index_col=0,skiprows=1)
        #floorカラムを数値IDに変換
        if 'Floor' in self.staff.columns:
            self.staff['Floor'] = self.staff['Floor'].map(FLOOR_MAPPING)
        #floor2カラムを数値IDに変換
        if 'Floor2' in self.staff.columns:
            self.staff['Floor2'] = self.staff['Floor2'].map(FLOOR_MAPPING)
        self.hope_list = hope_list
        #希望リストを数値IDに変換
        for column in self.hope_list.columns:
            self.hope_list[column] = self.hope_list[column].apply(
                lambda x: HOPE_MAPPING.get(x,x) if pd.notna(x) else x
            )
        self.primary_sections = PRIMARY_SECTIONS.keys()
        self.concurrent_sections = CONCURRENT_SECTIONS.keys()
        self.required_num = {1: 4,
                            2: 2,
                            3: 1,
                            4: 4,
                            5: 4,
                            6: 1,
                            7: 4,
                            8: 1,
                            9: 4,
                            10: 1,
                            11: 1,
                            12: 1,
                            13: 1,
                            14: 1,
                            15: 1}
        
        self.shifts = {}
        self.concurrent_shifts = {}  # 兼務業務用の変数辞書を追加
        self.night_shifts = {}
        
        self._init_constraints()
    
    def create_variables(self):
        # シフト変数(専属業務)
        for staff in self.staff.index:
            for day in range(1, self.days + 1):
                for section in self.primary_sections:
                    var_name = f'shift_{staff}_{day}_{section}'
                    self.shifts[(staff, day, section)] = self.model.NewBoolVar(var_name)
        
        # 兼務業務の変数を追加
        for staff in self.staff.index:
            for day in range(1, self.days + 1):
                for section in self.concurrent_sections:
                    var_name = f'concurrent_{staff}_{day}_{section}'
                    self.concurrent_shifts[(staff, day, section)] = self.model.NewBoolVar(var_name)
                    
        # 当直変数の初期化
        self.night_shifts = {}
        
        # 当直変数
        for day in range(1,self.days +1):
            for i, staff1 in enumerate(self.staff.index):
                for staff2 in self.staff.index[i+1:]:
                    var_name = f'oncall_{staff1}_{staff2}_{day}'
                    self.night_shifts[(staff1,staff2,day)] = self.model.NewBoolVar(var_name)
                    
        
        
    def _get_days_in_month(self):
        if self.month ==12:
            next_month =datetime(self.year +1,1,1)
        else:
            next_month =datetime(self.year,self.month +1,1)
        last_day = (next_month - timedelta(days=1)).day
        return last_day
    
    
    def _init_constraints(self):
        """制約オブジェクトの初期化"""
        self.work_constraints = WorkConstraints(self.model,self)
        self.work_requests = WorkRequests(self.model,self)
        self.oncall_constraints = OncallConstraints(self.model,self)
        
        self.meeting_constraints = MeetingConstraints(self.model,self)
        
    def apply_all_constraints(self):
        """全ての制約を適用"""
        self.oncall_constraints.apply()
        self.work_requests.apply()
        self.work_constraints.apply()
    
    #休み希望は叶える
    def apply_day_off_requests(self):
        """休み希望を反映"""
        for staff in self.staff.index:
            staff_requests = self.hope_list.loc[staff]
            for day in range(1, self.days + 1):
                if staff_requests.iloc[day-1] == 0:
                    self.model.Add(
                        sum(self.shifts[(staff, day, section)] for section in self.primary_sections) == 0  
                    )
                    
    #9.連続勤務は最大6日まで
    
    #10.ソフト制約　日曜祝日出勤は可能な限り一人月1回までとする
    
    #11.フロア毎の必要人数確保、配置を決める
    def add_section_requirements(self):
        """
        各セクションの必要人数を確保、配置を決める
        section ==0ではない人には、そのセクションに最低人数を配置する
        休みには必要人数の制約は不要
        """
        for section_id, required_count in self.required_num.items():
            for day in range(1, self.days + 1):
                self.model.Add(
                    sum(self.shifts[(staff, day, section_id)]
                        for staff in self.staff.index) >= required_count
                )

    #12.兼務業務の割り当て
    def add_current_assignment(self):
        """
        兼務業務の割り当て制約を追加
        - 兼務業務は専属業務をもつスタッフ飲みに割り当てる
        - スタッフの業務可能な条件.xlsxの条件に基づいて割り当てる
        - 各兼務業務の必要人数を確保する
        """        
        
        #兼務業務毎の必要人数
        concurrent_required_num = {
            '心不全回診':1,
            'NST回診':1,
            'ICT回診':1,        
            'RI':1,
            '緩和回診(兼任)':1,
            '当直':2
        }#会議は該当する役職者であればなるべく全員参加
        
        for day in range(1,self.days +1):
            for c_section in self.concurrent_sections:
                ecligible_staff = []
                for staff in self.staff.index:
                    if c_section in self.staff.columns and self.staff.loc[staff,c_section] == True:
                        ecligible_staff.append(staff)
                
                if ecligible_staff:
                    required_count = concurrent_required_num.get(c_section,0)
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
