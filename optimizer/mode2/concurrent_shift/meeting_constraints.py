from datetime import datetime
import pandas as pd
from optimizer.method.base_constraint import BaseConstraint
from config.forced_off_hope_values import FORCED_OFF_HOPE_VALUES
from config.objective_weights import (
    WEIGHT_FIXED_MANAGER_MEETING,
    WEIGHT_SECOND_FRIDAY_CONFERENCE,
    WEIGHT_FIXED_MEDICAL_SAFETY_WORKING_GROUP,
    WEIGHT_FIXED_GENERAL_MEETING,
    WEIGHT_FIXED_YAKUSHIN_MEETING,
)
class MeetingConstraints(BaseConstraint):
    """会議に関する制約"""
    def apply(self):
        meeting_penalty_groups =[
            ("manager_meeting",WEIGHT_FIXED_MANAGER_MEETING,self.fixed_manager_meeting()),
            ("second_friday_conference",WEIGHT_SECOND_FRIDAY_CONFERENCE,self.second_friday_conference()),
            ("medical_safety_working_group",WEIGHT_FIXED_MEDICAL_SAFETY_WORKING_GROUP,self.fixed_medical_safety_working_group()),
            ("general_meeting",WEIGHT_FIXED_GENERAL_MEETING,self.general_meeting()),
            ("yakushin_meeting",WEIGHT_FIXED_YAKUSHIN_MEETING,self.yakushin()),
        ]
        
        for term_name,weight,penalties in meeting_penalty_groups:
            if penalties:
                self.optimizer.register_objective_term(
                    term_name,
                    weight *sum(penalties),
                )

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
        - 当日休みの場合は配置しない
        - Floor=外来,主任以上=Trueは除く
        - 当日学会、研修の場合は配置しない
        - 当直明けを除外する==当直変数になるべく役職者会議前日に当直を割り当てないようにする
        - 前月末当直&会議日が月初の場合は配置しない（当直明けのため）当日○の日
        """
        meeting_section_id = 6#役職者会議の兼務業務ID
        penalties = []
        
        mondays = [
            day 
            for day in range(1,self.days +1)
            if datetime(self.year,self.month,day).weekday() == 0
        ]
        
        for staff in self.staff.index:
            if self.staff.loc[staff,'主任以上']!=True:
                continue
            
            floor_values = [
                self._get_staff_column_value(staff,column)
                for column in ("Floor","Floor2","Floor3")
            ]
            #外来部門所属かどうかを判定
            is_outpatient = any(
                pd.notna(value) and value ==9
                for value in floor_values
            )
            for index,day in enumerate(mondays):
                if index % 2 !=0:
                    continue
                
                meeting_var = self.optimizer.get_concurrent_assignment_var(
                    staff,day,meeting_section_id
                )    
                hope_value = self._get_hope_value(staff,day,default=7)#当日休み希望
                
                is_unavailable_by_hope = self._hope_matches(
                    hope_value,
                    FORCED_OFF_HOPE_VALUES | {6,11}#6:学会,11:研修
                )
                is_attending = self.optimizer.get_attendance_status(staff,day)
                
                # 当日出勤可能かどうかを判定
                if not is_attending or is_unavailable_by_hope or is_outpatient:
                    self.model.Add(meeting_var == 0)
                    continue
                
                penalty = self.model.NewBoolVar(
                    f"manager_meeting_penalty_{staff}_{day}"
                )
                self.model.Add(meeting_var == 1).OnlyEnforceIf(penalty.Not())
                self.model.Add(meeting_var == 0).OnlyEnforceIf(penalty)
                penalties.append(penalty)
                
        return penalties

    def second_friday_conference(self):
        """
        ソフト制約
        - 主任以上かつDIかつ、課長のスタッフ
        - 第二金曜日は出勤
        - 当日非出勤であれは配置しない（非出勤には当直明けも含む）
        - 学会・研修会の場合は配置しない
        """
        meeting_section_id = 7#　病棟担当者カンファレンスの兼務業務セクションID
        penalties = []
        
        fridays = [
            day
            for day in range(1,self.days + 1)
            if datetime(self.year,self.month,day).weekday() ==4
        ]
        if len(fridays) < 2:
            return penalties
        
        day = fridays[1]
        
        for staff in self.staff.index:
            if self.staff.loc[staff,'主任以上']!=True:
                continue
            
            floors = {
                self.staff.loc[staff,'Floor'],
                self.staff.loc[staff,'Floor2'],
                self.staff.loc[staff,'Floor3'],
            }
            # 13:課長、2:DI
            if 13 not in floors or 2 not in floors:
                continue
            # 第二金曜日の会議に出席するかどうかの判定
            meeting_var = self.optimizer.get_concurrent_assignment_var(
                staff,day,meeting_section_id
            )
            hope_value = self._get_hope_value(staff,day,default=7)
            unavailable_by_hope = self._hope_matches(
                hope_value,
                FORCED_OFF_HOPE_VALUES |{6,11},#学会、研修会
            )
            
            if (
                not self.optimizer.get_attendance_status(staff,day)
                or unavailable_by_hope
            ):
                self.model.Add(meeting_var == 0)
                continue
            
            # 第二金曜日の会議に出席するかどうかのペナルティを設定
            penalty = self.model.NewBoolVar(
                f"second_friday_congerence_penalty_{staff}_{day}"
            )
            self.model.Add(meeting_var == 1).OnlyEnforceIf(penalty.Not())
            self.model.Add(meeting_var == 0).OnlyEnforceIf(penalty)
            penalties.append(penalty)
        return penalties
    
    def fixed_medical_safety_working_group(self):
        """
        病棟担当役職者は・第3金曜日は臨床薬剤課役職者会議のため関係する役職者は全員出勤(ソフト制約)
        - 非出勤日は対象外
        - 学会・研修会の場合は対象外
        - 主任以上が対象
        - 第3金曜日が対象
        - 対象フロアのスタッフが対象
        
        """
        penalties = []
        meeting_section_id = 7# 臨床薬剤課役職者会議の兼務業務セクションID
        section_id_by_floor = {
            4: 1,
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

        day = fridays[2]
        
        
        for staff in self.staff.index:
            if self.staff.loc[staff, '主任以上'] != True:
                continue
            
            # 出勤状況や希望が合わない場合はスキップ
            if (
                not self.optimizer.get_attendance_status(staff,day)
                or self._hope_matches(
                    self._get_hope_value(staff,day,default=7),
                    FORCED_OFF_HOPE_VALUES | {6,11},
                )
            ):
                continue
            
            floor = self._get_staff_column_value(staff,"Floor")
            # 対象外のフロアのスタッフはスキップ
            #6:化療, 8:調剤室, 9:外来, 10:部長のフロアは対象外
            if pd.isna(floor) or floor in {6,8,9,10}:
                continue
            
            section_id = section_id_by_floor.get(floor)
            # 対象外のセクションのスタッフはスキップ
            if (
                section_id is None
                or section_id not in self.get_eligible_sections.get(staff, [])
            ):
                continue
            
            meeting_var = self.optimizer.get_concurrent_assignment_var(
                staff,day,meeting_section_id
            )
            penalty = self.model.NewBoolVar(
                f"medical_safety_meeting_assignment_penalty_{staff}_{day}"
            )
            self.model.Add(meeting_var == 1).OnlyEnforceIf(penalty.Not())
            self.model.Add(meeting_var == 0).OnlyEnforceIf(penalty)
            penalties.append(penalty)
            
        return penalties
                    
    #第四金曜日は薬剤部連絡会のため、役職者は全員出勤(ソフト制約)
    def general_meeting(self):
        """
        - 第四金曜日
        - 役職者はなるべく休みにしない
        - 非出勤日は対象外
        - 学会・研修会は対象外
        
        """
        meeting_section_id = 17 #薬剤部連絡会の兼務業務セクションID
        penalties = []
        
        fridays = [
            day
            for day in range(1,self.days +1)
            if datetime(self.year,self.month,day).weekday() == 4
        ]
        if len(fridays) < 4:
            return penalties
        
        day  = fridays[3]
        
        for staff in self.staff.index:
            if self.staff.loc[staff,'主任以上']!=True:
                continue
            
            meeting_var = self.optimizer.get_concurrent_assignment_var(
                staff,day,meeting_section_id
            )
            unavailable_by_hope = self._hope_matches(
                self._get_hope_value(staff,day,default = 7),
                FORCED_OFF_HOPE_VALUES |{6,11}#学会・研修会
            )
            
            if (
                not self.optimizer.get_attendance_status(staff,day)
                or unavailable_by_hope
            ):
                self.model.Add(meeting_var == 0)
                continue
            penalty = self.model.NewBoolVar(
                f"general_meeting_penalty_{staff}_{day}"
            )
            self.model.Add(meeting_var == 1).OnlyEnforceIf(penalty.Not())
            self.model.Add(meeting_var == 0).OnlyEnforceIf(penalty)
            penalties.append(penalty)
            
        return penalties

    def yakushin(self):
        """
        - 偶数月の第一木曜日が対象
        - 非出勤日は対象外（当直明けを含む）
        - 学会・研修会は対象外
        - 兼務業務内に薬審を入れる
        """
        meeting_section_id = 9 #薬審の兼務業務セクションID
        penalties = []
        
        if self.month not in {2,4,6,8,10,12}:
            return penalties
        
        first_thursdays = [
            day
            for day in range(1,self.days +1)
            if datetime(self.year,self.month,day).weekday() ==3
        ]
        if not first_thursdays:
            return penalties 
        
        day =first_thursdays[0]
        
        for staff in self.staff.index:
            if self.staff.loc[staff,'主任以上']!= True:
                continue
            
            meeting_var = self.optimizer.get_concurrent_assignment_var(
                staff,day, meeting_section_id
            )
            unvailable_by_hope = self._hope_matches(
                self._get_hope_value(staff,day,default = 7),
                FORCED_OFF_HOPE_VALUES |{6,11}#学会・研修会
            )
            
            if (
                not self.optimizer.get_attendance_status(staff,day)
                or unvailable_by_hope
            ):
                self.model.Add(meeting_var == 0)
                continue
            penalty_var = self.model.NewBoolVar(
                f"yakushin_penalty_{staff}_{day}"
            )
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
