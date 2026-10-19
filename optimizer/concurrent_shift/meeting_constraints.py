from datetime import datetime

from optimizer.base_constraint import BaseConstraint
from config.forced_off_hope_values import FORCED_OFF_HOPE_VALUES

class MeetingConstraints(BaseConstraint):
    """会議に関する制約"""
    def apply(self):
        #self.fixed_medical_safety_working_group()
        #fixed_manager_meeting()ペナルティ変数を使用するのでここで適用はしない
        #self.yakushin()ペナルティ変数を使用するのでここで適用はしない
        pass

    def _get_porifa_staff_ids(self, day):
        """指定日のポリファ対応候補スタッフIDを返す。"""
        assigned_staff_porifa = []
        required_porifa_staff = []
        assigned_porifa_ids = []
        floor_porifa_id = 11
        section_configs = {
            'ポリファーマシー': {
                'section_id': floor_porifa_id,
                'assigned_list': assigned_staff_porifa,
                'available_list': [],
                'check_day_off': True,
                'check_oncall_next': True,
                'required_staff': required_porifa_staff,
            }
        }
        self._build_section_availability(
            section_configs=section_configs,
            day=day,
            year=self.year,
            required_staff_12=None,
            required_staff_12_assigned=None,
            required_staff_12_available=None,
            di_eligible_staff_ids=None,
            porifa_staff_ids=assigned_porifa_ids,
        )
        return assigned_porifa_ids

    def _porifa_members_have_no_day_off_request(self, staff_ids, day):
        """全メンバーが当日に休み希望/研修希望/学会希望を出していないかを判定する。"""
        for staff in staff_ids:
            if self._hope_matches(self._get_hope_value(staff, day, default=7), FORCED_OFF_HOPE_VALUES):
                print(f"Day{day}はスタッフ{staff}の休み希望のため、ポリファーマシー開催不可とします。")
                return False
        return True
            

    def _collect_available_porifa_weeks(self, target_weekday):
        """指定曜日(0=月 ... 6=日)の開催可能週番号を返す。"""
        available_weeks = []
        for day in range(1, self.days + 1):
            if datetime(self.year, self.month, day).weekday() != target_weekday:
                continue
            if self._is_holiday(day):
                continue

            assigned_porifa_ids = self._get_porifa_staff_ids(day)
            if not assigned_porifa_ids:
                continue

            if self._porifa_members_have_no_day_off_request(assigned_porifa_ids, day):
                #開催可能週番号を追加
                week_num = (day - 1) // 7 + 1
                if week_num in [1, 2, 3, 4, 5]:
                    available_weeks.append(week_num)
            #当日が当直明けならば開催可能週から除外する
            
        return list(set(available_weeks))

    def fixed_manager_meeting(self):
        """
        ソフト制約
        - 役職者は第一、第三、第五月曜は役職者会議のため出勤
        - 兼務業務に役職者会議を割り当てる
        - 配置はそれぞれの所属フロアへ割り当てる
        - 休み希望があればそちらを優先する
        - Floor=外来,主任以上=Trueは除く
        - TODO:当直明けを除外する==当直変数になるべく役職者会議前日に当直を割り当てないようにする
        """
        print(f"役職者会議によるペナルティを追加します")
        penalties = []
        for staff in self.staff.index:
            if self.staff.loc[staff,'主任以上']==True:
                mondays = [day for day in range(1,self.days + 1) if datetime(self.year,self.month,day).weekday()==0]
                for i,mon in enumerate(mondays):
                    if i%2==0:
                        work_var = self.optimizer.get_primary_work_var(staff, mon)#primary_shift
                        meeting_var = self.optimizer.get_concurrent_work_var(staff, mon)#concurrent_shift
                        
                    
                        #休み希望があれば配置しない
                        
                        #当直明けは配置しない
                        had_oncall_yesterday = (
                            self.optimizer.work_constraints._get_had_oncall_yesterday_var(staff, mon)
                        )#月曜日当日を渡すと、関数が前日（日曜）の当直を確認する
                        self.model.Add(meeting_var == 0).OnlyEnforceIf(had_oncall_yesterday)
                    
                        if self._hope_matches(self._get_hope_value(staff, mon, default=7), FORCED_OFF_HOPE_VALUES):
                            print(f"{staff}は{mon}日の休み希望/慶弔休暇/育休/研修希望/学会希望のいずれかがあるため、役職者会議の出勤対象外です。")
                        #TODO:この条件あってる？外来部門所属者は除く Floor == 9は除く
                        elif self.staff.loc[staff,'Floor'] in [9]:
                            print(f"{staff}は外来部門所属のため役職者会議の出勤から除外します。")
                            pass
                        else:
                            #primary_shiftがなるべく休みにならないようにペナルティを加算
                            penalties.append(self.optimizer.get_primary_work_var(staff, mon))
                                                        
                            #なるべく兼務業務に役職者会議を割り当てる（ソフト制約）
                            assignment_penalty = self.model.NewBoolVar(
                                'assignment_penalty_'+str(staff)+'_'+str(mon)
                                )
                            self.model.Add(meeting_var==1).OnlyEnforceIf(assignment_penalty.Not())
                            self.model.Add(meeting_var==0).OnlyEnforceIf(assignment_penalty)
                            penalties.append(assignment_penalty)
                            
                            
        return penalties
        #work_requestsのペナルティと合わせて、目的関数に加算する様にする

    #diかつ課長のスタッフは第2金曜は病棟担当者カンファレンスのため出勤
    def second_friday_conference(self):
        """
        ソフト制約
        - 主任以上かつDIかつ、課長のスタッフ
        - 第二金曜日は出勤
        - 休み希望があればそちらを優先する
        - 当直制約に追加
        """
        print("病棟担当者カンファレンスの出勤希望を反映します。")
        penalties = []
        for staff in self.staff.index:
            if staff in self.staff.index:
                if self.staff.loc[staff,'主任以上']==True:
                    floors = {
                        self.staff.loc[staff,'Floor'],
                        self.staff.loc[staff,'Floor2'],
                        self.staff.loc[staff,'Floor3'],
                    }
                    if 13 in floors and 2 in floors:
                        if self.staff.loc[staff,'Floor']== 2 or self.staff.loc[staff,'Floor2']==2 or self.staff.loc[staff,'Floor3']==2:
                            fridays = [day for day in range(1,self.days + 1) if datetime(self.year,self.month,day).weekday()==4]
                            if len(fridays) < 2:
                                continue
                            second_friday = fridays[1]
                            if self._hope_matches(self._get_hope_value(staff, second_friday, default=7), FORCED_OFF_HOPE_VALUES):
                                continue
                            else:
                                penalty_var = self.model.NewBoolVar('penalty_'+str(staff)+'_'+str(second_friday))
                                self.model.Add(self.optimizer.get_primary_work_var(staff, second_friday) == 1).OnlyEnforceIf(penalty_var.Not())
                                penalties.append(penalty_var)
                                
                            
        return penalties
    
    def fixed_medical_safety_working_group(self):
        """病棟担当役職者は・第3金曜日は臨床薬剤課役職者会議のため関係する役職者は全員出勤(ソフト制約)"""
        penalties = []
        meeting_concurrent_id = 7
        section_id_by_floor = {
            4: 1,#
            8: 2,
            5: 3,
            6: 4,
            7: 5,
            9: 6,
            10: 7,
            1: 8,
            16: 9,
            26: 10,
            3: 11,
            22: 12,
            23: 13,
            14: 14,
        }

        fridays = [
            day for day in range(1, self.days + 1)
            if datetime(self.year, self.month, day).weekday() == 4
        ]
        if len(fridays) < 3:
            return penalties

        third_friday = fridays[2]
        
        
        for staff in self.staff.index:
            work_var = self.optimizer.get_primary_work_var(staff, third_friday)
            meeting_var = self.optimizer.get_concurrent_work_var(staff, third_friday)
            
            #主任以外のスタッフは対象外
            if self.staff.loc[staff, '主任以上'] != True:
                continue
            #休み希望があればスキップする
            if self._hope_matches(
                self._get_hope_value(staff, third_friday, default=7),
                FORCED_OFF_HOPE_VALUES,
            ):
                self.model.Add(work_var == 0)  # 強制的に休みにする
                self.model.Add(meeting_var == 0)  # 強制的に会議に出席させない
                
            # floorid 6:化療,floorid 8: 調剤室 floorid 9:外来, floorid 10:武長のスタッフは対象外
            if self.staff.loc[staff, 'Floor'] in [6, 8, 9, 10]:
                continue

            section_id = section_id_by_floor.get(self.staff.loc[staff, 'Floor'])
            if section_id is None or section_id not in self.get_eligible_sections.get(staff, []):
                continue
            
            # 出勤のペナルティ
            # TODO:強制出勤にするか考える
            attendance_penalty = self.model.NewBoolVar(
                f'medical_safety_meeting_attendance_penalty_{staff}_{third_friday}'
            )
            self.model.Add(work_var == 1).OnlyEnforceIf(attendance_penalty.Not())#出勤のペナルティが課されない場合
            self.model.Add(work_var == 0).OnlyEnforceIf(attendance_penalty)
            penalties.append(attendance_penalty)

            # 会議のペナルティ
            meeting_penalty = self.model.NewBoolVar(
                f'medical_safety_meeting_assignment_penalty_{staff}_{third_friday}'
            )
            self.model.Add(meeting_var == 1).OnlyEnforceIf(meeting_penalty.Not())#会議のペナルティが課されない場合
            self.model.Add(meeting_var == 0).OnlyEnforceIf(meeting_penalty)
            penalties.append(meeting_penalty)

        return penalties
                    
    #第四金曜日は薬剤部連絡会のため、役職者は全員出勤(ソフト制約)
    def general_meeting(self):
        """
        - 第四金曜日
        - 役職者はなるべく休みにしない
        - 休み希望があればそちらを優先する
        """
        print("第四金曜日の薬剤部連絡会の出勤希望を反映します。")
        penalties = []
        for staff in self.staff.index:
            if self.staff.loc[staff,'主任以上']==True:
                fridays = [day for day in range(1,self.days + 1) if datetime(self.year,self.month,day).weekday()==4]
                if len(fridays) >=4:
                    fourth_friday = fridays[3]
                    work_var = self.optimizer.get_primary_work_var(staff, fourth_friday)
                    meeting_var = self.optimizer.get_concurrent_work_var(staff, fourth_friday)
                    #休み希望がある場合はペナルティを課さない
                    if self._hope_matches(self._get_hope_value(staff, fourth_friday, default=7), FORCED_OFF_HOPE_VALUES):
                        continue
                    #休み希望がなければペナルティを課す
                    else:
                        penalty_var = self.model.NewBoolVar('penalty_'+str(staff)+'_'+str(fourth_friday))
                        # 休み希望がなければ、役職者会議の出勤を強制するペナルティを課す
                        # primary_shift
                        self.model.Add(work_var == 1).OnlyEnforceIf(penalty_var.Not())
                        self.model.Add(work_var == 0).OnlyEnforceIf(penalty_var)
                        # concurrent_shift
                        self.model.Add(meeting_var == 1).OnlyEnforceIf(penalty_var.Not())
                        self.model.Add(meeting_var == 0).OnlyEnforceIf(penalty_var)
                        penalties.append(penalty_var)
        return penalties

    def yakushin(self):
        """
        - 偶数月の第一木曜日が対象
        - 役職者は薬審の日は出勤とする
        - 休み希望があれば優先する
        - primary_shiftをなるべく出勤とする
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
                        work_var = self.optimizer.get_primary_work_var(staff, first_thursday)
                        meeting_var = self.optimizer.get_concurrent_work_var(staff, first_thursday)

                        #休み希望/慶弔休暇/育休/研修希望/学会希望をチェック
                        if self._hope_matches(self._get_hope_value(staff, first_thursday, default=7), FORCED_OFF_HOPE_VALUES):#休み希望の場合は配置しない
                            self.model.Add(meeting_var==0)
                        else:
                            #なるべく休みにならないようにする==primary_shift var=1
                            penalty_var =self.model.NewBoolVar('penalty_var_'+str(staff)+'_'+str(first_thursday))
                            self.model.Add(work_var == 1).OnlyEnforceIf(penalty_var.Not())
                            self.model.Add(work_var == 0).OnlyEnforceIf(penalty_var)
                            self.model.Add(meeting_var == 1).OnlyEnforceIf(penalty_var.Not())
                            self.model.Add(meeting_var == 0).OnlyEnforceIf(penalty_var)
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
        - 開催週はCP-SATの変数で統一する
        """
        cached = getattr(self.optimizer, '_porifa_week_num_cache', None)
        if cached is not None:
            self.porifa_tuesday_week_num, self.porifa_friday_week_num = cached
            return cached

        self.porifa_tuesday_week_num = 0
        self.porifa_friday_week_num = 0

        # 火曜(1)・金曜(4)の候補週を共通ロジックで収集
        available_tuesday_weeks = self._collect_available_porifa_weeks(target_weekday=1)
        available_friday_weeks = self._collect_available_porifa_weeks(target_weekday=4)

        #可能な曜日のうち、金曜日ー翌週の火曜日が連日している週を優先して選択する
        for week in available_friday_weeks:
            porifa_tuesday_selected = self.model.NewBoolVar('porifa_tuesday_selected_week_'+str(week))
            porifa_firday_selected = self.model.NewBoolVar('porifa_friday_selected_week_'+str(week))
            
        if self.porifa_tuesday_week_num == 0 and available_tuesday_weeks:
            self.porifa_tuesday_week_num = min(available_tuesday_weeks)
            print(f"火曜日のポリファーマシー開催可能週が複数あるため、最も早い第{self.porifa_tuesday_week_num}週を選択します。")
            
        print(f"選択されたポリファーマシー開催週: 火曜日第{self.porifa_tuesday_week_num}週, 金曜日第{self.porifa_friday_week_num}週")
        result = (self.porifa_tuesday_week_num, self.porifa_friday_week_num)
        self.optimizer._porifa_week_num_cache = result
        return result

    def day16to23(self):
        """
        name6の16日から23日まで出勤希望(ソフト制約)
        - 配置はDI
        - 日曜祝日でも希望あれば叶えるので、is_non_working_dayのチェックはしない
        """
        penalties = []
        
        for staff in self.staff.index:
            floor1 = self.staff.loc[staff, 'Floor']
            floor2 = self.staff.loc[staff, 'Floor2']
            floor3 = self.staff.loc[staff, 'Floor3']
            
            #floor1-3のいずれかに13（課長が含まれる場合）
            if 13 in {floor1,floor2,floor3} and 2 in {floor1,floor2,floor3}:
                for day in range(16, 24):
                    #休み希望があればスキップする
                    if self._hope_matches(
                        self._get_hope_value(staff,day,default = 7),
                        {0,3,5,6,11},
                    ):
                        continue
                    else:
                        penalty_var = self.model.NewBoolVar('penalty'+str(staff)+'_'+str(day))
                        self.model.Add(self.optimizer.get_primary_work_var(staff, day) == 1).OnlyEnforceIf(penalty_var.Not())
                        penalties.append(penalty_var)
                        print(f"課長かつDI所属のスタッフ{staff}が16日から23日までの出勤希望を反映: day {day}")
        return penalties
            