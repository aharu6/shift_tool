from ortools.sat.python import cp_model
import pandas as pd
from datetime import datetime,timedelta
from config.sections import PRIMARY_SECTIONS
from config.concurrent_sections import CONCURRENT_SECTIONS
from config.floor_mapping import FLOOR_MAPPING
from optimizer.initialize import ShiftOptimizer

class ShiftVariables:
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
        self.hope_list = hope_list
        self.primary_sections = PRIMARY_SECTIONS.keys()
        self.concurrent_sections = CONCURRENT_SECTIONS.keys()        
        self.shifts = {}
        self.concurrent_shifts = {}  # 兼務業務用の変数辞書を追加
    
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
    
    
    def add_basic_constraints(self):
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
        
    def day_off_requests(self):
        for staff in self.staff.index:
            staff_requests = self.hope_list.loc[staff]
            print(f"スタッフ{staff}の休み希望: {staff_requests.values}")
            for day in range(1, self.days + 1):
                if staff_requests.iloc[day] == 0:
                    self.model.Add(
                        sum(self.shifts[(staff, day, section)] for section in self.primary_sections) == 0  
                    )
    """
    #曜日。日付。役職による規定の出勤日  
    """
    ## name == 6 は16日から22日は専属業務8(DI)に割り当てる
    def fixed_6_for6_22(self):
        for day in range(16,23):
            self.model.Add(
                self.shifts[(6,day,8)]==1
            )
    
    ##name==6は火曜と金曜は認知症せん妄ラウンドのため出勤
    def fixed_6_on_requests(self):
        for day in range(1,self.days +1):
            if datetime(self.year,self.month,day).weekday() in [1,4]:
                self.model.Add(
                    self.shifts[(6,day,12)]==1
                )
        
    ##name ==6は第二金曜日は病棟担当者カンファレンスのため出勤,配置はDI
    def fixed_6_second_friday(self):
        fridays = [day for day in range(1,self.days+1) if datetime(self.year,self.month,day).weekday()==4]
        if len(fridays) >=2:
            #休み希望のチェック　
            staff_requests = self.hope_list.loc[6]  
            if staff_requests.iloc[fridays[1]-1] ==0:
                return#休み希望があればスキップ
            second_friday = fridays[1]
            self.model.Add(
                self.shifts[(6,second_friday,8)]==1
            )
            
    ##役職者は第一、第三、第五月曜は役職者会議のため出勤
    #配置はそれぞれの所属フロアへ割り当てる
    #休み希望があればそちらを優先する
    def fixed_manager_meeting(self):
        for staff in self.staff.index:
            if self.staff.loc[staff,'主任以上']==True:
                mondays = [day for day in range(1,self.days + 1) if datetime(self.year,self.month,day).weekday()==0]
                for i,mon in enumerate(mondays):
                    if i%2==0:
                        #休み希望をチェック
                        staff_requests = self.hope_list.loc[staff]
                        if staff_requests.iloc[mon-1] ==0:
                            continue
                        #外来部門所属者は除く Floor == 9は除く
                        #部長は除く 　　　　　Floor ==10は除く
                        if self.staff.loc[staff,'Floor'] == 9:
                            continue
                        
                        #所属フロアの専任業務を割り当てる
                        floor = self.staff.loc[staff,'Floor']
                        #floorに対応するセクションIDをPRIMARY_SECTIONSから取得
                        #対応表の定義 {PRIMARY_SECTIONS:FLOOR_MAPPING}
                        section_id_df = {4:1,#PRIMARY_SECTIONS: FLOOR_MAPPING = (4:1-2階):('1-2':1)
                                    8:2,
                                    5:3,
                                    6:4,
                                    7:5,
                                    9:6,
                                    10:7,#
                                    1:8,# 調剤室ー調剤室
                                    16:9,#外来
                                    26:10,#部長
                                    3:11,#入退院センター
                                    22:12,#RI
                                    23:13,#RI
                                    14:14#医療安全・感染管理:'医療安全・感染管理'
                                    
                                        }
                        section_id = section_id_df.get(floor,None)
                        self.model.Add(
                            self.shifts[(staff,mon,section_id)]==1
                        ) 
                        #兼任業務に役職者会議を割り当てる
                        self.model.Add(
                            self.concurrent_shifts[(staff,mon,6)]==1
                        )
                        
    ##病棟担当役職者は・第3金曜日は臨床薬剤課役職者会議のため関係する役職者は全員出勤
    def fixed_pharmacy_meeting(self):
        for staff in self.staff.index:
            if self.staff.loc[staff,'主任以上']==True:
                fridays = [day for day in range(1,self.days +1) if datetime(self.year,self.month,day).weekday()==4]
                print(self.staff.loc[staff,'Floor'])
                if len(fridays) >=3:
                    third_friday = fridays[2]
                    #休み希望があれば優先する
                    staff_reqests = self.hope_list.loc[staff]
                    if staff_reqests.iloc[third_friday -1]==0:
                        continue
                    #外来部門 FLOOR==9は除く
                    if self.staff.loc[staff,'Floor'] == 9:
                        continue
                    #部長 FLOOR==10は除く
                    if self.staff.loc[staff,'Floor'] ==10:
                        continue
                    #化療 FLOOR==6は除く
                    if self.staff.loc[staff,'Floor'] ==6:
                        continue
                    #所属フロアの専任業務を割り当てる
                    floor = self.staff.loc[staff,'Floor']
                    section_id_df = {4:1,#PRIMARY_SECTIONS: FLOOR_MAPPING = (4:1-2階):('1-2':1)
                                    5:3,
                                    6:4,
                                    7:5,
                                    8:2,
                                    9:6,
                                    14:14#'医療安全・感染管理':'医療安全・感染管理'
                                    }
                    section_id = section_id_df.get(floor,None)
                    self.model.Add(
                        self.shifts[(staff,third_friday,section_id)]==1
                    ) 
                    #兼任業務に役職者会議を割り当てる
                    self.model.Add(
                        self.concurrent_shifts[(staff,third_friday,7)]==1
                    )   
                    
    #6.当直は月2回まで,当直不可のスタッフは除外する
    def add_oncall_constraints(self):
        """
        当直の基本制約
        - 当直不可のスタッフは除外
        - 月2回まで
        """
        for staff in self.staff.index:
            if self.staff.loc[staff,'当直']==False:
                for day in range(1,self.days +1):
                    for other_staff in self.staff.index:
                        if staff != other_staff:
                            self.model.Add(
                                self.night_shifts.get((staff,other_staff,day),0)==0
                            )
            else:
                total_oncalls = []
                for day in range(1,self.days +1):
                    for other_staff in self.staff.index:
                        if staff != other_staff:
                            total_oncalls.append(self.night_shifts.get((staff,other_staff,day),0))
                            total_oncalls.append(self.night_shifts.get((other_staff,staff,day),0))
                self.model.Add(
                    sum(total_oncalls)<=2
                )
    
    #7.当直は同性のスタッフで構成、同じフロアの組み合わせを避ける
    def add_oncall_paring_constraints(self):
        pass
    
    #7.当直明けはなるべく休み
    
    #8.前回の当直から次回の当直までは最低7日間空ける
    
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
