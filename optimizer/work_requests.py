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
        self.fixed_manager_meeting()
        
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
    
    
    def fixed_manager_meeting(self):
        """
        - 役職者は第一、第三、第五月曜は役職者会議のため出勤
        - 配置はそれぞれの所属フロアへ割り当てる
        - 休み希望があればそちらを優先する
        """
        print("役職者会議の出勤希望を反映します。")
        penalties = []
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
                        if self.staff.loc[staff,'Floor'] in [9,10]:
                            continue
                        
                        #所属フロアの専任業務を割り当てる
                        floor = self.staff.loc[staff,'Floor']
                        #floorに対応するセクションIDをPRIMARY_SECTIONSから取得
                        #対応表の定義 {PRIMARY_SECTIONS:FLOOR_MAPPING}
                        section_id_df = {1:4,#PRIMARY_SECTIONS: FLOOR_MAPPING = (4:1-2階):('1-2':1)
                                        2:8,#'DI':'DI'
                                        3:5,#'3階':'3階'
                                        4:6,#'4階':'4階'
                                        5:7,#'5階':'5階'
                                        6:9,#'化療':'化療'
                                        8:1,#'調剤':'調剤'TODO 調剤もしくは監査に割り当てる必要
                                        9:16,#'外来':'外来'
                                        10:14,#'部長':'医療安全・感染管理'

                                        }
                        section_id = section_id_df.get(floor,None)
                        self.model.Add(self.shifts[(staff,mon,section_id)] == 1)  #専任業務にフロア業務を割り当てる             
                        #兼任業務に役職者会議を割り当てる
                        self.model.Add(self.concurrent_shifts[(staff,mon,6)] == 1)  #'役職者会議':6  
    