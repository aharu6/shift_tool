from ..base_constraint import BaseConstraint
from datetime import datetime

class MeetingConstraints(BaseConstraint):
    """会議に関する制約"""
    def apply(self):
        #self.fixed_medical_safety_working_group()
        #fixed_manager_meeting()ペナルティ変数を使用するのでここで適用はしない
        #self.fixed_medical_safety_working_group()ペナルティ変数を使用するのでここで適用はしない
        #self.yakushin()ペナルティ変数を使用するのでここで適用はしない
        pass
    def fixed_manager_meeting(self):
        """
        ソフト制約
        - 役職者は第一、第三、第五月曜は役職者会議のため出勤
        - 配置はそれぞれの所属フロアへ割り当てる
        - 休み希望があればそちらを優先する
        - 外来主任は除く
        - TODO:当直明けを除外する==当直変数になるべく役職者会議前日に当直を割り当てないようにする
        """
        print("役職者会議の出勤希望を反映します。")
        penalties = []
        for staff in self.staff.index:
            if self.staff.loc[staff,'主任以上']==True:
                print(f"{staff}は役職者会議のため出勤を割り当てます。")
                mondays = [day for day in range(1,self.days + 1) if datetime(self.year,self.month,day).weekday()==0]
                for i,mon in enumerate(mondays):
                    if i%2==0:
                        print(f"{mon}日は役職者会議のため出勤を割り当てます。")
                        #休み希望をチェック
                        staff_requests = self.hope_list.loc[staff]
                        #当直明けをチェック
                        
                        if staff_requests.iloc[mon-1] ==0:
                            self.model.Add(self.shifts[(staff,mon,0)]==1)#休みにする
                        #外来部門所属者は除く Floor == 9は除く
                        elif self.staff.loc[staff,'Floor'] in [9]:
                            print(f"{staff}は外来部門所属のため役職者会議の出勤から除外します。")
                            pass
                        else:
                            #なるべく休みにならないようにペナルティを加算
                            penalty_var = self.model.NewBoolVar('penalty_'+str(staff)+'_'+str(mon))
                            self.model.Add(self.shifts[(staff,mon,0)]==0).OnlyEnforceIf(penalty_var.Not())
                            penalties.append(penalty_var)
                            #TODO:兼任業務に役職者会議を割り当てる
                            print("役職者会議の兼任業務を割り当てます。")
                            self.model.Add(self.concurrent_shifts[(staff,mon,6)]==1).OnlyEnforceIf(penalty_var.Not())
                            self.model.Add(self.concurrent_shifts[(staff,mon,6)]==0).OnlyEnforceIf(penalty_var)
                            penalties.append(penalty_var)
                            
        return penalties
        #work_requestsのペナルティと合わせて、目的関数に加算する様にする
        
    def fixed_medical_safety_working_group(self):
        """病棟担当役職者は・第3金曜日は臨床薬剤課役職者会議のため関係する役職者は全員出勤(ソフト制約)"""
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
                    
    def fixed_medical_safety_working_group(self):
        """
        第四金曜日は医薬品安全使用WGのため出勤
        - name =0,name =6,name = 10,name = 21,name = 16,name = 29
        - 兼務業務に割り当てる
        - 休み希望があればそちらを優先する  
        """
        print("医薬品安全使用WGの出勤希望を反映します。")
        penalties = []
        pharmacy_staff = [0,6,10,16,21,29]
        fridays = [day for day in range(1,self.days +1) if datetime(self.year,self.month,day).weekday()==4]
        if len(fridays) >=4:
            fourth_friday = fridays[3]
            for staff in pharmacy_staff:
                #休み希望をチェック
                staff_requests = self.hope_list.loc[staff]
                if staff_requests.iloc[fourth_friday -1] ==0:
                    self.model.Add(self.shifts[(staff,fourth_friday,0)]==1)
                else:
                    #なるべく休みにならないようにペナルティ変数を追加
                    penalty_var = self.model.NewBoolVar('penalty_pharmacy_'+str(staff)+'_'+str(fourth_friday))
                    self.model.Add(self.shifts[(staff,fourth_friday,0)]==0).OnlyEnforceIf(penalty_var.Not())
                    #兼任業務に医薬品安全使用WGを割り当てる
                    self.model.Add(self.concurrent_shifts[(staff,fourth_friday,8)]==1).OnlyEnforceIf(penalty_var.Not())
                    self.model.Add(self.concurrent_shifts[(staff,fourth_friday,8)]==0).OnlyEnforceIf(penalty_var)
                    penalties.append(penalty_var)
        return penalties
    #TODO:work_constraintsの目的の関数にペナルティを加算するようにする
    
    def yakushin(self):
        """
        - 偶数月の第一木曜日が対象
        - 役職者は薬審の日は出勤とする
        - 休み希望があれば優先する
        - 配置可能なフロアのいずれかに出勤可能とする
        - 兼務業務内に薬審を入れる
        
        """
        print("薬審の日の出勤を反映します")
        penalties = []
        for staff in self.staff.index:
            if self.staff.loc[staff,'主任以上']== True:
                print(f"{staff}は薬審のため出勤を割り当てます")
                even_months = [2,4,6,8,10,12]
                if self.month in even_months:
                    print(f"{self.month}月は薬審の対象月です。")
                    first_thursday = [day for day in range(1,self.days +1) if datetime(self.year,self.month,day).weekday()==3]
                    if first_thursday:
                        first_thursday = first_thursday[0]
                        #休み希望をチェック
                        staff_requests = self.hope_list.loc[staff]
                        if staff_requests.iloc[first_thursday -1]==0:
                            self.model.Add(self.shifts[(staff,first_thursday,0)]==1)#休みにする
                        else:
                            #なるべく休みにならないようにする==配置可能なフロアのいずれかに出勤
                            penalty_var =self.model.NewBoolVar('penalty_var_'+str(staff)+'_'+str(first_thursday))
                            self.model.Add(self.shifts[(staff,first_thursday,0)]==0).OnlyEnforceIf(penalty_var.Not())
                            #兼任業務に薬審を割り当てる
                            self.model.Add(self.concurrent_shifts[(staff,first_thursday,9)]==1).OnlyEnforceIf(penalty_var.Not())
                            self.model.Add(self.concurrent_shifts[(staff,first_thursday,9)]==0).OnlyEnforceIf(penalty_var)
                            penalties.append(penalty_var)
        return penalties
        #work_requestsのペナルティと合わせて目的関数に加算する様にする

    def get_porifa_week_num(self):
        """
        火曜日と金曜日にポリファーマシー開催可能週を算出する
        - 第1週〜第3週目までの火曜日と金曜日の休み希望を調査する
        - 金曜：第1週もしくは第2週の金曜日、メンバーが全員参加可能な週を算出する
        - 開催可能週が複数あれば火曜日の休み希望がない方を優先する
        - それでも区別なければ早い方を優先する
        
        - 火曜：金曜開催が第1週の場合→第2週目の火曜日に開催
        -     金曜開催が第2週の場合→第3週目の火曜日に開催
        
        - 決定した火曜日と金曜日のポリファ開催週を返す
        return self.porifa_tuesday_week_num,self.porifa_friday_week_num
        
        work_constraintsのポリファ配置で決まった週の火曜日と金曜日にポリファを開催
        開催する日は他病棟フロアの必要人数を減らす・緩和する
        """
        #TODO: ポリファーマシー対応可能スタッフの抽出
        available_tuesday_weeks = []
        available_friday_weeks = []
        for day in range(1,self.days +1):
            #火曜日ver
            #火曜日かどうか,祝日でないかの判定
            if datetime(self.year,self.month,day).weekday()==1 and not self._is_holiday(day):
                #初期化
                self.porifa_tuesday_week_num=0
                self.porifa_friday_week_num=0
                
                assigned_staff_porifa = []#ポリファーマシー対応可能スタッフのリスト
                required_porifa_staff = []#必須メンバーのリスト
                assigned_porifa_ids = []#perstaff制約用
                
                
                floor_porifa_id = 11 #ポリファーマシーのフロアID
                section_configs = {
                        'ポリファーマシー':{
                            'section_id': floor_porifa_id,
                            'assigned_list': assigned_staff_porifa,
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
                    porifa_staff_ids=assigned_porifa_ids,
                )
                
                #第何週かを取得
                week_num = (day -1)//7 +1
                #assigned_staff全員において休み希望がない、当直の翌日でない条件を満たしているか確認をする
                if assigned_porifa_ids:
                    for staff in assigned_porifa_ids:
                        staff_requests = self.hope_list.loc[staff]
                        is_day_off_request = staff_requests.iloc[day] ==0
                        is_oncall_next = False#TODO:当直変数から判定する
                        if is_day_off_request or is_oncall_next:
                            print(f"Day{day}はスタッフ{staff}の休み希望もしくは当直明けのため、ポリファーマシー開催不可とします。")
                            break     
                        else:#全員が条件を満たしている場合
                            if week_num in [1,2,3]:
                                available_tuesday_weeks.append(week_num)#開催可能な火曜の週を追加する
            #金曜日ver
            if datetime(self.year,self.month,day).weekday()==4 and not self._is_holiday(day):
                #第何週かを取得
                week_num = (day -1)//7 +1
                #初期化
                self.porifa_friday_week_num=0
                assigned_staff_porifa = []#ポリファーマシー対応可能スタッフのリ
                required_porifa_staff = []#必須メンバーのリスト
                assigned_porifa_ids = []#perstaff制約用
                section_configs = {
                        'ポリファーマシー':{
                            'section_id': floor_porifa_id,
                            'assigned_list': assigned_staff_porifa,
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
                    porifa_staff_ids=assigned_porifa_ids,
                )
                #assigned_staff全員において休み希望がない、当直の翌日でない条件を満たしているか確認をする
                if assigned_porifa_ids  :
                    for staff in assigned_porifa_ids:
                        staff_requests = self.hope_list.loc[staff]
                        is_day_off_request = staff_requests.iloc[day] ==0
                        is_oncall_next = False#TODO:当直変数から判定する
                        if is_day_off_request or is_oncall_next:
                            print(f"Day{day}はスタッフ{staff}の休み希望もしくは当直明けのため、ポリファーマシー開催不可とします。")
                            break     
                        else:#全員が条件を満たしている場合
                            if week_num in [1,2,3]:
                                available_friday_weeks.append(week_num)#開催可能な金曜の週を追加する
            #すべての週が可能であれば早い方を優先する
        #候補週の整理　日付ごとでループして増えた分を削除
        available_tuesday_weeks = list(set(available_tuesday_weeks))
        available_friday_weeks = list(set(available_friday_weeks))
        #可能な曜日のうち、金曜日ー翌週の火曜日が連日している週を優先して選択する
        for week in available_friday_weeks:
            if week+1 in available_tuesday_weeks:
                self.porifa_friday_week_num = week
                self.porifa_tuesday_week_num = week +1
                print(f"第{week}週の金曜日と第{week+1}週の火曜日が両方ともポリファーマシー開催可能な週のため、金曜日を第{week}週、火曜日を第{week+1}週に選択します。")
                break
        print(f"選択されたポリファーマシー開催週: 火曜日第{self.porifa_tuesday_week_num}週, 金曜日第{self.porifa_friday_week_num}週")    
        return self.porifa_tuesday_week_num,self.porifa_friday_week_num