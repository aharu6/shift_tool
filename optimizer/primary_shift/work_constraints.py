from optimizer.base_constraint import BaseConstraint
from config.floor_mapping import FLOOR_MAPPING
import random
import pandas as pd
import datetime
class WorkConstraints(BaseConstraint):
    """勤務に関する基本制約"""
    def apply(self):
        self.eligible_sections = self._get_eligible_section_constraints()#割り当て可能な業務名の制約を取得
        self._add_basic_constraints()#専属業務は1人1日1セクションのみ
        #self._get_eligible_section_constraints()#割り当て可能な業務名の制約
        #self.add_on_call_primary_section_constraint()#当直日に専属業務を休みにしない
        #self.add_on_call_day_off_nextday_constraints()#当直明けの制約を適用
        #self.add_day_off_oncallnextday()#明けの次の日はなるべく休みにする
        #self.add_section_requests()#セクションごとの配置数人
#        self.add_consecutive_work_constraints()
        #self.add_mandatory_day_off_constraints()#7日間に1日は休み
        
    def _add_basic_constraints(self):
        """専属業務は1人1日1セクションのみ"""
        # 1. 専属業務は1人1日1セクションのみ
        for staff in self.staff.index:
            #primary_sections のうち、割り当て可能なセクションのみを対象とする
            staff_primary_sections = [s for s in self.primary_sections if s in self.eligible_sections[staff]]
            #staff_primary_sectionsが空の場合はデフォルトのself.staff_primary_sectionsを使用
                
            for day in range(1, self.days + 1):
                """if not staff_primary_sections:
                    #特に指定がない場合は割り当て可能な業務でランダムに選択する TODO：必要人数があるから、割り当て可能な業務の中から選んでもらう？
                    available_sections = list(self.primary_sections)
                    print(f"スタッフ{staff}のデフォルトの専属業務セクション: {available_sections}")
                    if available_sections:
                        staff_primary_sections =available_sections
                    else:
                        print(f"警告: スタッフ{staff}に割り当て可能な専属業務セクションがありません。")
                        continue
                """    
                    
                self.model.Add(
                    sum(self.shifts[(staff, day, section)] for section in staff_primary_sections) <= 1
                )
                
                for c_section in self.concurrent_sections:
                    for section in staff_primary_sections:
                        # 2. 兼務業務は専属業務がある場合のみ割り当て可能
                        # 専属業務がない場合は兼務業務も割り当てない
                        self.model.Add(
                            self.concurrent_shifts[(staff, day, c_section)] <= self.shifts[(staff, day, section)]
                        )    
                        
        
    def _get_eligible_section_constraints(self):
        """
        スタッフ条件.xlsxによる割り当て可能な業務名の制約
        出勤の際に割り当てる業務はFloor,もしくはfloor2に制約している業務のみとする。
        floor  、flor2,floor3の定義
        - 化療：化療と調剤室
        - 調剤室：調剤室のみ
        - DI: DIと調剤室,所属病棟
        - ただし、name=6はDIのみ
        - 外来：外来のみ
        - 1-2階：1-2階、調剤室、所属病棟
        - 3階：3階、調剤室、所属病棟
        - 4階：4階、調剤室、所属病棟
        - 5階：5階、調剤室、所属病棟
        - name=0：医療安全・感染管理のみ
        
        """
        eligable_sections_dict = {}
        
        for staff in self.staff.index:
            eligable_sections = []
            floor = self.staff.loc[staff,'Floor']
            floor2 = self.staff.loc[staff,'Floor2']
            floor3 = self.staff.loc[staff,'Floor3'] 
            
            #name==6はDIのみ
            if staff == 6:
                eligable_sections = [8]  # DIのセクションID
            #floorが有効な値の場合
            else:
                if pd.notna(floor) and floor != '':
                    #floorごとに対応したprimary_sectionを追加
                    match floor:
                        case 1:#1-2
                            eligable_sections = [4,1]  # 1-2階、調剤室
                        case 2:#DI
                            eligable_sections = [8,1]  # DI
                            #各スタッフの所属病棟を取得
                            if floor2 ==1:
                                eligable_sections.append(4)  # DI、調剤室、1-2階
                            elif floor2 ==3:
                                eligable_sections.append(5)  # DI、調剤室、3階
                            elif floor2 ==4:
                                eligable_sections.append(6)  # DI、調剤室、4階
                            elif floor2 ==5:
                                eligable_sections.append(7)  # DI、調剤室、5階
                            elif floor2 ==6:
                                eligable_sections.append(9)  # DI、調剤室、化療
                            else:
                                eligable_sections = [8,1]  # DI、調剤室
                        case 3:#3
                            eligable_sections = [5,1]  # 3階、調剤室
                            if floor2 ==2:
                                eligable_sections.append(4)  # 1-2階
                            elif floor2 ==3:
                                eligable_sections.append(5)  # 3階
                            elif floor2 ==4:
                                eligable_sections.append(6)  # 4階
                            elif floor2 ==5:
                                eligable_sections.append(7)  # 5階
                            elif floor2 ==6:
                                eligable_sections.append(9)  # 化療

                            if floor3==11:
                                eligable_sections.append(11)  # 入退院センター
                        case 4:#4
                            eligable_sections = [6,1]  # 4階、調剤室
                            if floor2 ==2:
                                eligable_sections.append(4)  # 1-2階
                            elif floor2 ==3:
                                eligable_sections.append(5)  # 3階
                            elif floor2 ==4:
                                eligable_sections.append(6)  # 4階
                            elif floor2 ==5:
                                eligable_sections.append(7)  # 5階
                            elif floor2 ==6:
                                eligable_sections.append(9)  # 化療
                            if floor3==11:
                                eligable_sections.append(11)  # 入退院センター
                        case 5:#5
                            eligable_sections = [7,1]  # 5階、調剤室
                        case 6:#化療
                            eligable_sections = [9,1]  # 化療、調剤室
                            if floor2 ==8:
                                eligable_sections.append(1)  # 調剤室
                            if floor3==11:
                                eligable_sections.append(11)  # 入退院センター
                        case 8:#調剤
                            eligable_sections = [1]  # 調剤室
                            if floor2==11:
                                eligable_sections.append(11)  # 入退院センター
                            if floor3==12:
                                eligable_sections.append(12)  # RI
                        case 9:#外来
                            eligable_sections = [16]  # 外来
                            if floor2==11:
                                eligable_sections.append(11)  # 入退院センター
                            if floor3==12:
                                eligable_sections.append(12)  # RI
                        case 10:#部長（感染管理対応可能）
                            eligable_sections = [14]  # 医療安全・感染管理
                        case _:
                            print(f"警告: スタッフ{staff}のFloorの値が不正です: {floor}")
                else:
                    print(f"警告: スタッフ{staff}のFloorの値が欠損しています。")
                            
                        
            
            eligable_sections_dict[staff] = eligable_sections
            print(f"スタッフ{staff}の割り当て可能なセクション: {eligable_sections}")
            
        return eligable_sections_dict

    def add_am_pm_consistency_constraint(self):
        """
        午前シフトと午後シフトの担当者をなるべく一致
        
        """
        print("午前・午後シフト一致制約を適用します。")
    
    def add_on_call_primary_section_constraint(self):
        """
        当直に割り当てられている日に専属業務を休みにしない !=0
        - 当直の次の日は明けを設定する 17
        - ハード制約
        - 明けは休みとして設定する
        """
        print("当直日に専属業務を休みにしない制約を適用します。")
        print("当直の次の日は明けを設定し、専属業務は休みにします。")
        for staff in self.staff.index:
            for day in range(1, self.days + 1):
                oncall_assigned = []
                # その日に当直が割り当てられているか確認
                for other_staff in self.staff.index:
                    if other_staff == staff:
                        continue
                    key1 = (staff, other_staff, day)
                    key2 = (other_staff, staff, day)
                    if key1 in self.night_shifts:
                        oncall_assigned.append(self.night_shifts[key1])
                    if key2 in self.night_shifts:
                        oncall_assigned.append(self.night_shifts[key2])
                    
                # 当直が実際に割り当てられている場合のみ制約を追加
                if oncall_assigned:
                    # 当直がある場合、専属業務は休み以外にする
                    staff_primary_sections = [s for s in self.primary_sections if s in self.eligible_sections[staff] and s != 0]
                    if staff_primary_sections:
                        self.model.Add(
                            sum(oncall_assigned) <= sum(
                                self.shifts[(staff, day, section)] for section in staff_primary_sections
                            )
                        )
                        if day < self.days:
                            # 当直の次の日は明けを設定し、専属業務は休みにする
                            self.model.Add(
                                sum(oncall_assigned) <= self.shifts[(staff, day + 1, 17)]
                            )
                        
    
    def add_on_call_day_off_nextday_constraints(self):
        """
        当直の翌日は明けを設定し、病棟業務に割り当てない制約
        """
        print("当直の次の日は明けを設定し、病棟業務に割り当てない制約を適用します。")
        
        # 病棟業務のセクションID
        floor_sections = [4, 5, 6, 7, 8, 9, 11, 12]  # 1-2階、3階、4階、5階、DI、化療、入退院、RI
        
        for staff in self.staff.index:
            for day in range(1, self.days + 1):
                if day > 1:
                    # 前日に当直があった場合、当日は明けを設定
                    if (staff, day-1, 1) in self.night_shifts:
                        # 前日の当直が1の場合、当日は明け(17)を1にする
                        self.model.Add(
                            self.shifts[(staff, day, 17)] == 1
                        ).OnlyEnforceIf(self.night_shifts[(staff, day-1, 1)])
                        
                        # 当日が明けの場合、病棟業務には割り当てない
                        for section in floor_sections:
                            if section in self.eligible_sections[staff]:
                                self.model.Add(
                                    self.shifts[(staff, day, section)] == 0
                                ).OnlyEnforceIf(self.shifts[(staff, day, 17)])
                            print(f"スタッフ{staff}の当直翌日の病棟業務割り当て制約を適用しました。")
    
    def add_day_off_oncallnextday(self):
        """
        明けの次の日はなるべく休みにする
        - ソフト制約
        - 出勤希望があれば出勤にする、
        """
        print("明けの次の日はなるべく休みにします")
        for staff in self.staff.index:
            for day in range(1,self.days):
                penalry_var = self.model.NewBoolVar(f'dayoff_oncallnextday_penalty_{staff}_{day}')
                #明け == 17があるかの確認
                # 前日が明けの場合、当日を休みにすることを推奨（ソフト制約）
                if day+1<=self.days:
                    self.model.Add(
                        self.shifts[(staff, day+1, 0)] == 1
                    ).OnlyEnforceIf(self.shifts[(staff, day, 17)])
                
    ##配置
    def add_section_requests(self):
        """
        1～2階は月～土は3名
        （name :[7,10,11,14]のうち1人は必ず出勤にする）
        - 日祝日は0名
        - floor=1-2のうちから、月～土は3名選出する
        - スタッフ条件に「1人は必ず出勤にする」の対象者を追加する
        - 選出メンバーの内にname :[7,10,11,14]を必ず1人含める
        """
        print("セクションごとの配置人数の制約を適用します。")
        #月〜土はflor=1-2が3名必要
        for day in range(1, self.days + 1):
            # primarty_sectionでfloor=1-2に対応するセクションID
            floor_1_2_section_id = 4
            #3F
            floor_3_section_id = 5
            #4F
            floor_4_section_id = 6
            #5F
            floor_5_section_id = 7
            #化学療法
            floor_chemo_secion_id = 9
            #DI
            floor_di_section_id = 8
            #入退院センター
            floor_nyutain_section_id = 11
            #RI
            floor_ri_section_id = 12
                            
            assigned_staff_12 = []
            assigned_staff_3 = []
            assigned_staff_4 = []
            assigned_staff_5 = []
            assigned_staff_chemo = []
            assigned_staff_di = []
            assigned_staff_nyutain = []
            assigned_staff_ri = []
            
            required_staff_12 = ["7","10","11","14"]
            required_staff_12_assigned = [] #12Fで必須メンバーが割り当てられた変数リスト
            
            for staff in self.staff.index:
                if floor_1_2_section_id in self.eligible_sections[staff]:
                    assigned_staff_12.append(self.shifts[(staff, day, floor_1_2_section_id)])
                    if staff in required_staff_12:
                        required_staff_12_assigned.append(self.shifts[(staff,day,floor_1_2_section_id)])
                if floor_3_section_id in self.eligible_sections[staff]:
                    assigned_staff_3.append(self.shifts[(staff, day, floor_3_section_id)])
                if floor_4_section_id in self.eligible_sections[staff]:
                    assigned_staff_4.append(self.shifts[(staff, day, floor_4_section_id)])
                if floor_5_section_id in self.eligible_sections[staff]:
                    assigned_staff_5.append(self.shifts[(staff, day, floor_5_section_id)])
                if floor_chemo_secion_id in self.eligible_sections[staff]:
                    assigned_staff_chemo.append(self.shifts[(staff, day, floor_chemo_secion_id)])
                if floor_di_section_id in self.eligible_sections[staff]:
                    assigned_staff_di.append(self.shifts[(staff, day, floor_di_section_id)])
                if floor_ri_section_id in self.eligible_sections[staff]:
                    assigned_staff_ri.append(self.shifts[(staff, day, floor_ri_section_id)])
                    
            """日曜祝日は0人"""
            weekend = [7]
            holiday = self.holidays
            is_holiday = False
            for h in holiday:
                if h[0].day == day:
                    is_holiday = True
                    break
                    
            """12階、3階、4階、5階:日曜祝日は0人"""
            if day == 7 or is_holiday:
                self.model.Add(
                    sum(assigned_staff_12) ==0
                )
                self.model.Add(
                    sum(assigned_staff_3) ==0
                )
                self.model.Add(
                    sum(assigned_staff_4) ==0
                )
                self.model.Add(
                    sum(assigned_staff_5) ==0
                )
                continue
            
            """12F:weekdayの場合、3人配置"""
            if day not in weekend and not is_holiday:    
                if assigned_staff_12:
                    self.model.Add(
                        sum(assigned_staff_12) >=3
                    )

                #必須メンバーから1人は必ず割り当てる
                if required_staff_12_assigned:
                    self.model.Add(
                        sum(required_staff_12_assigned) >=1
                    )
                
                        
            """
            3階は火曜のみ5名、他は4名。
            - 日曜祝日は0名、上で定義済み
            """
            if day==2:
                if assigned_staff_3:
                    self.model.Add(
                        sum(assigned_staff_3) >=5
                    )               
            else:
                if assigned_staff_3:
                    self.model.Add(
                        sum(assigned_staff_3) >=4
                    )
                    
            """
            4階：月のみ5名、他は4名。
            - 日曜祝日は0名、上で定義済み
            """
            if day==1:
                if assigned_staff_4:
                    self.model.Add(
                        sum(assigned_staff_4) >=5
                    )
            else:
                if assigned_staff_4:
                    self.model.Add(
                        sum(assigned_staff_4) >=4
                    )
            """
            5階：連休明けでない火曜は4名、月・水は5名、木～土は4名
            - 日曜祝日は0名、上で定義済み
            - 連休明けの定義：前日が祝日、もしくは祝日の次の日が火曜日の場合
            - 連休明け火曜は5名
            - それ以外の火曜は4名
            """
            if day==2 and day-1 in holiday:#連休明け火曜
                if assigned_staff_5:
                    self.model.Add(
                        sum(assigned_staff_5) >=5
                    )
            if day==1 or day==3:#月・水
                if assigned_staff_5:
                    self.model.Add(
                        sum(assigned_staff_5) >=5
                    )
            if day==2:#通常の火曜は0名
                if assigned_staff_5:
                    self.model.Add(
                        sum(assigned_staff_5) >=4
                    )
            else:
                if assigned_staff_5:
                    self.model.Add(
                        sum(assigned_staff_5) >=4
                    )
            
            """
            化学療法
            - 育休中のスタッフがいる場合、月〜金は3名
            - hope_list == 3(育休)
            - 育休中のスタッフがいない場合、月〜金は4名
            - 育休に関わらず、土曜日は2名
            - 日曜祝日は0名、上で定義済み
            
            """
            if day not in weekend and not is_holiday:#月〜金
                # 育休中のスタッフがいるか確認、化学療法所属かつ育休==True
                on_maternity_leave = False
                for staff in self.staff.index:
                    if (self.staff.loc[staff,'Floor'] == 9) and (self.hope_list.loc[staff].iloc[day-1] == 3):
                        on_maternity_leave = True
                        break
                if on_maternity_leave:
                    if assigned_staff_chemo:
                        self.model.Add(
                            sum(assigned_staff_chemo) >=3
                        )
                else:
                    if assigned_staff_chemo:
                        self.model.Add(
                            sum(assigned_staff_chemo) >=4
                        )
            elif day ==6:#土曜日
                if assigned_staff_chemo:
                    self.model.Add(
                        sum(assigned_staff_chemo) >=2
                    )
    
            """
            DI
            - 2月前、の週の5日間は1日2名 薬審:偶数月の第一木曜日
            - 1名になる日は月曜日以外なら可
            - それ以外は月のみ2名、火～土は1名。
            - 日曜祝日は0名、上で定義済み
            """
            yakushin_month = [2,8,10,12]
            pre_yakushin_month = [(m-1) if m>1 else 12 for m in yakushin_month]
            if self.month in pre_yakushin_month:
                #前の月の最終5日間を取得
                last_week_days = [d for d in range(self.days-4,self.days +1)]
                print(f"DIの前月最終5日間: {last_week_days}")
                if day in last_week_days:
                    if assigned_staff_di:
                        self.model.Add(
                            sum(assigned_staff_di) >=2
                        )
                        
            else:
                if day==1:#月曜
                    if assigned_staff_di:
                        self.model.Add(
                            sum(assigned_staff_di) >=2
                        )
                    else:#火〜土
                        if assigned_staff_di:
                            self.model.Add(
                                sum(assigned_staff_di) >=1
                            )
                            
                
            """
            調剤室
            - 調剤室は監査者を含めて、月～木が入退院センター担当含めて7名。
            - 金曜は隔週で午前7名、午後6名。
            - 土はケモから2名出勤(FLOOR2を利用)+入退院セ担当ふくめて午前6名、午後5名。
            - 奇数週が午前７名、午後６名（監査者を含めて）
            - 偶数週が午前６名、午後５名(監査者を含めて)

            """
            
            
            """
            入退院センター 
            - 月〜土は1名
            - 
            """
            if day not in weekend and not is_holiday:
                if assigned_staff_nyutain:
                    self.model.Add(
                        sum(assigned_staff_nyutain) >=1
                    )
                    
            """
            RI
            - 月〜土は1名
            - TODO:割り振りの優先度 name == > name == > name == > 条件シートの優先度
            """
            if day not in weekend and not is_holiday:
                if assigned_staff_ri:
                    self.model.Add(
                        sum(assigned_staff_ri) >=1
                    )
            
            """
            感染管理
            - 月〜土に1日1人
            - 当直明けの日は配置しない
            - 対応可能スタッフ: スタッフ0（専属）、Floor==10（部長）
            """
            assigned_staff_infection = []
            
            for staff in self.staff.index:
                if 14 in self.eligible_sections[staff]:
                    # 当直明けの日は感染管理に配置しない（ハード制約）
                    if day > 1:
                        self.model.Add(
                            self.shifts[(staff, day, 14)] == 0
                        ).OnlyEnforceIf(self.shifts[(staff, day, 17)])
                    
                    assigned_staff_infection.append(self.shifts[(staff, day, 14)])
                    # デバッグ用: 感染管理対応可能なスタッフを表示
                    staff_floor = self.staff.loc[staff, 'Floor'] if pd.notna(self.staff.loc[staff, 'Floor']) else 'N/A'
                    print(f"[感染管理] スタッフ{staff}（Floor={staff_floor}）を配置可能スタッフとして登録")
            
            # 平日の場合、感染管理に最低1人配置
            # 当直明け、休み希望の日は最低人数の制約を適用しない
            if day not in weekend and not is_holiday:
                if assigned_staff_infection:
                    self.model.Add(
                        sum(assigned_staff_infection) >=1
                    )
                else:
                    self.model.Add(sum(assigned_staff_infection) >=0)
                    print(f"警告: 感染管理に配置可能なスタッフがいません。日付: {day}")
                    

        
    def add_consecutive_work_constraints(self):
        """
        連続出勤の制限
        - 当直明けを含めると6日まで
        - 休み0以外のprimary_sectionが7日以上連続しないようにする
        """
        
        for staff in self.staff.index:             
            # 7日間の連続する期間をチェック
            for start_day in range(1, self.days - 6 + 1):
                # いずれかのwork_sectionに割り当てられた日数の合計が6日以内
                #0以外のセクションを指定 1~16
                self.model.Add(
                    sum(
                        self.shifts[(staff, start_day + offset_day, 14)]
                        for offset_day in range(7)
                    ) <= 6
                )
                #すべての
                
    #7日間に1日は休みになる
    def add_mandatory_day_off_constraints(self):
        """
        7日間に1日は必ず休みにする
        月末付近の日数不足にも対応
        """
        print("7日間に1日休みの制約を適用します。")
        for staff in self.staff.index:
            # 割り当て可能なセクションに休み(0)が含まれているか確認
            if 0 not in self.eligible_sections.get(staff, []):
                print(f"警告: スタッフ{staff}の割り当て可能セクションに休み(0)が含まれていません")
                continue
            
            # 日数が7日未満の場合は全期間で1日休みを確保
            if self.days < 7:
                self.model.Add(
                    sum(
                        self.shifts[(staff, day, 0)]
                        for day in range(1, self.days + 1)
                    ) >= 1
                )
                continue
            
            # 7日間のウィンドウごとに休みを確保（ソフト制約に変更）
            for start_day in range(1, self.days - 6 + 1):
                # ペナルティ変数を使用してソフト制約化
                penalty_var = self.model.NewBoolVar(f'no_dayoff_penalty_{staff}_{start_day}')
                
                # 7日間で1日以上休みがある場合、ペナルティなし
                self.model.Add(
                    sum(
                        self.shifts[(staff, start_day + offset_day, 0)]
                        for offset_day in range(7)
                    ) >= 1
                ).OnlyEnforceIf(penalty_var.Not())
                
                # ペナルティをなるべく避ける（目的関数で最小化）
                # この変数を後で目的関数に追加する必要があります
