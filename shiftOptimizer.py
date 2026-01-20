from ortools.sat.python import cp_model
import pandas as pd
from datetime import datetime,timedelta

class ShiftOptimizer:
    def __init__(self,year,month,staff_list_pass,required_list,hope_list):
        """2.変数リスト

        Args:
            year (_type_): 作成する年
            month (_type_): 作成する月
            staff_list_pass (_type_): スタッフ条件
            required_list (_type_): 固定の休み希望リスト
            hope_list (_type_): 希望の休みリスト
            
        スタッフ一人あたり、１日あたり３種類のシフトを割り当てる
        出勤の日：勤務-兼任業務-当直の有無  休みの日：休みー休みー休み
        
        """
        self.model = cp_model.CpModel()
        self.year = year
        self.month = month
        self.days = self._get_days_in_month()
        self.staff = pd.read_excel(staff_list_pass,sheet_name="member_list",index_col=0,skiprows=1)
        self.required_list = required_list
        self.hope_list = hope_list
        self.primary_sections = ['調剤室','監査','入退院センター','1-2階','3階','4階','5階','DI','化療','緩和回診(専任)','ポリファーマシーチーム','せん妄ラウンド','AST','医療安全・感染管理']
        self.concurrent_sections = ['心不全回診','NST回診','ICT回診','RI','緩和回診(兼任)','当直']
        
        self.shifts = {}
        self.concurrent_shifts = {}  # 兼務業務用の変数辞書を追加
        
    def _get_days_in_month(self):
        if self.month ==12:
            next_month =datetime(self.year +1,1,1)
        else:
            next_month =datetime(self.year,self.month +1,1)
        last_day = (next_month - timedelta(days=1)).day
        return last_day
    
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
                    
        
    def add_basic_constraints(self):
        # 1. 専属業務は1人1日1セクションのみ
        for staff in self.staff.index:
            for day in range(1,self.days +1):
                self.model.Add(
                    sum(self.shifts[(staff,day,section)] for section in self.primary_sections) <=1
                )
                
        #　兼務業務は専属業務がある場合のみ割り当て可能
        # 2.各セクションの必要人数を満たす
        #日付や曜日によって変動する人数に対応する
        #TODO:日毎に必要人数を決定する別関数必要　required_staff_per_day
        required_staff = {
            '調剤室': 7,
            '1-2階': 3,
            '3階': 4,
            '4階': 4,
            '5階': 4,
            'DI': 1,
            'ケモ': 4
        }
        
    #3.休み希望の順守
    def day_off_requests(self, hope_list):
        for staff in self.staff.index:
            staff_requests = hope_list.loc[staff]
            for day in range(1,self.days+1):
                if staff_requests[day] == 0:
                    self.model.Add(
                        sum(self.shifts[(staff,day,section)] for section in self.sections) ==0  
                    )
            
    #4.出勤希望の順守
    
    #5.固定希望出勤の順守 create_hopelistで作成した希望リストを使用
    def fixed_day_on_requests(self, required_list):
        for staff in self.staff.index:
            staff_requests = required_list.loc[staff]
            for day in range(1,self.days+1):
                if staff_requests[day] == 1:
                    self.model.Add(
                        sum(self.shifts[(staff,day,section)] for section in self.sections) ==1  
                    )
        
    #6.当直は月2回まで
    
    #7.当直明けはなるべく休み
    
    #8.前回の当直から次回の当直までは最低7日間空ける
    
    #9.連続勤務は最大6日まで
    
    #10.フロア毎の必要人数確保
    
    #11.ソフト制約　日曜祝日出勤は可能な限り一人月1回までとする


