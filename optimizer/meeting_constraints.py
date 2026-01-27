from .base_constraint import BaseConstraint
from datetime import datetime

class MeetingConstraints(BaseConstraint):
    """会議に関する制約"""
    def apply(self):
        self.fixed_manager_meeting()
        self.fixed_pharmacy_meeting()
            
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
    
    def fixed_pharmacy_meeting(self):
        """病棟担当役職者は・第3金曜日は臨床薬剤課役職者会議のため関係する役職者は全員出勤"""
        for staff in self.staff.index:
            if self.staff.loc[staff,'主任以上']==True:
                fridays = [day for day in range(1,self.days +1) if datetime(self.year,self.month,day).weekday()==4]
                print(self.staff.loc[staff,'Floor'])
                if len(fridays) >=3:
                    third_friday = fridays[2]
                    #休み希望があれば優先する
                    staff_requests = self.hope_list.loc[staff]
                    if staff_requests.iloc[third_friday -1]==0:
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
                                    10:14#'部長':'医療安全・感染管理'
                                    }
                    section_id = section_id_df.get(floor,None)
                    self.model.Add(
                        self.shifts[(staff,third_friday,section_id)]==1
                    ) 
                    #兼任業務に役職者会議を割り当てる
                    self.model.Add(
                        self.concurrent_shifts[(staff,third_friday,7)]==1
                    )   
                    
    def fixed_pharmacy_meeting(self):
        """
        第四金曜日は医薬品安全使用WGのため出勤
        - name =0,name =6,name = 10,name = 21,name = 16,name = 29
        - 兼務業務に割り当てる
        - 休み希望があればそちらを優先する  
        """
        print("医薬品安全使用WGの出勤希望を反映します。")
        pharmacy_staff = [0,6,10,16,21,29]
        fridays = [day for day in range(1,self.days +1) if datetime(self.year,self.month,day).weekday()==4]
        if len(fridays) >=4:
            fourth_friday = fridays[3]
            for staff in pharmacy_staff:
                #休み希望をチェック
                staff_requests = self.hope_list.loc[staff]
                if staff_requests.iloc[fourth_friday -1] ==0:
                    continue
                self.model.Add(
                    self.concurrent_shifts[(staff,fourth_friday,8)]==1
                )
        