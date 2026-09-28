from optimizer.base_constraint import BaseConstraint
from config.floor_mapping import FLOOR_MAPPING
import random
import pandas as pd
import datetime
import numbers
import jpholiday
from optimizer.concurrent_shift import MeetingConstraints
from optimizer.concurrent_shift.concurrent_constraints import ConcurrentConstraints
from config.objective_weights import (
    WEIGHT_ONCALL_NEXTDAY,
    WEIGHT_SUNDAY_HOLIDAY,
    WEIGHT_CONSECUTIVE_WORK,
    WEIGHT_FIXED_MANAGER_MEETING,
    WEIGHT_FIXED_GENERAL_MEETING,
    WEIGHT_FIXED_YAKUSHIN_MEETING,
    WEIGHT_FIXED_MEDICAL_SAFETY_WORKING_GROUP,
    WEIGHT_PORIFA_FRIDAY,
    WEIGHT_PORIFA_PAIR,
    WEIGHT_CHEMO_SATURDAY,
    WEIGHT_PRIMARY_FAIRNESS,
    WEIGHT_CONSECUTIVE_WORK_FAIRNESS,
    WEIGHT_CONSECUTIVE_OFF_FAIRNESS,
    CONSECUTIVE_WORK_FAIRNESS_TOLERANCE,
    CONSECUTIVE_OFF_FAIRNESS_TOLERANCE,
    WEIGHT_SECOND_FRIDAY_CONFERENCE,
    WEIGHT_MANAGER,
    WEIGHT_KACHO_ASSIGNMENT,
    WEIGHT_PREVIOUS_YEAR_DECEMBER_30_AVOIDANCE,
    WEIGHT_PREVIOUS_DECEMBER_31_AVOIDANCE,
    WEIGHT_PREVIOUS_JANUARY_1_AVOIDANCE,
    WEIGHT_PREVIOUS_JANUARY_2_AVOIDANCE,
    WEIGHT_PREVIOUS_JANUARY_3_AVOIDANCE,
)
from config.sections import PRIMARY_SECTIONS


class WorkConstraints(BaseConstraint):
    def __init__(self, model, optimizer):
        super().__init__(model, optimizer)
        self.meeting_constraints = MeetingConstraints(model, optimizer)
        self.concurrent_constraints = ConcurrentConstraints(model, optimizer)
        self.prev_month_oncall_staff_ids = set(getattr(optimizer, 'prev_month_oncall_staff_ids', []))
        self._had_oncall_yesterday_vars = {}
        self._work_day_vars = {}
        self._staff_max_consecutive_work_vars = {}
        self._staff_max_consecutive_off_vars = {}
        self.prev_year_end_shift = getattr(optimizer, 'prev_year_end_shift', None)

    @staticmethod
    def _maximum_candidate_assignment(section_candidates, requirements):
        """候補スタッフを1日1セクションとして割り当てられる最大人数を求める。"""
        staff_to_sections = {}
        for section_name, candidates in section_candidates.items():
            if requirements.get(section_name, 0) <= 0:
                continue
            for staff in candidates:
                staff_to_sections.setdefault(staff, []).append(section_name)

        section_slots = {
            section_name: [None] * requirements.get(section_name, 0)
            for section_name in section_candidates
            if requirements.get(section_name, 0) > 0
        }

        def assign(staff, visited):
            for section_name in staff_to_sections.get(staff, []):
                if section_name in visited:
                    continue
                visited.add(section_name)
                for slot_index, current_staff in enumerate(section_slots[section_name]):
                    if current_staff is None or assign(current_staff, visited):
                        section_slots[section_name][slot_index] = staff
                        return True
            return False

        for staff in staff_to_sections:
            assign(staff, set())
        return sum(
            current_staff is not None
            for slots in section_slots.values()
            for current_staff in slots
        )

    def _log_candidate_conflicts(self, day, section_candidates, requirements):
        active_candidates = {
            section_name: candidates
            for section_name, candidates in section_candidates.items()
            if requirements.get(section_name, 0) > 0
        }
        staff_sections = {}
        for section_name, candidates in active_candidates.items():
            for staff in candidates:
                staff_sections.setdefault(staff, []).append(section_name)

        shared_staff = {
            staff: sections
            for staff, sections in staff_sections.items()
            if len(sections) > 1
        }
        total_required = sum(requirements.get(name, 0) for name in active_candidates)
        maximum_assignment = self._maximum_candidate_assignment(
            active_candidates,
            requirements,
        )
        if shared_staff or maximum_assignment < total_required:
            print(
                f"⚠️ [全体候補診断] Day {day}: "
                f"必要枠={total_required}, 最大割当可能数={maximum_assignment}, "
                f"重複候補者数={len(shared_staff)}"
            )
            if shared_staff:
                print(f"   競合スタッフ: {shared_staff}")
            if maximum_assignment < total_required:
                print(
                    f"   セクション間競合により最大{total_required - maximum_assignment}枠が不足する可能性があります。"
                )

    def _is_prev_day_holiday(self, day):
        if day > 1:
            return self._is_holiday(day - 1)

        prev_date = self._get_date(day) - datetime.timedelta(days=1)
        return bool(jpholiday.is_holiday(prev_date))

    def _get_had_oncall_yesterday_var(self, staff, day):
        """
        前日に当直があったかどうかを表す変数を取得する
        当直はoncall_shiftより参照する
        - 前日に当直があった場合は1、なかった場合は0
        - day=1の場合は、前月末の当直担当者リストを参照する
        """
        
        cache_key = (staff, day)
        #oncall_shiftの結果を取得する
        if cache_key in self._had_oncall_yesterday_vars:
            return self._had_oncall_yesterday_vars[cache_key]

        prev_day_label = (day - 1) if day > 1 else 'prev_month_end'
        had_oncall_yesterday = self.model.NewBoolVar(
            f'had_oncall_{staff}_{prev_day_label}'
        )

        if day > 1:
            prev_day_oncall = []
            for other_staff in self.staff.index:
                if other_staff == staff:
                    continue
                # 当直ペアのキー順序は ShiftOptimizer 側で正規化して取得する
                pair_var = self.optimizer.get_oncall_pair(staff, other_staff, day - 1)
                if pair_var is not None:
                    prev_day_oncall.append(pair_var)
            if prev_day_oncall:
                self.model.AddMaxEquality(had_oncall_yesterday, prev_day_oncall)
            else:
                self.model.Add(had_oncall_yesterday == 0)
        else:
            # 前月末の当直担当者リストが与えられている場合
            # 対象スタッフ　通常通り１週間内の当直避けたり、前日の当直情報反映する
            if staff in self.prev_month_oncall_staff_ids:
                self.model.Add(had_oncall_yesterday == 1)
            else:
                self.model.Add(had_oncall_yesterday == 0)

        self._had_oncall_yesterday_vars[cache_key] = had_oncall_yesterday
        return had_oncall_yesterday
        
    """勤務に関する基本制約"""
    def apply(self):
        #事前検証：希望と制約の競合チェック
#        self._get_eligible_section_constraints()#割り当て可能な業務名の制約
        self.eligible_sections = self.get_eligible_sections#割り当て可能な業務名の制約を取得
        self._add_basic_constraints()#専属業務は1人1日1セクションのみ
        self.apply_day_off_requests()#休み希望は叶える
        self.apply_training_requests()#研修希望は叶える
        self.apply_conference_requests()#学会希望は叶える
        self.add_on_call_primary_section_constraint()#当直日に専属業務を休みにしない
        self.add_on_call_day_off_nextday_constraints()#当直明けの制約を適用
    
        sunday_holiday_penalties = self.add_sunday_holiday_work_constraints()#日曜祝日の出勤は可能な限り月1回までとする
        consecutive_work_penalties = self.add_consecutive_work_constraints()#連続勤務の制約（超過ペナルティ）を追加
        self.apply_weighted_dayworkpenalties(
            sunday_holiday_penalties,
            consecutive_work_penalties,
            )#重みづけした目的関数を設定
        """当直明けの休みの制約"""
        self.add_section_requests()#セクションごとの配置数人
        
    def _add_basic_constraints(self):
        """専属業務は1人1日1セクションのみ"""
        concurrent_only_sections = {18, 19, 20, 21, 22, 24, 27}
        # 1. 専属業務は1人1日1セクションのみ
        for staff in self.staff.index:
            #primary_sections のうち、割り当て可能なセクション＋０：休み、＋２８：研修、＋２９：学会のみを対象とする
            #get_eilgible_sectionsにて学会や研修、休みを含む所属可能セクションを取得しているので、それ以外の業務に配置されないように明示的に記載する
            staff_primary_sections = [
                s for s in self.primary_sections
                if s in self.eligible_sections[staff]
                and s not in concurrent_only_sections
            ]
            #配置対象外のセクション
            ineligible_sections = (
                [s for s in self.primary_sections 
                if s not in self.eligible_sections[staff]]
                if self.eligible_sections[staff]
                else[]
            )
            print(f"Staff: {staff}, Primary Sections: {staff_primary_sections}, Ineligible Sections: {ineligible_sections}")
            
            for day in range(1, self.days + 1):
                self.model.Add(
                    sum(self.shifts[(staff, day, section)] for section in staff_primary_sections) <= 1
                )
                # 専属業務に配置されないセクションは0にする制約を追加
                if ineligible_sections:
                    self.model.Add(
                        sum(self.shifts[(staff, day, section)] for section in ineligible_sections) == 0
                    )
                    
                for c_section in self.concurrent_sections:
                    # 2. 兼務業務は出勤している（休みでない）場合のみ割り当て可能
                    # 専属業務に「休み(0)」以外が少なくとも1つある場合のみ兼務可能
                    non_off_sections = [s for s in staff_primary_sections]  # 建設的に全ての専属業務セクションを対象とする
                    if non_off_sections:
                        self.model.Add(
                            self.concurrent_shifts[(staff, day, c_section)] <= sum(
                                self.shifts[(staff, day, section)] for section in non_off_sections
                            )
                        )
                        

    #休み希望は叶える
    def apply_day_off_requests(self):
        """
        休み希望を反映
        - 休み、育休、慶弔休暇 →すべて休みの0として扱う
        - 休みと研修希望と学会希望以外のセクションは==０不可とする
        """
        #休み希望と研修希望以外のセクション
        non_request_sections = [s for s in self.primary_sections if s not in (0, 28, 29)]  # 休み希望(0)と研修希望(28)と学会希望(29)以外のセクション
        for staff in self.staff.index:
            for day in range(1, self.days + 1):
                if self._hope_matches(self._get_hope_value(staff, day, default=7), {0}): #休み希望がある場合
                    self.model.Add(
                        sum(self.shifts[(staff, day, section)] for section in non_request_sections) == 0
                    )
                elif self._hope_matches(self._get_hope_value(staff, day, default=7), {3}):#慶弔休暇希望がある場合
                    self.model.Add(
                        sum(self.shifts[(staff, day, section)] for section in non_request_sections) == 0
                    )
        
    #研修希望は叶える
    def apply_training_requests(self):
        """
        研修希望を反映
        - 研修希望日にのみ専属業務として研修を割り当てる
        - 研修希望がある場合、その日は専属業務を休みにする
        """
        for staff in self.staff.index:
            for day in range(1,self.days +1):
                if self._get_hope_value(staff, day, default=7) == 6:  # 研修希望がある場合
                    self.model.Add(self.shifts[(staff, day, 28)] == 1)  # 研修希望がある場合、その日は研修に割り当てる
                    #研修以外のシフトを割り当てない
                    self.model.Add(
                        sum(self.shifts[(staff, day, section)] for section in self.primary_sections if section != 28) == 0
                    )
                else:
                    self.model.Add(self.shifts[(staff, day, 28)] == 0)  # 研修希望がない場合、その日は研修に割り当てない
                    
    #学会希望は叶える
    def apply_conference_requests(self):
        """
        学会希望を反映
        - 学会希望日にのみ専属業務として学会を割り当てる
        - 学会希望がある場合、その日は専属業務を休みにする
        """
        for staff in self.staff.index:
            for day in range(1,self.days +1):
                if self._get_hope_value(staff, day, default=7) == 11:  # 学会希望がある場合
                    print(f"スタッフ{staff}の{day}日の学会希望が反映されます。")
                    self.model.Add(self.shifts[(staff, day, 29)] == 1)  # 学会希望がある場合、その日は学会に割り当てる
                    #学会以外のシフトを割り当てない
                    self.model.Add(
                        sum(self.shifts[(staff, day, section)] for section in self.primary_sections if section != 29) == 0
                    )
                else:
                    self.model.Add(self.shifts[(staff, day, 29)] == 0)  # 学会希望がない場合、その日は学会に割り当てない
    #該当者は基本的に日曜祝日は休みにする
    
    def add_on_call_primary_section_constraint(self):
        """
        当直に割り当てられている日に専属業務を休みにしない !=0
        - ハード制約
        - TODO:前月の月末が当直の場合は、月初の1日も当直明けとして扱う必要がある
        """
        print("当直日に専属業務を休みにしない制約を適用します。")
        debug_no_primary_staff = []
        
        for staff in self.staff.index:
            primary_sections = [
                section
                for section in self.primary_sections
                if section in self.eligible_sections[staff]
                and section not in (0, 17, 28, 29)
            ]
            
            oncall_allowed = (
                self.staff.loc[staff,'当直'] is True
                and self.staff.loc[staff,'休職'] is False
            )
            
            if oncall_allowed and not primary_sections:
                debug_no_primary_staff.append(staff)

        if debug_no_primary_staff:
            # 研修/学会は希望が無い日にハード0固定されるため、当直強制の逃げ場にできない
            raise ValueError(f"⚠️ 当直対象だが専属業務(病棟系)を持たないスタッフがいます。\n当直のTRUE/FALSEを見直すか、対象の専属業務名を追加してください。\n"
                            f"配置を再度確認してから再実行してください。: {debug_no_primary_staff}")
            

        for staff in self.staff.index:            
            for day in range(1, self.days + 1):
                oncall_pairs = []
                # その日に当直が割り当てられているか確認
                for other_staff in self.staff.index:
                    if other_staff == staff:
                        continue
                    pair_var = self.optimizer.get_oncall_pair(staff, other_staff, day)
                    if pair_var is not None:
                        oncall_pairs.append(pair_var)
                
                if not oncall_pairs:
                    continue  # 当直のペアがない場合は制約を追加しない
                                    
                #当日当直かどうか
                oncall_today = self.model.NewBoolVar(f'oncall_today_{staff}_{day}')
                self.model.AddMaxEquality(oncall_today,oncall_pairs)
                
                #非休み・非明け・非学会・非研修の専属業務
                staff_primary_sections = [
                    s for s in self.primary_sections
                    if s in self.eligible_sections[staff] and s not in (0, 17, 28, 29)
                ]
                print(f"スタッフ{staff}の{day}日の専属業務候補: {staff_primary_sections}")
                if not staff_primary_sections:
                    #当直候補自体は残す。専属業務がない場合はその人を自動選択対象から外すだけに止める
                    continue
                        
                worked_primary = self.model.NewBoolVar(f"worked_primary_{staff}_{day}")
                self.model.Add(
                    sum(self.shifts[(staff, day, section)] for section in staff_primary_sections) >= 1
                ).OnlyEnforceIf(worked_primary) #
                self.model.Add(
                    sum(self.shifts[(staff, day, section)] for section in staff_primary_sections) == 0
                ).OnlyEnforceIf(worked_primary.Not())
                
                # 当直のときは専属業務は休み(0)でないことを強制
                self.model.Add(worked_primary == 1).OnlyEnforceIf(oncall_today)
    
    def add_on_call_day_off_nextday_constraints(self):
        """
        当直の翌日は明けを設定し、業務に割り当てない制約
        - 明けは前日に当直がある場合のみ
        - 前日に当直がない場合、明けに割り当てない
        - TODO:前月の月末が当直の場合は、月初の1日も当直明けとして扱う必要がある

        既定では厳密モードとし、当直翌日制約をハード固定する。
        緩和モードを使う場合のみ optimizer.strict_oncall_nextday = False を設定する。
        """
        strict_oncall_nextday = bool(getattr(self.optimizer, 'strict_oncall_nextday', True))#厳密モードON
        print(f"当直翌日制約: {'厳密モード' if strict_oncall_nextday else '緩和モード'}")

        # 業務のセクションID
        floor_sections = [s for s in PRIMARY_SECTIONS if s != 17]

        for staff in self.staff.index:
            for day in range(1, self.days + 1):
                had_oncall_yesterday = self._get_had_oncall_yesterday_var(staff, day)#前日に当直があったかどうかの変数を取得
                print(f"スタッフ{staff}の{day}日の前日当直変数: {had_oncall_yesterday}")
                day_off_requested = self._hope_matches(
                    self._get_hope_value(staff, day, default=7), {0, 3}
                )
                if day_off_requested and day > 1:
                    for other_staff in self.staff.index:
                        if other_staff == staff:
                            continue
                        pair_var = self.optimizer.get_oncall_pair(
                            staff,
                            other_staff,
                            day - 1,
                        )
                        if pair_var is not None:
                            self.model.Add(pair_var == 0)
                elif day_off_requested and staff in self.prev_month_oncall_staff_ids:
                    print(
                        f"[WARNING当直競合] staff={staff}, day={day}: "
                        "前月末当直と当日休み希望が競合するため、モデル上で解消できません"
                    )
                    raise ValueError(
                        f"前月末当直と当日休み希望が競合するため、staff={staff}, day={day}で制約を適用できません"
                    )

                if strict_oncall_nextday:
                    # 厳密モード: 明けは「前日当直の真偽」と完全一致させる
                    self.model.Add(self.shifts[(staff, day, 17)] == had_oncall_yesterday)
                else:
                    # 緩和モード: 前日に当直がなければ明け禁止、前日にあっても明けを選ばないことも許容する
                    self.model.Add(
                        self.shifts[(staff, day, 17)] <= had_oncall_yesterday
                    )
                    self.model.Add(
                        self.shifts[(staff, day, 17)] == 0
                    ).OnlyEnforceIf(had_oncall_yesterday.Not())

                # 当日が明けの場合,専属業務には割り当てない
                for section in floor_sections:
                    if section in self.eligible_sections[staff]:
                        self.model.Add(
                            self.shifts[(staff, day, section)] == 0
                        ).OnlyEnforceIf(self.shifts[(staff, day, 17)])

                print(f"スタッフ{staff}の{day}日の当直翌日制約を適用しました。")
    
    def add_day_off_oncallnextday(self):
        """
        明けの次の日はなるべく休みにする
        - ソフト制約
        - 出勤希望があれば出勤にする、
        """
        print("明けの次の日はなるべく休みにします")
        penalties = []
        for staff in self.staff.index:
            for day in range(1,self.days+1):
                if day <= 1:
                    continue

                penalty_var = self.model.NewBoolVar(f'dayoff_oncallnextday_penalty_{staff}_{day}')
                prev_day_ake = self.shifts[(staff, day - 1, 17)]
                today_dayoff = self.shifts[(staff, day, 0)]

                # 明け翌日に休みを入れられなかった場合のみペナルティ（ソフト制約）
                # penalty = max(0, prev_day_ake - today_dayoff)
                self.model.Add(penalty_var >= prev_day_ake - today_dayoff)
                self.model.Add(penalty_var <= prev_day_ake)

                penalties.append(penalty_var)
        return penalties

    def _has_maternity_leave_in_chemo(self, day):
        for staff in self.staff.index:
            if (self.staff.loc[staff, 'Floor'] == 9) and self._hope_matches(
                self._get_hope_value(staff, day, default=7), {3}
            ):
                return True
        return False

    def _get_section_min_requirements(self, day, weekday, is_holiday, prev_day_is_holiday):
        if weekday == 6 or is_holiday:
            return {
                '1-2F': 0,
                '3F': 0,
                '4F': 0,
                '5F': 0,
                '化療': 0,
                'DI': 0,
                '入退院センター': 0,
                '感染管理': 0,
                'ポリファーマシー': 0
            }

        is_weekday = weekday <= 4
        is_saturday = weekday == 5
        is_tuesday = weekday == 1
        is_monday = weekday == 0
        is_wednesday = weekday == 2

        five_f_required = 4
        if (is_tuesday and prev_day_is_holiday) or is_monday or is_wednesday:
            five_f_required = 5

        chemo_required = 0
        if is_weekday:
            chemo_required = 3 if self._has_maternity_leave_in_chemo(day) else 4
        elif is_saturday:
            chemo_required = 2

        yakushin_month = [2, 8, 10, 12]
        pre_yakushin_month = [(m - 1) if m > 1 else 12 for m in yakushin_month]
        di_required = 1
        if self.month in pre_yakushin_month:
            last_week_days = [d for d in range(self.days - 4, self.days + 1)]
            if day in last_week_days:
                di_required = 2
            elif is_monday:
                di_required = 2
        elif is_monday:
            di_required = 2

        return {
            '1-2F': 3,
            '3F': 5 if is_tuesday else 4,
            '4F': 5 if is_monday else 4,
            '5F': five_f_required,
            '化療': chemo_required,
            'DI': di_required,
            '入退院センター': 1,
            '感染管理': 1,
            'ポリファーマシー':0,
        }

    def _prevalidate_section_capacity(self, day, requirements, available_counts, required_staff_12_available):
        conflict_messages = []
        non_mandatory_sections = {'RI'}

        if requirements.get('1-2F', 0) > 0 and len(required_staff_12_available) == 0:
            conflict_messages.append(
                f"必須メンバー不足: 1-2Fは必須メンバー1人以上が必要だが該当者0人"
            )

        for section_name, required_count in requirements.items():
            if required_count <= 0:
                continue
            if section_name in non_mandatory_sections:
                continue
            if not isinstance(available_counts.get(section_name, 0), numbers.Real):
                print(f"ℹ️ [事前検証] Day {day} {section_name}: 当直明け依存のため静的検証をスキップ")

        if conflict_messages:
            print(f"🚨 [事前検証] Day {day}: 競合候補を検出")
            for message in conflict_messages:
                print(f"   - {message}")
            return False

        return True
            
    def _add_shortage_penalty(
        self,
        assigned_vars,
        effective_required,
        required_count,
        day,
        section_name,
    ):
        upper_bound = max(required_count, len(assigned_vars))
        shortage = self.model.NewIntVar(0, upper_bound, f'{section_name}_shortage_{day}')
        excess = self.model.NewIntVar(0, upper_bound, f'{section_name}_excess_{day}')

        # 実際の配置人数と目標人数(effective_required)の差を shortage/excess で表現する
        self.model.Add(
            sum(assigned_vars) - effective_required == excess - shortage
        )

        self.optimizer.register_objective_term(
            f'{section_name}_shortage_{day}',
            10000 * shortage,
        )
        self.optimizer.register_objective_term(
            f'{section_name}_excess_{day}',
            10000 * excess,
        )

        return shortage, excess
    
    def get_year_end_dispensing_required(self, target):
        """
        年末年始(12/30-1/3)の必要人数(4or 7人)を返す
        - 12/29が日曜なら12/30は7人、それ以外は4人
        - 以降1/3まで4人と7人が交互に配置される
        Args:
            target (int): 対象日(day)

        Returns:
            int: 必要人数
        """
        #基準となる今年の12/29の曜日を判定
        base_year = self.year if self.month == 12 else self.year - 1
        dec_29 = datetime.date(base_year, 12, 29)
        print(f"基準となる12/29の曜日: {dec_29.weekday()}")
        
        req_12_30 = 7 if dec_29.weekday() == 6 else 4
        req_12_31 = 4 if req_12_30 == 7 else 7
        req_1_1 = 4 if req_12_31 == 7 else 7
        req_1_2 = 4 if req_1_1 == 7 else 7
        req_1_3 = 4 if req_1_2 == 7 else 7
        
        requirements = {
            (12,30):req_12_30,
            (12,31):req_12_31,
            (1,1):req_1_1,
            (1,2):req_1_2,
            (1,3):req_1_3,
        }
        
        return requirements.get((self.month, target), 4)
        
    ##配置
    def add_section_requests(self):
        porifa_tuesday_penalties= []
        hold_porifa_tuesday_vars = []
        porifa_tuesday_schedulable_vars = []
        kacho_unassigned_penalties = []
        """
        1～2階は月～土は3名
        （name :[7,10,11,14]のうち1人は必ず出勤にする）
        - 日祝日は0名
        - floor=1-2のうちから、月～土は3名選出する
        - スタッフ条件に「1人は必ず出勤にする」の対象者を追加する
        - 選出メンバーの内にname :[7,10,11,14]を必ず1人含める
        - eligible_sectionsのうち、配置可能としてだけ登録した業務、本来兼務業務の（心不全回診、NST,RI),医薬品安全使用WGは専属業務のシフトに含まれないようにする
        """
        print("セクションごとの配置人数の制約を適用します。")
        prev_required = 0#前日の必要配置人数(調剤室用)
        
        for day in range(1, self.days + 1):
            #奇数週か偶数週かの判定
            week_number = (day -1)//7+1
            is_odd_week = week_number % 2 == 1#奇数週ならTrue、偶数週ならFalse

            #今週が第何週かを判定
            week_number = (day -1)//7+1

            #曜日、祝日、前日祝日を取得
            weekday = self._get_weekday(day)
            is_weekday = weekday <= 4 #月～金
            is_holiday = self._is_holiday(day)
            is_monday = weekday == 0
            is_tuesday = weekday == 1
            is_wednesday = weekday == 2
            is_thursday = weekday == 3
            is_friday = weekday == 4
            is_saturday = weekday == 5
            is_sunday = weekday == 6
            prev_day_is_holiday = self._is_prev_day_holiday(day)
            is_year_end_holiday_period = (
                (self.month ==12 and day in {30,31})
                or (self.month == 1 and day ==1)
            )
            prev_day_is_sunday = weekday == 0 if day > 1 else False
            
            
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
            #調剤室
            floor_dispensing_section_id = 1
            #入退院センター
            floor_nyutain_section_id = 3
            #感染管理
            floor_infection_section_id = 14
            #ポリファーマシー
            floor_porifa_id = 11
            #心不全回診,専属業務ではないが、配置可能な業務として登録する
            #ポリファーマシー金曜兼務業務
            concurrent_porifa_id = 10
            #認知症せん妄ラウンド,専属業務ではないが、配置かのうな業務として登録する
            concurrent_dementia_id = 12
            floor_shinhuzen_id = 18
            #NST,専属業務ではないが、配置可能な業務として登録する
            floor_nst_id = 19
            #実習,専属業務ではないが、配置可能な業務として登録する
            floor_jishu_id = 20
            #マスター管理,専属業務ではないが、配置可能な業務として登録する
            floor_master_id = 21
            #RI,専属業務ではないが、配置可能な業務として登録
            floor_ri_id = 22
            #課長業務
            floor_kacho_id = 23
            #医薬品安全使用WG,専属業務ではないが、配置可能な業務として登録する
            floor_safetyWG_id = 24
            #課長業務
            floor_dementia_id = 25
            #部長,実際に配置はしないが、配置可能な業務として登録する
            floor_manager_id = 26

            #配置可能なスタッフリスト
            assigned_staff_12 = []
            assigned_staff_3 = []
            assigned_staff_4 = []
            assigned_staff_4_monday = []
            assigned_staff_4_tuesday = []
            assigned_staff_dispensing_tuesday = []
            assigned_staff_5 = []
            assigned_staff_chemo = []
            assigned_staff_di = []
            di_eligible_staff_ids = []
            assigned_staff_dispensing_getsu = []
            assigned_staff_dispensing_kin = []
            assigned_staff_dispensing_saturday = []
            assigned_staff_chemo_saturday = []
            assigned_staff_dispensing_nichi = []
            assigned_staff_nyutain = []
            assigned_staff_infection = []
            assigned_staff_porifa = []
            porifa_staff_ids = []  # ポリファーマシーチームのスタッフIDリスト（per-staff制約用）
            assigned_staff_shinhuzen = []#心不全回診は専属業務ではないが、配置可能な業務として登録する
            assigned_staff_nst = []#NSTは専属業務ではないが、配置可能な業務として登録する
            assigned_staff_jishu = []#実習は専属業務ではないが、配置可能な業務として登録する
            assigned_staff_master = []#マスター管理は専属業務ではないが、配置可能な業務として登録する
            assigned_staff_ri = []#RIは専属業務ではないが、配置可能な業務として登録する
            assigned_staff_kacho = []
            assigned_staff_safetyWG = []#医薬品安全使用WGは専属業務ではないが、配置可能な業務として登録する
            assigned_staff_dementia = []#認知症せん妄ラウンドは専属業務ではないが、配置可能な業務として登録する
            assigned_staff_sectionManager = []#課長
            assigned_staff_manager = []#部長
            
            #必須メンバーのリスト
            required_staff_12 = []
            print(f"スタッフ条件の読み込み{self.staff}")
            for staff in self.staff.index:
                if self.staff.get('必須メンバー', pd.Series(0, index=self.staff.index)).loc[staff] == 1:
                    required_staff_12.append(staff)
            print(f"必須メンバーのリスト: {required_staff_12}")
                    
            required_staff_12_assigned = [] #12Fで必須メンバーが割り当てられた変数リスト
            required_staff_12_available = [] #12F必須メンバーの当日配置可能変数リスト
            
            # セクション設定を辞書で定義
            section_configs = {
                '1-2F': {
                    'section_id': floor_1_2_section_id,
                    'assigned_list': assigned_staff_12,
                    'available_list': [],
                    'check_day_off': True,
                    'check_oncall_next': True,
                    'required_staff': required_staff_12,
                    'required_list': required_staff_12_assigned,
                },
                '3F': {
                    'section_id': floor_3_section_id,
                    'assigned_list': assigned_staff_3,
                    'available_list': [],
                    'check_day_off': True,
                    'check_oncall_next': True,
                },
                '4F': {
                    'section_id': floor_4_section_id,
                    'assigned_list': assigned_staff_4,
                    'available_list': [],
                    'check_day_off': True,
                    'check_oncall_next': True,
                },
                '4F_月': {
                    'section_id': floor_4_section_id,
                    'assigned_list': assigned_staff_4_monday,
                    'available_list': [],
                    'check_day_off': True,
                    'check_oncall_next': True,
                },
                '4F_火': {
                    'section_id': floor_4_section_id,
                    'assigned_list': assigned_staff_4_tuesday,
                    'available_list': [],
                    'check_day_off': True,
                    'check_oncall_next': True,
                },
                '5F': {
                    'section_id': floor_5_section_id,
                    'assigned_list': assigned_staff_5,
                    'available_list': [],
                    'check_day_off': True,
                    'check_oncall_next': True,
                },
                '化療': {
                    'section_id': floor_chemo_secion_id,
                    'assigned_list': assigned_staff_chemo,
                    'available_list': [],
                    'check_day_off': True,
                    'check_oncall_next': True,
                },
                'DI': {
                    'section_id': floor_di_section_id,
                    'assigned_list': assigned_staff_di,
                    'available_list': [],
                    'check_day_off': True,
                    'check_oncall_next': True,
                },
                '調剤室_月木_非祝日': {
                    'section_id': floor_dispensing_section_id,
                    'assigned_list': assigned_staff_dispensing_getsu,
                    'available_list': [],
                    'check_day_off': True,
                    'check_oncall_next': True,
                },
                '調剤室_火_非祝日':{
                    'section_id': floor_dispensing_section_id,
                    'assigned_list': assigned_staff_dispensing_tuesday,
                    'available_list': [],
                    'check_day_off': True,
                    'check_oncall_next': True,
                },
                '調剤室_金_非祝日': {
                    'section_id': floor_dispensing_section_id,
                    'assigned_list': assigned_staff_dispensing_kin,
                    'available_list': [],
                    'check_day_off': True,
                    'check_oncall_next': True,
                },
                '調剤室_土': {#化療担当者は除外
                    'section_id': floor_dispensing_section_id,
                    'assigned_list': assigned_staff_dispensing_saturday,
                    'available_list': [],
                    'check_day_off': True,
                    'check_oncall_next': True,
                },
                '調剤室_日祝': {
                    'section_id': floor_dispensing_section_id,
                    'assigned_list': assigned_staff_dispensing_nichi,
                    'available_list': [],
                    'check_day_off': True,
                    'check_oncall_next': True,
                },
                '入退院センター': {
                    'section_id': floor_nyutain_section_id,
                    'assigned_list': assigned_staff_nyutain,
                    'available_list': [],
                    'check_day_off': True,
                    'check_oncall_next': True,

                },
                '感染管理': {
                    'section_id': floor_infection_section_id,
                    'assigned_list': assigned_staff_infection,
                    'available_list': [],
                    'check_day_off': True,
                    'check_oncall_next': True,
                },
                'ポリファーマシー':{
                    'section_id':floor_porifa_id,
                    'assigned_list' :assigned_staff_porifa,
                    'available_list': [],
                    'check_day_off':True,
                    'check_oncall_next':True,
                },
                '心不全回診':{#配置可能な業務として登録するが、専属業務のシフトには含めない
                    'section_id':floor_shinhuzen_id,
                    'assigned_list': assigned_staff_shinhuzen,
                    'available_list': [],
                    'check_day_off': True,
                    'check_oncall_next': False,
                },
                'NST':{#配置可能な業務として登録するが、専属業務のシフトには含めない
                    'section_id':floor_nst_id,
                    'assigned_list': assigned_staff_nst,
                    'available_list': [],
                    'check_day_off': True,
                    'check_oncall_next': False,
                },
                '実習':{#配置可能な業務として登録するが、専属業務のシフトには含めない
                    'section_id':floor_jishu_id,
                    'assigned_list': assigned_staff_jishu,
                    'available_list': [],
                    'check_day_off': True,
                    'check_oncall_next': False,
                },
                'マスター管理':{#配置可能な業務として登録するが、専属業務のシフトには含めない
                    'section_id':floor_master_id,
                    'assigned_list': assigned_staff_master,
                    'available_list': [],
                    'check_day_off': True,
                    'check_oncall_next': False,
                },
                'RI':{#配置可能な業務として登録するが、専属業務のシフトには含めない
                    'section_id':floor_ri_id,
                    'assigned_list': assigned_staff_ri,
                    'available_list': [],
                    'check_day_off': True,
                    'check_oncall_next': False,
                },
                '課長業務':{#専属業務配置可能
                    'section_id':floor_kacho_id,
                    'assigned_list': assigned_staff_kacho,
                    'available_list': [],
                    'check_day_off': True,
                    'check_oncall_next': False,
                },
                '医薬品安全使用WG':{#配置可能な業務として登録するが、専属業務のシフトには含めない
                    'section_id':floor_safetyWG_id,
                    'assigned_list': assigned_staff_safetyWG,
                    'available_list': [],
                    'check_day_off': True,
                    'check_oncall_next': False,
                },
                'せん妄ラウンド':{#配置可能な業務として登録するが、専属業務のシフトには含めない
                    'section_id':concurrent_dementia_id,
                    'assigned_list': assigned_staff_dementia,
                    'available_list': [],
                    'check_day_off': True,
                    'check_oncall_next': False,},
                '課長':{
                    'section_id':floor_dementia_id,
                    'assigned_list': assigned_staff_sectionManager,
                    'available_list': [],
                    'check_day_off': True,
                    'check_oncall_next': True,
                    },
                '部長':{#配置可能な業務として登録するが、専属業務のシフトには含めない
                    'section_id':floor_manager_id,
                    'assigned_list': assigned_staff_manager,
                    'available_list': [],
                    'check_day_off': True,
                    'check_oncall_next': False,
                }
            }
            
            
            self._build_section_availability(section_configs=section_configs,day = day,year= self.year,
                                            required_staff_12_available=required_staff_12_available,
                                            required_staff_12_assigned=required_staff_12_assigned,
                                            required_staff_12=required_staff_12,
                                            di_eligible_staff_ids=di_eligible_staff_ids,
                                            porifa_staff_ids=porifa_staff_ids,
                                            prev_year_end_shift=self.prev_year_end_shift,)            

            # available_list は「セクションに所属可能なスタッフのみ」を順に保持するため、
            # セクションごとのローカル index を事前に作って参照する。
            section_staff_pos_map = {}
            for section_name, config in section_configs.items():
                section_id = config['section_id']
                eligible_staff_in_section = [
                    staff for staff in self.staff.index
                    if section_id in self.eligible_sections.get(staff, [])
                ]
                section_staff_pos_map[section_name] = {
                    staff: idx for idx, staff in enumerate(eligible_staff_in_section)
                }
            
            
        
            requirements = self._get_section_min_requirements(
                day=day,
                weekday=weekday,
                is_holiday=is_holiday,
                prev_day_is_holiday=prev_day_is_holiday,
            )
            section_requirements = {
                '1-2F': (
                    requirements['1-2F'],
                    section_configs['1-2F']['available_list']
                ),
                '3F': (
                    requirements['3F'],
                    section_configs['3F']['available_list']
                ),
                '4F': (
                    requirements['4F'],
                    section_configs['4F']['available_list']
                ),
                '5F': (
                    requirements['5F'],
                    section_configs['5F']['available_list']
                ),
                '化療': (
                    requirements['化療'],
                    section_configs['化療']['available_list']
                ),
                'DI': (
                    requirements['DI'],
                    section_configs['DI']['available_list']
                ),
                '入退院センター': (
                    requirements['入退院センター'],
                    section_configs['入退院センター']['available_list']
                ),
                '感染管理': (
                    requirements['感染管理'],
                    section_configs['感染管理']['available_list']
                ),
                'ポリファーマシー': (
                    requirements['ポリファーマシー'],
                    section_configs['ポリファーマシー']['available_list']
                )   
            }
            self._log_candidate_conflicts(
                day=day,
                section_candidates={
                    section_name: section_configs[section_name].get('available_list', [])
                    for section_name in section_requirements
                },
                requirements={
                    section_name: required_count
                    for section_name, (required_count, _) in section_requirements.items()
                },
            )
            total_required = sum(
                required_count
                for required_count,_ in section_requirements.values()
            )
            
            total_candidate_slots = sum(
                len(available_vars)
                for _, available_vars in section_requirements.values()
            )
            print(
                f"Day{day}:"
                f"必要人数合計＝{total_required}",
                f"候補スロット合計＝{total_candidate_slots}"
            )
            available_counts = {
                # 事前検証は静的上限（候補人数）で比較する。
                # BoolVar の和（LinearExpr）を渡すと比較不能で検証が無効化されるため、件数で評価する。
                '1-2F': len(section_configs['1-2F']['available_list']),
                '3F': len(section_configs['3F']['available_list']),
                '4F': len(section_configs['4F']['available_list']),
                '5F': len(section_configs['5F']['available_list']),
                '化療': len(section_configs['化療']['available_list']),
                'DI': len(section_configs['DI']['available_list']),
                '入退院センター': len(section_configs['入退院センター']['available_list']),
                '感染管理': len(section_configs['感染管理']['available_list']),
                'ポリファーマシー': len(section_configs['ポリファーマシー']['available_list']),
            }
            self._prevalidate_section_capacity(
                day=day,
                requirements=requirements,
                available_counts=available_counts,
                required_staff_12_available=required_staff_12_available,
            )
                
            
            """
            12階、3階、4階、5階,DI,ポリファ、ケモ、感染管理、入退院:日曜祝日は0人
            - 出勤希望があれば出勤可能とする,_get_day_on_request_sectionsで定義済み
            """
            if is_sunday or is_holiday:
                """
                日曜祝日0人を適用するフロア
                - 課長業務:出勤希望があれば配置可能とするが、基本的に日祝日は配置しない
                - 配置可能条件:16-22日はシフト作成のため出勤
                - 配置可能条件2:hopelistで希望があれば配置可能とする,DI配置可能メンバーの出勤希望確認に限る
                - 調剤室 は下で別に定義済み、ここには記載しない
                運用上の例外として制約対象外、ここには記載しない
                - name6の16-23日の期間に日曜日がある場合には日曜日配置人数適用から除外
                - 条件に当てはまらない場合はname6勤務&&日曜日は原則0名
                - 年末年始12/30～1/3 は日曜祝日の対象とする
                """
                self.model.Add(sum(assigned_staff_3) == 0)
                self.model.Add(sum(assigned_staff_12) ==0)
                self.model.Add(sum(assigned_staff_4) ==0)
                self.model.Add(sum(assigned_staff_5) ==0)
                self.model.Add(sum(assigned_staff_chemo) ==0)
                self.model.Add(sum(assigned_staff_nyutain) ==0)
                self.model.Add(sum(assigned_staff_infection) ==0)
                self.model.Add(sum(assigned_staff_porifa) ==0)
                self.model.Add(sum(assigned_staff_di) ==0)
                #課長業務については別途定義するためここでは定義しないWorkrequest
            elif is_year_end_holiday_period:#年末年始の期間
                self.model.Add(sum(assigned_staff_3) == 0)
                self.model.Add(sum(assigned_staff_12) ==0)
                self.model.Add(sum(assigned_staff_4) ==0)
                self.model.Add(sum(assigned_staff_5) ==0)
                self.model.Add(sum(assigned_staff_chemo) ==0)
                self.model.Add(sum(assigned_staff_nyutain) ==0)
                self.model.Add(sum(assigned_staff_infection) ==0)
                self.model.Add(sum(assigned_staff_porifa) ==0)
                self.model.Add(sum(assigned_staff_di) ==0)
                    
            """
            ポリファーマシーチーム
            - 一日専属の火曜日と半日のみの金曜日がある
            - こちらで設定するのは1日専属の火曜日のみ
            - 所属メンバー全員が揃っている火曜日に配置する（CP-SAT変数で最適週を決定）
            - 金曜半日午後は兼務業務で設定する
            - 原則として月1回開催
            """
            available_porifa_vars = section_configs['ポリファーマシー']['available_list']
            
            if is_tuesday and not is_holiday:
                hold_porifa_tuesday = self.optimizer.porifa_tuesday_vars.get(
                    day, self.model.NewBoolVar(f'hold_porifa_tuesday_{day}')
                )
                self.optimizer.porifa_tuesday_vars[day] = hold_porifa_tuesday
                hold_porifa_tuesday_vars.append(hold_porifa_tuesday)

                porifa_tuesday_schedulable = self.model.NewBoolVar(f'porifa_tuesday_schedulable_{day}')
                porifa_tuesday_schedulable_vars.append(porifa_tuesday_schedulable)

                if available_porifa_vars and assigned_staff_porifa and not is_year_end_holiday_period:                    
                    # 火曜ポリファは所属メンバー全員が可用な場合のみ開催可能
                    self.model.AddMinEquality(porifa_tuesday_schedulable, available_porifa_vars)
                    self.model.Add(hold_porifa_tuesday <= porifa_tuesday_schedulable)
                    self.model.Add(
                        sum(assigned_staff_porifa) == len(assigned_staff_porifa)
                    ).OnlyEnforceIf(hold_porifa_tuesday)
                    self.model.Add(sum(assigned_staff_porifa) == 0).OnlyEnforceIf(hold_porifa_tuesday.Not())
                    print(
                        f"day{day}: 火曜ポリファーマシーは全{len(assigned_staff_porifa)}人が"
                        "配置可能な場合のみ開催可能です。"
                    )
                else:
                    # メンバー/候補が不足している日は開催不可または年末年始休暇期間中は開催不可
                    self.model.Add(hold_porifa_tuesday == 0)
                    self.model.Add(porifa_tuesday_schedulable == 0)
                    self.model.Add(sum(assigned_staff_porifa) == 0)
                    print(f"day{day}: ポリファーマシー担当者が未登録のため開催できません。")
            else:
                #shift_optimizer.py:175-181 で、すべての火曜日に porifa_tuesday_vars が作成されます
                hold_porifa_tuesday = self.optimizer.porifa_tuesday_vars.get(
                    day, self.model.NewBoolVar(f'hold_porifa_tuesday_{day}')
                )
                self.optimizer.porifa_tuesday_vars[day] = hold_porifa_tuesday
                hold_porifa_tuesday_vars.append(hold_porifa_tuesday)
                
                porifa_tuesday_schedulable = self.model.NewBoolVar(f'porifa_tuesday_schedulable_{day}')
                porifa_tuesday_schedulable_vars.append(porifa_tuesday_schedulable)
                self.model.Add(hold_porifa_tuesday == 0)
                self.model.Add(porifa_tuesday_schedulable == 0)
                self.model.Add(sum(assigned_staff_porifa) == 0)
                
            """
            12F
            - weekdayの場合、3人配置
            - 日祝日は0人、上で定義済み
            """
            print(f"day{day}:編集後の12F必須メンバーリスト{required_staff_12}")
            print(f"day{day}:編集後の配置可能リストに基づく12Fの配置必須メンバーのavailable_list: {[var.Name() for var in required_staff_12_available]}")
            if not is_sunday and not is_holiday and not is_year_end_holiday_period:
                available_12f_vars = section_configs['1-2F']['available_list']
                available_staff_12_upper_bound = len(available_12f_vars)
                n_avail_12f = sum(available_12f_vars)
                required_12f = 3
                print(
                    f"day{day}: 1-2Fの配置人数は3人です。"
                    f"配置可能スタッフ候補数(上限)は{available_staff_12_upper_bound}人です。"
                    f"必須メンバーの候補変数数は{len(required_staff_12_assigned)}人です。"
                )
                print(f"day{day}: 1-2Fの配置可能スタッフのavailable_list: {[var.Name() for var in available_12f_vars]}")
                if available_12f_vars:
                    effective_required_12f = n_avail_12f
                    self._add_shortage_penalty(
                        assigned_vars=assigned_staff_12,
                        effective_required=effective_required_12f,
                        required_count=len(available_12f_vars),
                        day=day,
                        section_name='12f',
                    )
                #必須メンバー(required_staff_12)のうち、少なくとも1人が配置されるようにする
                if required_staff_12_assigned:#必須メンバーの候補変数が存在する場合のみ制約を追加
                    has_required_staff_available = self.model.NewBoolVar(
                        f'has_required_staff_available_12f_{day}'
                    )
                    self.model.Add(sum(required_staff_12_available) >= 1).OnlyEnforceIf(has_required_staff_available)
                    self.model.Add(sum(required_staff_12_available) == 0).OnlyEnforceIf(has_required_staff_available.Not())
                    self.model.Add(
                        sum(required_staff_12_assigned) >= 1
                    ).OnlyEnforceIf(has_required_staff_available)
                else:
                    print(f"day{day}: 1-2Fの必須メンバー候補が存在しないため、必須メンバー配置制約は適用されません。")
            """
            3階は火曜のみ5名、他は4名。
            - 日曜祝日は0名、上で定義済み
            """
            available_3f_vars = section_configs['3F']['available_list']
            print(f"day{day}: 3Fの配置可能スタッフのavailable_list: {[var.Name() for var in available_3f_vars]}")
            n_avail_3f = sum(available_3f_vars)  # CP-SAT式: 実際に配置可能な人数

            if is_tuesday and not is_holiday and not is_year_end_holiday_period:
                required_3f = 5
                if available_3f_vars:
                    effective_required = n_avail_3f
                    
                    self._add_shortage_penalty(
                        assigned_vars = assigned_staff_3,
                        effective_required = effective_required,
                        required_count = required_3f,
                        day = day,
                        section_name = '3f'
                    )
                    print(f"day{day}: 3Fの配置人数は{required_3f}人です。(上限は{len(available_3f_vars)}人)")
            elif not is_sunday and not is_holiday and not is_year_end_holiday_period:
                required_3f = 4
                if available_3f_vars:
                    effective_required = n_avail_3f
                    self._add_shortage_penalty(
                        assigned_vars = assigned_staff_3,
                        effective_required = effective_required,
                        required_count = required_3f,
                        day = day,
                        section_name = '3f'
                    )
                    print(f"day{day}: 3Fの配置人数は{required_3f}人です。(上限は{len(available_3f_vars)}人)")

            """
            4階：月のみ5名、他は4名。
            - 日曜祝日は0名、上で定義済み
            - 月曜日と火曜日は緩和ケア回診担当者を除く _build_section_availabilotyで定義すみ
            """
            
            
            if is_monday and not is_holiday and not is_year_end_holiday_period:
                available_4f_vars = section_configs['4F']['available_list']
                n_available_4f = sum(available_4f_vars)  # CP-SAT式: 実際に配置可能な人数
                            
                required_4f = 5
                if available_4f_vars:
                    effective_required = n_available_4f
                    self._add_shortage_penalty(
                        assigned_vars = assigned_staff_4,
                        effective_required = effective_required,
                        required_count = required_4f,
                        day = day,
                        section_name = '4f'
                    )
                    print(f"day{day}: 4Fの配置人数は{required_4f}人です。(上限は{len(available_4f_vars)}人)")
            elif is_tuesday and not is_holiday and not is_year_end_holiday_period:
                available_4f_vars_tues = section_configs['4F_火']['available_list']
                n_available_4f_tues = sum(available_4f_vars_tues)  # CP-SAT式: 実際に配置可能な人数
                            
                #毎週火曜日は緩和ケア回診担当者を除いたスタッフで構成　_build_section_availabilotyで定義    
                required_4f = 4
                if available_4f_vars_tues:
                    effective_required = n_available_4f_tues
                    self._add_shortage_penalty(
                        assigned_vars = assigned_staff_4_tuesday,
                        effective_required = effective_required,
                        required_count = required_4f,
                        day = day,
                        section_name='4f_tues'
                    )
                    print(f"day{day}: 4F火曜の配置人数は{required_4f}人です。(上限は{len(available_4f_vars_tues)}人)")
            elif not is_sunday and not is_holiday and not is_year_end_holiday_period:
                available_4f_vars = section_configs['4F']['available_list']
                n_available_4f = sum(available_4f_vars)  # CP-SAT式: 実際に配置可能な人数
                            
                required_4f = 4
                if available_4f_vars:
                    effective_required = n_available_4f
                    self._add_shortage_penalty(
                        assigned_vars = assigned_staff_4,
                        effective_required = effective_required,
                        required_count = required_4f,
                        day = day,
                        section_name = '4f'
                    )
                    print(f"day{day}: 4Fの配置人数は{required_4f}人です。(上限は{len(available_4f_vars)}人)")
            
            """
            5階：連休明けでない火曜は4名、月・水は5名、木～土は4名
            - 日曜祝日は0名、上で定義済み
            - 連休明けの定義：前日が祝日、もしくは祝日の次の日が火曜日の場合
            - 連休明け火曜は5名
            - それ以外の火曜は4名
            """            
            if is_tuesday and prev_day_is_holiday and not is_year_end_holiday_period:#連休明け火曜
                available_5f_vars = section_configs['5F']['available_list']
                effective_required = sum(available_5f_vars)  # CP-SAT式: 実際に配置可能な人数
                required_5f = 5
                if available_5f_vars:
                    min_required_5f = self.model.NewIntVar(
                        0,required_5f,f'min_required_5f_day{day}'
                    )
                    self.model.AddMinEquality(
                        min_required_5f,[effective_required,required_5f]
                    )
                    self._add_shortage_penalty(
                        assigned_vars = assigned_staff_5,
                        effective_required = effective_required,
                        required_count = required_5f,
                        day = day,
                        section_name = '5f_tuesday_and_prevholiday'
                    )
                    
            elif ((is_monday and not is_holiday) or (is_wednesday and not is_holiday)) and not is_year_end_holiday_period:#平日の月・水
                available_5f_vars = section_configs['5F']['available_list']
                effective_required = sum(available_5f_vars)  # CP-SAT式: 実際に配置可能な人数
                required_5f = 5
                if available_5f_vars:
                    min_required_5f = self.model.NewIntVar(
                        0,required_5f,f'min_required_5f_day{day}'
                    )
                    self.model.AddMinEquality(
                        min_required_5f,[effective_required,required_5f]
                    )
                    
                    self._add_shortage_penalty(
                        assigned_vars = assigned_staff_5,
                        effective_required = effective_required,
                        required_count = required_5f,
                        day = day,
                        section_name = '5f_monday_or_wednesday'
                    )
            elif is_tuesday and not prev_day_is_holiday and not is_year_end_holiday_period:#通常の火曜は4名
                #可能人数が4人以上ならば最低人数を4人とする
                available_5f_vars = section_configs['5F']['available_list']
                effective_required = sum(available_5f_vars)  # CP-SAT式: 実際に配置可能な人数
                required_5f = 4
                #4人未満ならば、配置可能人数を最低人数とする
                if available_5f_vars:
                    min_required_5f = self.model.NewIntVar(
                        0,required_5f,f'min_required_5f_day{day}'
                    )
                    self.model.AddMinEquality(
                        min_required_5f,[effective_required,required_5f]
                    )
                    self._add_shortage_penalty(
                        assigned_vars = assigned_staff_5,
                        effective_required = effective_required,
                        required_count = required_5f,
                        day = day,
                        section_name = '5f_tuesday'
                    )
            elif (is_thursday or is_friday or is_saturday) and not is_holiday and not is_year_end_holiday_period:#木～土
                available_5f_vars = section_configs['5F']['available_list']
                effective_required = sum(available_5f_vars)  # CP-SAT式: 実際に配置可能な人数
                required_5f = 4
                if available_5f_vars:
                    effective_required = sum(available_5f_vars)
                    min_required_5f = self.model.NewIntVar(
                        0,required_5f,f'min_required_5f_day{day}'
                    )
                    self.model.AddMinEquality(
                        min_required_5f,[effective_required,required_5f]
                    )
                    self._add_shortage_penalty(
                        assigned_vars = assigned_staff_5,
                        effective_required = effective_required,
                        required_count = required_5f,
                        day = day,
                        section_name = '5f_thu_to_sat'
                    )
            """
            化学療法 floor=6
            - 育休中のスタッフがいる場合、月〜金は3名
            - hope_list == 3(育休)
            - 育休中のスタッフがいない場合、月〜金は4名
            - 土曜日（専属業務）は2名
            - 日曜祝日は0名、上で定義済み
            """
            available_chemo_vars = section_configs['化療']['available_list']
            n_avail_chemo = sum(available_chemo_vars)  # CP-SAT式: 実際に配置可能な人数
            
            if is_weekday and not is_holiday and not is_year_end_holiday_period:#月〜金
                required_chemo = 3 if self._has_maternity_leave_in_chemo(day) else 4
                chemo_available_expr = sum(section_configs['化療']['available_list'])
                print(f"day{day}:化学療法の配置可能人数（当直明け反映）は {chemo_available_expr} です。育休中のスタッフがいるか確認します。")
                if available_chemo_vars:
                    effective_required = n_avail_chemo
                    min_required_chemo = self.model.NewIntVar(
                        0,required_chemo,
                        f'min_required_chemo_day{day}'
                    )
                    self.model.AddMinEquality(
                        min_required_chemo,
                        [effective_required, required_chemo]
                    )
                    self._add_shortage_penalty(
                        assigned_vars = assigned_staff_chemo,
                        effective_required = effective_required,
                        required_count = required_chemo,
                        day = day,
                        section_name = 'chemo'
                    )
            elif is_saturday and not is_holiday and not is_year_end_holiday_period:
                required_chemo = 2
                self._add_shortage_penalty(
                    assigned_vars = assigned_staff_chemo,
                    effective_required = required_chemo,
                    required_count = required_chemo,
                    day = day,
                    section_name = 'chemo'
                ) 
                print(f"土曜の化学療法室に配置可能なスタッフは{assigned_staff_chemo}です")           
            """
            DI
            - 2月前、の週の5日間は1日2名 薬審:偶数月の第一木曜日
            - 1名になる日は月曜日以外なら可
            - それ以外は月のみ2名、火～土は1名。
            - 火～土は1名以上配置
            - 日曜祝日は0名、上で定義済み
            """
            yakushin_month = [2,8,10,12]
            pre_yakushin_month = [(m-1) if m>1 else 12 for m in yakushin_month]
            available_di_vars = section_configs['DI']['available_list']
            n_avail_di = sum(available_di_vars)  # CP-SAT式: 実際に配置可能な人数
            
            if self.month in pre_yakushin_month and not is_year_end_holiday_period:
                #当月の最終5日間を取得
                last_week_days = [d for d in range(self.days-4,self.days +1)]
                print(f"DIの当月最終5日間: {last_week_days}")
                if day in last_week_days and not is_holiday:
                    required_di = 2
                    if available_di_vars:
                        effective_required = n_avail_di
                        self._add_shortage_penalty(
                            assigned_vars = assigned_staff_di,
                            effective_required = effective_required,
                            required_count = required_di,
                            day = day,
                            section_name = 'di'
                        )
                        print(f"day{day}: DIの配置人数は{required_di}人です（当月最終5日間のため）。(上限は{len(available_di_vars)}人)")
                elif is_monday and not is_holiday:
                    required_di = 2
                    if available_di_vars:
                        effective_required = n_avail_di
                        self._add_shortage_penalty(
                            assigned_vars = assigned_staff_di,
                            effective_required = effective_required,
                            required_count = required_di,
                            day = day,
                            section_name = 'di'
                        )
                elif (is_tuesday and not is_holiday) or (is_wednesday and not is_holiday) or (is_thursday and not is_holiday) or(is_friday and not is_holiday) or (is_saturday and not is_holiday): 
                    required_di = 1
                    if available_di_vars:
                        effective_required = n_avail_di
                        self._add_shortage_penalty(
                            assigned_vars = assigned_staff_di,
                            effective_required = effective_required,
                            required_count = required_di,
                            day = day,
                            section_name = 'di'
                        )
                
            else:
                if is_monday and not is_holiday:#月曜
                    required_di = 2
                    if available_di_vars:
                        effective_required = n_avail_di
                        self._add_shortage_penalty(
                            assigned_vars = assigned_staff_di,
                            effective_required = effective_required,
                            required_count = required_di,
                            day = day,
                            section_name = 'di'
                        )
                elif (is_tuesday and not is_holiday) or (is_wednesday and not is_holiday) or (is_thursday and not is_holiday) or(is_friday and not is_holiday) or (is_saturday and not is_holiday):#火〜土
                    required_di = 1
                    if available_di_vars:
                        effective_required = n_avail_di
                        self._add_shortage_penalty(
                            assigned_vars = assigned_staff_di,
                            effective_required = effective_required,
                            required_count = required_di,
                            day = day,
                            section_name = 'di'
                        )
                
            """
            調剤室
            - 調剤室は監査者を含めて、月～木が入退院センター担当含めて7名。
            - 含めないと月〜木は6名、金曜は5名、土曜は5名
            - 金曜は隔週で午前7名、午後6名.→なんで？他の配置人数に影響しそう
            - 土曜：調剤室かつ化学療法の両方に対応可能なスタッフから2名(最低1名) + それ以外の調剤室勤務可能スタッフを含めた合計
            - 土曜日の化学療法業務は兼務業務に配置
            - 休み希望の日は配置しない、上で定義済み
            - 日曜祝日は最低4名、2連続の際は7人程度必要
            - 前日が祝日の日曜日：7人
            - 前日が祝日でない日曜日：4人
            - 前日が祝日・または日曜日でない祝日（平日の祝日):4人
            - 年末年始12/30～1/3 は日曜祝日の対象とする
            - GWは祝日として認識される
            - TODO:2日連続祝日（GW）の時のrequiredの4,7の切り替え
            - 兼務業務と比較して午前のみ、午後のみのスタッフが生じる場合には1日の必要人数を+1
            - 化学療法(課長)は平日化学療法、土曜日のみ調剤室配置可能とする
            - 化学療法室&課長&主任以上のスタッフは平日調剤室配置から除外、土曜日のみ配置可能
            - スタッフ条件['日曜出勤']FALSEのスタッフは日曜祝日配置から除外する
            - 出勤希望があれば日曜祝日配置可能とする
            - 火曜日は緩和ケア回診担当者を除く
            """
            if is_year_end_holiday_period:
                required_dispensing = self.get_year_end_dispensing_required(day)
                available_dispensing_vars = section_configs['調剤室_日祝']['available_list']
                n_avail_dispensing = sum(available_dispensing_vars)# CP-SAT式: 実際に配置可能な人数
                if available_dispensing_vars:
                    # 配置可能人数ではなく必要人数(required_dispensing)に頭打ちする
                    min_required_dispensing = self.model.NewIntVar(
                        0, required_dispensing, f'min_required_dispensing_yearend_{day}'
                    )
                    self.model.AddMinEquality(
                        min_required_dispensing,
                        [n_avail_dispensing, required_dispensing]
                    )
                    self._add_shortage_penalty(
                        assigned_vars=assigned_staff_dispensing_nichi,
                        effective_required=min_required_dispensing,
                        required_count=required_dispensing,
                        day=day,
                        section_name='dispensing_nichi',
                    )
            #条件分岐の祝日条件は他の曜日より先に持ってくる(平日でも祝日の可能性あるから)
            #前日が7人配置(required=7)以外の場合
            elif is_holiday and prev_required != 7:
                print(f"prev_required={prev_required},前日の必要配置人数を表示します：{day}")
                available_dispensing_vars= section_configs['調剤室_日祝']['available_list']
                n_avail_dispensing = sum(available_dispensing_vars)# CP-SAT式: 実際に配置可能な人数
                
                required_dispensing = 7
                if available_dispensing_vars:
                    # 配置可能人数ではなく必要人数(required_dispensing)に頭打ちする
                    min_required_dispensing = self.model.NewIntVar(
                        0, required_dispensing, f'min_required_dispensing_holiday_streak_{day}'
                    )
                    self.model.AddMinEquality(
                        min_required_dispensing,
                        [n_avail_dispensing, required_dispensing]
                    )
                    self._add_shortage_penalty(
                        assigned_vars=assigned_staff_dispensing_nichi,
                        effective_required=min_required_dispensing,
                        required_count=required_dispensing,
                        day=day,
                        section_name='dispensing_holiday_streak',
                    )
                prev_required = required_dispensing
            #祝日　前日が7人配置(required= 4の場合
            elif is_holiday and prev_required == 7:
                available_dispensing_vars= section_configs['調剤室_日祝']['available_list']
                n_avail_dispensing = sum(available_dispensing_vars)# CP-SAT式: 実際に配置可能な人数
                
                required_dispensing = 4
                if available_dispensing_vars:
                    # 配置可能人数ではなく必要人数(required_dispensing)に頭打ちする
                    min_required_dispensing = self.model.NewIntVar(
                        0, required_dispensing, f'min_required_dispensing_holiday_{day}'
                    )
                    self.model.AddMinEquality(
                        min_required_dispensing,
                        [n_avail_dispensing, required_dispensing]
                    )
                    self._add_shortage_penalty(
                        assigned_vars=assigned_staff_dispensing_nichi,
                        effective_required=min_required_dispensing,
                        required_count=required_dispensing,
                        day=day,
                        section_name='dispensing_holiday',
                    )
                prev_required = required_dispensing
            elif (is_monday  or is_wednesday or is_thursday)and not is_holiday:
                available_dispensing_vars= section_configs['調剤室_月木_非祝日']['available_list']
                effective_required = sum(available_dispensing_vars)# CP-SAT式: 実際に配置可能な人数            
                required_dispensing = 6
                
                if available_dispensing_vars:
                    min_required_dispensing = self.model.NewIntVar(
                        0,
                        required_dispensing,
                        f'min_required_dispensing_getsu_{day}'
                    )
                    self.model.AddMinEquality(
                        min_required_dispensing,
                        [effective_required, required_dispensing]
                    )
                    self._add_shortage_penalty(
                        assigned_vars=assigned_staff_dispensing_getsu,
                        effective_required=min_required_dispensing,
                        required_count=required_dispensing,
                        day=day,
                        section_name='dispensing_getsu',
                    )
            elif is_tuesday and not is_holiday:
                available_dispensing_vars= section_configs['調剤室_火_非祝日']['available_list']
                effective_required = sum(available_dispensing_vars)# CP-SAT式: 実際に配置可能な人数
                
                if available_dispensing_vars:
                    required_dispensing = 6
                    min_required_dispensing = self.model.NewIntVar(
                        0,
                        required_dispensing,
                        f'tue_min_required_{day}'
                    )
                    self.model.AddMinEquality(
                        min_required_dispensing,
                        [effective_required, required_dispensing]
                    )
                    self._add_shortage_penalty(
                        assigned_vars=assigned_staff_dispensing_tuesday,
                        effective_required=min_required_dispensing,
                        required_count=required_dispensing,
                        day = day,
                        section_name = 'dispensing_tue'
                    )
            elif is_friday and not is_holiday:
                available_dispensing_vars= section_configs['調剤室_金_非祝日']['available_list']
                effective_required = sum(available_dispensing_vars)# CP-SAT式: 実際に配置可能な人数                
                    
                if is_odd_week:#第1・3週の金曜日　奇数週
                    required_dispensing = 6
                    if available_dispensing_vars:
                        min_required_dispensing = self.model.NewIntVar(
                            0,
                            required_dispensing,
                            f'fri_odd_min_required_{day}',
                        )
                        self.model.AddMinEquality(
                            min_required_dispensing,
                            [effective_required, required_dispensing]
                        )
                        self._add_shortage_penalty(
                            assigned_vars=assigned_staff_dispensing_kin,
                            effective_required=min_required_dispensing,
                            required_count=required_dispensing,
                            day=day,
                            section_name = 'dispensing_13_kin'
                        )
                else:#第2・4週の金曜日 偶数週
                    required_dispensing = 5
                    if available_dispensing_vars:
                        min_required_dispensing = self.model.NewIntVar(
                            0,
                            required_dispensing,
                            f'fri_even_min_required_{day}',
                        )
                        self.model.AddMinEquality(
                            min_required_dispensing,
                            [effective_required, required_dispensing]
                        )
                        self._add_shortage_penalty(
                            assigned_vars=assigned_staff_dispensing_kin,
                            effective_required=min_required_dispensing,
                            required_count=required_dispensing,
                            day=day,
                            section_name = 'dispensing_24_kin'
                        )                                    
            elif is_saturday and not is_holiday:
                #調剤室スタッフより3名配置(化療可能者は除く)
                # 当日の化療・調剤室の両方に配置可能なスタッフを CP-SAT 内で判定する。
                available_dispensing_vars = section_configs['調剤室_土']['available_list']
                effective_required = sum(available_dispensing_vars)#CP-SAT式: 実際に配置可能な人数
                required_dispensing = 3
                if available_dispensing_vars:
                    min_required_dispensing = self.model.NewIntVar(
                        0,required_dispensing,f'min_required_dispensing_saturday_{day}'
                    )
                    self.model.AddMinEquality(
                        min_required_dispensing,
                        [effective_required, required_dispensing]
                    )
                    self._add_shortage_penalty(
                        assigned_vars=assigned_staff_dispensing_saturday,
                        effective_required=min_required_dispensing,
                        required_count=required_dispensing,
                        day=day,
                        section_name='dispensing_saturday',
                    )
                
                
                else:
                    raise ValueError(
                        f"[DEBUG土曜化療エラー] Day{day}:"
                        "化療+調剤室の両対応スタッフが0です。"
                        "土曜化療と監査のハード制約と衝突しやすい状態です。"
                    )
            #日曜 前日が祝日でない場合
            elif is_sunday and not prev_day_is_holiday:
                available_dispensing_vars= section_configs['調剤室_日祝']['available_list']
                effective_required = sum(available_dispensing_vars)# CP-SAT式: 実際に配置可能な人数
                required_dispensing = 4
                if available_dispensing_vars:
                    min_required_dispensing = self.model.NewIntVar(
                        0,required_dispensing,
                        f'min_required_dispensing_sunday_{day}'
                    )
                    self.model.AddMinEquality(
                        min_required_dispensing,
                        [effective_required, required_dispensing]
                    )
                    self._add_shortage_penalty(
                        assigned_vars=assigned_staff_dispensing_nichi,
                        effective_required=min_required_dispensing,
                        required_count=required_dispensing,
                        day=day,
                        section_name='dispensing_sunday',
                    )
                # 翌日の休日判定に使う値は実際にこの日設定したrequiredに合わせる
                prev_required = required_dispensing
            #日曜　前日が祝日の場合
            elif is_sunday and prev_day_is_holiday:
                available_dispensing_vars= section_configs['調剤室_日祝']['available_list']
                n_avail_dispensing = sum(available_dispensing_vars)# CP-SAT式: 実際に配置可能な人数
                
                required_dispensing = 7
                if available_dispensing_vars:
                    # 配置可能人数ではなく必要人数(required_dispensing)に頭打ちする
                    min_required_dispensing = self.model.NewIntVar(
                        0, required_dispensing, f'min_required_dispensing_sunday_holiday_{day}'
                    )
                    self.model.AddMinEquality(
                        min_required_dispensing,
                        [n_avail_dispensing, required_dispensing]
                    )
                    self._add_shortage_penalty(
                        assigned_vars=assigned_staff_dispensing_nichi,
                        effective_required=min_required_dispensing,
                        required_count=required_dispensing,
                        day=day,
                        section_name='dispensing_sunday_holiday',
                    )
                prev_required = 7
            """
            入退院センター 
            - 月〜土は1名
            - 休み希望の日は配置しない、上で定義済み
            - 配置可能なスタッフがいない場合は0人でも許容
            """
            available_nyutain_vars = section_configs['入退院センター']['available_list']
            n_avail_nyutain = sum(available_nyutain_vars)  # CP-SAT式: 実際に配置可能な人数
            if not is_sunday and not is_holiday and not is_year_end_holiday_period:
                required_nyutain = 1
                effective_required = n_avail_nyutain
                self._add_shortage_penalty(
                    assigned_vars=assigned_staff_nyutain,
                    effective_required=required_nyutain,
                    required_count=required_nyutain,
                    day=day,
                    section_name='nyutain',
                )
            
            """
            医療安全・感染管理
            - 月〜土に1日1人（配置可能なスタッフがいる場合）
            - 当直明けの日は配置しない
            - 休み希望の日は配置しない,上で定義済み
            - 対応可能スタッフ: スタッフ0（専属）、Floor==10（部長）
            - 配置可能なスタッフがいない場合は0人でも許容
            - 日曜祝日は0人
            """
            available_infection_vars = section_configs['感染管理']['available_list']
            n_avail_infection = sum(available_infection_vars)  # CP-SAT
            
            #医療安全・感染管理available_var があれば配置可能とする、なければその日の配置人数は0人を許容
            if not is_sunday and not is_holiday and not is_year_end_holiday_period:
                required_infection = 1
                available_list_infection = section_configs['感染管理']['available_list']
                print(f"医療安全・感染管理の配置可能スタッフ数の上限は {len(available_list_infection)} 人です。")
                if available_list_infection:
                    self._add_shortage_penalty(
                        assigned_vars=assigned_staff_infection,
                        effective_required=n_avail_infection,
                        required_count=required_infection,
                        day=day,
                        section_name='infection',
                    )
                    # 配置可能者が0人の場合は0人配置を許容（ハード制約なし）
                else:
                    print(f"警告: Day {day}の感染管理に対応可能なスタッフが登録されていません。")
            
            """
            課長
            - 月〜土に1日1人（配置可能なスタッフがいる場合）
            - 当直明けの日は配置しない
            - 休み希望の日は配置しない,上で定義済み
            - 対応可能スタッフ: Floor|Floor2|Floor3==課長
            """
            available_kacho_vars = section_configs['課長']['available_list']
            if not is_sunday and not is_holiday and not is_year_end_holiday_period:
                if available_kacho_vars:
                    kacho_available = self.model.NewBoolVar(f'kacho_available_{day}')
                    self.model.AddMaxEquality(kacho_available, available_kacho_vars)

                    unassigned_penalty = self.model.NewBoolVar(f'kacho_unassigned_penalty_{day}')
                    self.model.Add(
                        unassigned_penalty == kacho_available - sum(assigned_staff_sectionManager)
                    )
                    kacho_unassigned_penalties.append(unassigned_penalty)
                else:
                    print(f"警告: Day {day}の課長に対応可能なスタッフが登録されていません。")
            
            
            """
            eligible_sectionsのうち、配置可能としてだけ登録した業務、本来兼務業務の（心不全回診、NST,RI),医薬品安全使用WGは専属業務のシフトに含まれないようにする
            専属業務としては配置しない、兼務業務の方で設定
            eligible_sectionsで配置可能なフロアに判定として兼務業務のセクションIDを追加しているため
            """
            self.model.Add(sum(assigned_staff_shinhuzen) == 0)
            self.model.Add(sum(assigned_staff_nst) == 0)
            self.model.Add(sum(assigned_staff_jishu) == 0)
            self.model.Add(sum(assigned_staff_master) == 0)
            self.model.Add(sum(assigned_staff_ri) == 0)
            self.model.Add(sum(assigned_staff_safetyWG) == 0)
            self.model.Add(sum(assigned_staff_dementia) == 0)
            self.model.Add(sum(assigned_staff_manager) == 0)
            
        # 月内で火曜ポリファ開催を原則1回行う
        if hold_porifa_tuesday_vars:
            any_schedulable_tuesday_porifa = self.model.NewBoolVar('any_schedulable_tuesday_porifa')
            if porifa_tuesday_schedulable_vars:
                self.model.AddMaxEquality(any_schedulable_tuesday_porifa, porifa_tuesday_schedulable_vars)
                # 開催候補日が1日でもある場合は1回開催、候補日がなければ0回
                self.model.Add(sum(hold_porifa_tuesday_vars) == 1).OnlyEnforceIf(any_schedulable_tuesday_porifa)
                self.model.Add(sum(hold_porifa_tuesday_vars) == 0).OnlyEnforceIf(any_schedulable_tuesday_porifa.Not())
            else:
                self.model.Add(sum(hold_porifa_tuesday_vars) == 0)
        else:
            print("火曜ポリファ開催候補がないため、月内必須制約をスキップします。")

        if kacho_unassigned_penalties:
            self.optimizer.register_objective_term(
                "kacho_assignment",
                WEIGHT_KACHO_ASSIGNMENT * sum(kacho_unassigned_penalties),
            )
    
        #return porifa_tuesday_penalties
            
    def add_consecutive_work_constraints(self):
        """
        連続出勤の制限
        - 当直明けを含めると6日まで
        - 各個人で配置可能なセクションについて検証する
        - 休み0以外のprimary_sectionが7日以上連続しないようにする
        - TODO:前月シフトも考慮
        """
        penalties = []
        prev_month = getattr(self.optimizer,'prev_month_shift', None)
        def is_prev_month_working(staff, relative_day, check_sections):
            """前月CSV上の相対日(-1, -2, ...)が勤務日かを返す。"""
            if prev_month is None:
                print(f"前月シフト表が存在しません。")
                return 0

            print(f"前月シフト表の確認インデックスの確認{prev_month.loc[prev_month['Name'] == staff]}")
            if staff not in prev_month.loc[prev_month['Name'] == staff, 'Name'].values:
                print(f"前月シフト表にスタッフ{staff}が存在しません。")
                return 0

            column = str(relative_day)
            print(f"前月シフト表の確認: staff={staff}, relative_day={relative_day}")
            if column not in prev_month.columns:
                return 0

            value = prev_month.loc[prev_month['Name'] == staff, column].values[0]#前月シフト表の該当セルの値
            print(f"前月シフト表の該当セルの値: staff={staff}, column={column}, value={value}")
            if pd.isna(value):
                return 0

            value_text = str(value).strip()#該当セルの値を文字列として取得
            print(f"前月シフト表の該当セルの値を文字列として取得: staff={staff}, column={column}, value_text={value_text}")

            # 前月CSVは「1」「4」「17」のような section ID、
            # または section 名を含む文字列として保存されている。
            if value_text in {"", "0", "休み"}:
                return 0
            

            for section in check_sections:
                section_name = PRIMARY_SECTIONS.get(section)
                if section_name is not None and section_name in value_text:
                    return 1

            # 数値IDが保存されている場合
            for section in check_sections:
                if value_text == str(section):
                    return 1
            return 0
    
        
        for staff in self.staff.index:
            check_sections = sorted(set(self.eligible_sections.get(staff, [])))
            if 0 in check_sections:
                check_sections.remove(0)
            if 17 not in check_sections:
                check_sections.append(17)

            print(f"スタッフ{staff}の勤務可能なセクションは{check_sections}です")

            for end_day in range(1, self.days + 1):
                window_start = end_day - 6 # 7日間のウィンドウの開始日を計算
                print(f"window_start={window_start}, end_day={end_day}")
                previous_work_count = 0
                current_work_vars = []

                for day in range(window_start, end_day + 1):
                    if day == 0:  # day0は存在しないのでスキップ
                        print(f"day=0のためスキップ: staff={staff}, day={day}, check_sections={check_sections}")
                        continue
                    elif day < 1:
                        previous_work_count += is_prev_month_working(
                            staff,
                            day,
                            check_sections,
                        )
                    else:
                        current_work_vars.extend(
                            self.shifts[(staff, day, section)]
                            for section in check_sections
                        )

                work_days_in_window = self.model.NewIntVar(
                    0,
                    7,
                    f"work_days_in_window_{staff}_{end_day}",
                )

                self.model.Add(
                    work_days_in_window
                    == previous_work_count + sum(current_work_vars)
                )

                excess_var = self.model.NewIntVar(
                    0,
                    7,
                    f"consecutive_work_excess_{staff}_{end_day}",
                )
                self.model.Add(excess_var >= work_days_in_window - 6)
                self.model.Add(excess_var >= 0)
                penalties.append(excess_var)

        return penalties
                
    def add_sunday_holiday_work_constraints(self):
        """
        日曜祝日の出勤は可能な限り月1回までとする（ソフト制約）
        - 12/30,12/31,1/1,1/2,1/3も日曜祝日の対象とする
        """
        penalties = []
        for staff in self.staff.index:
            #日曜祝日勤務をカウントする変数を作成
            sunday_holiday_work_count = self.model.NewIntVar(0, self.days, f'sunday_holiday_work_count_{staff}')
            target_sections =set(PRIMARY_SECTIONS.keys())            
            staff_work_sections =  target_sections & set(self.eligible_sections.get(staff, []))
            self.model.Add(
                sunday_holiday_work_count == sum(
                    self.shifts[(staff, day, section)]
                    for day in range(1, self.days + 1)
                    for section in staff_work_sections
                    if (self._get_weekday(day) == 6 or self._is_holiday(day) or day in {363, 364, 365, 1, 2, 3})
                    if (staff, day, section) in self.shifts
                )
            )
            # 1回を超えた出勤分をペナルティ変数として計上（ソフト制約）
            excess_var = self.model.NewIntVar(0, self.days, f'sunday_holiday_excess_{staff}')
            self.model.Add(excess_var >= sunday_holiday_work_count - 1)
            self.model.Add(excess_var >= 0)
            penalties.append(excess_var)
        return penalties

    def add_primary_section_fairness_penalties(self):
        """
        専属業務ごとの担当回数の偏り（max-min）をソフト制約で抑制する。
        - Floor列の主所属に対応するスタッフ間で計算する。
        - Floor2とFloor3は無視する
        """
        penalties = []
        floor_to_section = {
            FLOOR_MAPPING[floor_name]: section
            for floor_name, section in {
                '1-2': 4,
                'DI': 8,
                '3': 5,
                '4': 6,
                '5': 7,
                '化療': 9,
                '調剤': 1,
                '外来': 16,
                '部長': 26,
                '入退院センター': 3,
                'RI': 22,
                '課長': 25,
                '医療安全・感染管理': 14,
            }.items()
        }

        fairness_sections = [
            section for section in self.primary_sections
            if section != 17 and section in floor_to_section.values()
        ]

        for section in fairness_sections:
            floor = next(
                floor for floor, mapped_section in floor_to_section.items()
                if mapped_section == section
            )
            fairness_staff = [
                staff for staff in self.staff.index
                if self.staff.loc[staff, 'Floor'] == floor
            ]
            if len(fairness_staff) <= 1:
                continue

            section_counts = []
            for staff in fairness_staff:
                count_var = self.model.NewIntVar(
                    0,
                    self.days,
                    f'primary_section_count_{section}_{staff}',
                )
                self.model.Add(
                    count_var == sum(
                        self.shifts[(staff, day, section)]
                        for day in range(1, self.days + 1)
                    )
                )
                section_counts.append(count_var)

            max_count = self.model.NewIntVar(
                0,
                self.days,
                f'primary_section_max_{section}',
            )
            min_count = self.model.NewIntVar(
                0,
                self.days,
                f'primary_section_min_{section}',
            )
            spread = self.model.NewIntVar(
                0,
                self.days,
                f'primary_section_spread_{section}',
            )

            self.model.AddMaxEquality(max_count, section_counts)
            self.model.AddMinEquality(min_count, section_counts)
            self.model.Add(spread == max_count - min_count)
            penalties.append(spread)
        
    
        print(f"専属業務の公平性ペナルティ変数: {len(penalties)}個作成")
        return penalties

    def _get_work_day_var(self, staff, day):
        cache_key = (staff, day)
        if cache_key in self._work_day_vars:
            return self._work_day_vars[cache_key]

        non_off_sections = [
            section for section in self.primary_sections
            if section in self.eligible_sections.get(staff, []) and section != 0
        ]

        work_day = self.model.NewBoolVar(f'work_day_{staff}_{day}')
        if non_off_sections:
            self.model.Add(
                work_day == sum(
                    self.shifts[(staff, day, section)]
                    for section in non_off_sections
                )
            )
        else:
            self.model.Add(work_day == 0)

        self._work_day_vars[cache_key] = work_day
        return work_day

    def _build_max_consecutive_streak_var(self, staff, indicator_getter, prefix):
        streak_vars = []
        prev_streak = None

        for day in range(1, self.days + 1):
            indicator = indicator_getter(day)
            streak = self.model.NewIntVar(0, self.days, f'{prefix}_streak_{staff}_{day}')

            if day == 1:
                self.model.Add(streak == 1).OnlyEnforceIf(indicator)
                self.model.Add(streak == 0).OnlyEnforceIf(indicator.Not())
            else:
                self.model.Add(streak == prev_streak + 1).OnlyEnforceIf(indicator)
                self.model.Add(streak == 0).OnlyEnforceIf(indicator.Not())

            streak_vars.append(streak)
            prev_streak = streak

        max_streak = self.model.NewIntVar(0, self.days, f'{prefix}_max_{staff}')
        self.model.AddMaxEquality(max_streak, streak_vars)
        return max_streak

    def _get_staff_max_consecutive_work_var(self, staff):
        """スタッフの最大連勤日数を表す変数を取得または作成する。"""
        if staff in self._staff_max_consecutive_work_vars:
            return self._staff_max_consecutive_work_vars[staff]

        max_streak = self._build_max_consecutive_streak_var(
            staff=staff,
            indicator_getter=lambda day: self._get_work_day_var(staff, day),
            prefix='work',
        )
        self._staff_max_consecutive_work_vars[staff] = max_streak
        return max_streak

    def _get_staff_max_consecutive_off_var(self, staff):
        """スタッフの最大連休日数を表す変数を取得または作成する。"""
        if staff in self._staff_max_consecutive_off_vars:
            return self._staff_max_consecutive_off_vars[staff]

        max_streak = self._build_max_consecutive_streak_var(
            staff=staff,
            indicator_getter=lambda day: self.shifts[(staff, day, 0)],
            prefix='off',
        )
        self._staff_max_consecutive_off_vars[staff] = max_streak
        return max_streak

    def add_consecutive_streak_fairness_penalties(
        self,
        work_tolerance=CONSECUTIVE_WORK_FAIRNESS_TOLERANCE,
        off_tolerance=CONSECUTIVE_OFF_FAIRNESS_TOLERANCE,
    ):
        """
        同一セクション担当可能者間の連勤・連休偏りを抑える。
        「Floor」列対象スタッフ間で公平性を計算
        [Floor2]と[floor3]は対象外
        """
        work_penalties = []
        off_penalties = []
        fairness_sections = [
            section for section in self.primary_sections
            if section not in (0, 17)
        ]

        for section in fairness_sections:
            eligible_staff = [
                staff for staff in self.staff.index
                if section in self.eligible_sections.get(staff, [])
            ]
            if len(eligible_staff) <= 1:
                continue

            max_work_by_staff = [
                self._get_staff_max_consecutive_work_var(staff)
                for staff in eligible_staff
            ]
            max_off_by_staff = [
                self._get_staff_max_consecutive_off_var(staff)
                for staff in eligible_staff
            ]

            section_work_max = self.model.NewIntVar(0, self.days, f'section_work_max_{section}')
            section_work_min = self.model.NewIntVar(0, self.days, f'section_work_min_{section}')
            section_work_spread = self.model.NewIntVar(0, self.days, f'section_work_spread_{section}')
            section_work_excess = self.model.NewIntVar(0, self.days, f'section_work_excess_{section}')

            self.model.AddMaxEquality(section_work_max, max_work_by_staff)
            self.model.AddMinEquality(section_work_min, max_work_by_staff)
            self.model.Add(section_work_spread == section_work_max - section_work_min)
            self.model.Add(section_work_excess >= section_work_spread - work_tolerance)
            self.model.Add(section_work_excess >= 0)
            work_penalties.append(section_work_excess)

            section_off_max = self.model.NewIntVar(0, self.days, f'section_off_max_{section}')
            section_off_min = self.model.NewIntVar(0, self.days, f'section_off_min_{section}')
            section_off_spread = self.model.NewIntVar(0, self.days, f'section_off_spread_{section}')
            section_off_excess = self.model.NewIntVar(0, self.days, f'section_off_excess_{section}')

            self.model.AddMaxEquality(section_off_max, max_off_by_staff)
            self.model.AddMinEquality(section_off_min, max_off_by_staff)
            self.model.Add(section_off_spread == section_off_max - section_off_min)
            self.model.Add(section_off_excess >= section_off_spread - off_tolerance)
            self.model.Add(section_off_excess >= 0)
            off_penalties.append(section_off_excess)

        print(f"連勤公平性ペナルティ変数: {len(work_penalties)}個作成")
        print(f"連休公平性ペナルティ変数: {len(off_penalties)}個作成")
        return work_penalties, off_penalties

    def add_porifa_pair_penalties(self):
        """
        金曜ポリファ（第W週）と火曜ポリファ（第W+1週）の連続週ペア開催を推奨するソフト制約。
        火曜・金曜ともに開催されるが、連続週ペアになっていない場合にペナルティを加算する。
        """
        fri_vars = self.optimizer.porifa_friday_vars
        tue_vars = self.optimizer.porifa_tuesday_vars
        if not fri_vars or not tue_vars:
            return []

        pair_vars = []
        for fri_day, fri_hold in fri_vars.items():
            fri_week = (fri_day - 1) // 7 + 1
            for tue_day, tue_hold in tue_vars.items():
                tue_week = (tue_day - 1) // 7 + 1
                # 第W週金曜 と 第W+1週火曜 のペア
                if tue_week == fri_week + 1 and 0 < tue_day - fri_day <= 7:
                    is_pair = self.model.NewBoolVar(f'porifa_pair_fri_{fri_day}_tue_{tue_day}')
                    self.model.AddMinEquality(is_pair, [fri_hold, tue_hold])
                    pair_vars.append(is_pair)

        if not pair_vars:
            return []

        # ペアが成立しているかを判定
        any_pair_held = self.model.NewBoolVar('porifa_consecutive_pair_held')
        self.model.AddMaxEquality(any_pair_held, pair_vars)

        # 火曜・金曜それぞれで開催されるか
        any_fri = self.model.NewBoolVar('any_porifa_friday_held')
        self.model.AddMaxEquality(any_fri, list(fri_vars.values()))
        any_tue = self.model.NewBoolVar('any_porifa_tuesday_held')
        self.model.AddMaxEquality(any_tue, list(tue_vars.values()))

        # 両方開催されているのにペアになっていない場合にペナルティ
        both_held = self.model.NewBoolVar('both_porifa_held')
        self.model.AddMinEquality(both_held, [any_fri, any_tue])

        unpaired_penalty = self.model.NewBoolVar('penalty_porifa_not_paired')
        self.model.Add(unpaired_penalty == 1).OnlyEnforceIf([both_held, any_pair_held.Not()])
        self.model.Add(unpaired_penalty == 0).OnlyEnforceIf(both_held.Not())
        self.model.Add(unpaired_penalty == 0).OnlyEnforceIf(any_pair_held)

        return [unpaired_penalty]

    def apply_weighted_dayworkpenalties(
        self,
        sunday_holiday_penalties=None,
        consecutive_work_penalties=None,
        porifa_tuesday_penalties = None):
        """
        重みづけした目的関数を設定
        """
        oncall_nextday_penalties = self.add_day_off_oncallnextday()
        
        #結合した目的関数
        sunday_penalty_term = WEIGHT_SUNDAY_HOLIDAY * sum(sunday_holiday_penalties) if sunday_holiday_penalties else 0
        consecutive_work_penalty_term = WEIGHT_CONSECUTIVE_WORK * sum(consecutive_work_penalties) if consecutive_work_penalties else 0
        
        #役職者会議のペナルティを追加
        fixed_manager_meeting_penalties = self.meeting_constraints.fixed_manager_meeting()
        fixed_manager_meeting = WEIGHT_FIXED_MANAGER_MEETING * sum(fixed_manager_meeting_penalties) if fixed_manager_meeting_penalties else 0
        
        #薬剤部連絡会(役職者)のペナルティを追加
        fixed_general_meeting_penalties = self.meeting_constraints.general_meeting()
        fixed_general_meeting = WEIGHT_FIXED_GENERAL_MEETING * sum(fixed_general_meeting_penalties) if fixed_general_meeting_penalties else 0
        
        #薬審のペナルティを追加
        fixed_yakushin_meeting_penalties = self.meeting_constraints.yakushin()
        fixed_yakushin_meeting = WEIGHT_FIXED_YAKUSHIN_MEETING * sum(fixed_yakushin_meeting_penalties) if fixed_yakushin_meeting_penalties else 0

        #第三金曜日の臨床薬剤課役職者会議のペナルティを追加
        fixed_medical_safety_working_group_penalties = self.meeting_constraints.fixed_medical_safety_working_group()
        fixed_medical_safety_working_group = (
            WEIGHT_FIXED_MEDICAL_SAFETY_WORKING_GROUP
            * sum(fixed_medical_safety_working_group_penalties)
            if fixed_medical_safety_working_group_penalties
            else 0
        )
        
        # ポリファ（金曜日）の日はなるべく出勤とするペナルティを追加
        porifa_friday_penaltiles = self.concurrent_constraints.add_concurrent_porifa()
        porifa_friday_penalty_term = WEIGHT_PORIFA_FRIDAY * sum(porifa_friday_penaltiles) if porifa_friday_penaltiles else 0
        
        # ポリファ連続週ペア（第W週金曜＋第W+1週火曜）の推奨ペナルティを追加
        porifa_pair_penalties = self.add_porifa_pair_penalties()
        porifa_pair_penalty_term = WEIGHT_PORIFA_PAIR * sum(porifa_pair_penalties) if porifa_pair_penalties else 0
        
        
        primary_fairness_penalties = self.add_primary_section_fairness_penalties()
        primary_fairness_penalty_term = WEIGHT_PRIMARY_FAIRNESS * sum(primary_fairness_penalties) if primary_fairness_penalties else 0
        
        #第二金曜日、病棟担当者カンファレンス参加のペナルティを追加
        second_friday_conference_penalties = self.meeting_constraints.second_friday_conference()
        second_friday_conference_penalty_term = WEIGHT_SECOND_FRIDAY_CONFERENCE * sum(second_friday_conference_penalties) if second_friday_conference_penalties else 0

        #課長かつDI所属スタッフの16日から23日までの出勤希望のペナルティを追加
        general_manager_penalties = self.meeting_constraints.day16to23()
        manager_penalty_term = WEIGHT_MANAGER * sum(general_manager_penalties) if general_manager_penalties else 0
        
        streak_work_fairness_penalties, streak_off_fairness_penalties = self.add_consecutive_streak_fairness_penalties()
        streak_work_fairness_term = (
            WEIGHT_CONSECUTIVE_WORK_FAIRNESS * sum(streak_work_fairness_penalties)
            if streak_work_fairness_penalties
            else 0
        )
        streak_off_fairness_term = (
            WEIGHT_CONSECUTIVE_OFF_FAIRNESS * sum(streak_off_fairness_penalties)
            if streak_off_fairness_penalties
            else 0
        )
        if self.month in [12,1]:
            #12月または1月シフト作成時にのみ有効
            #12月シフト作成時にのみ有効
            previous_year_december_30_penalties = [
                self.shifts[(staff, 30, section)]
                for staff in self.staff.index
                if self._is_previous_year_december_30_staff(staff, 30)
                for section in self.primary_sections
            ]
            #12月シフト作成時にのみ有効にする
            previous_year_december_30_penalty_term = (
                WEIGHT_PREVIOUS_YEAR_DECEMBER_30_AVOIDANCE
                * sum(previous_year_december_30_penalties)
                if previous_year_december_30_penalties
                else 0
            )
            #12月シフト作成時にのみ有効にする
            previous_december_31_penalties = [
                self.shifts[(staff, 31, section)]
                for staff in self.staff.index
                if self._is_previous_december_31_staff(staff, 31)
                for section in self.primary_sections
            ]
            #12月シフト作成時にのみ有効にする
            previous_december_31_penalty_term = (
                WEIGHT_PREVIOUS_DECEMBER_31_AVOIDANCE
                * sum(previous_december_31_penalties)
                if previous_december_31_penalties
                else 0
            )
            #1月1日に去年と同じスタッフが出勤していた場合のペナルティを取得
            #1月シフト作成時にのみ有効にする
            previous_january_1_penalties = [
                self.shifts[(staff,1,section)]
                for staff in self.staff.index
                if self._is_previous_january_1_staff(staff,1)
                for section in self.primary_sections
            ]
            previous_january_1_penalty_term = (
                WEIGHT_PREVIOUS_JANUARY_1_AVOIDANCE
                * sum(previous_january_1_penalties)
                if previous_january_1_penalties
                else 0
            )
            #1月シフト作成時にのみ有効にする
            #1/2
            previous_january_2_penalties = [
                self.shifts[(staff,2,section)]
                for staff in self.staff.index
                if self._is_previous_january_2_staff(staff,2)
                for section in self.primary_sections
            ]
            previous_january_2_penalty_term = (
                WEIGHT_PREVIOUS_JANUARY_2_AVOIDANCE
                * sum(previous_january_2_penalties)
                if previous_january_2_penalties
                else 0
            )
            #1/3
            previous_january_3_penalties = [
                self.shifts[(staff,3,section)]
                for staff in self.staff.index
                if self._is_previous_january_3_staff(staff,3)
                for section in self.primary_sections
            ]
            previous_january_3_penalty_term = (
                WEIGHT_PREVIOUS_JANUARY_3_AVOIDANCE
                * sum(previous_january_3_penalties)
                if previous_january_3_penalties
                else 0
            )
        total_penalty = (
            WEIGHT_ONCALL_NEXTDAY * sum(oncall_nextday_penalties)
            + sunday_penalty_term
            + consecutive_work_penalty_term
            + fixed_manager_meeting
            + fixed_general_meeting
            + fixed_yakushin_meeting
            + fixed_medical_safety_working_group
            + porifa_friday_penalty_term
            + porifa_pair_penalty_term
            + primary_fairness_penalty_term
            + streak_work_fairness_term
            + streak_off_fairness_term
            + second_friday_conference_penalty_term
            + manager_penalty_term
        )
        if self.month in [12, 1]:
            total_penalty += (
                previous_year_december_30_penalty_term
                + previous_december_31_penalty_term
                + previous_january_1_penalty_term
                + previous_january_2_penalty_term
                + previous_january_3_penalty_term
            )
        self.optimizer.register_objective_term("work_constraints", total_penalty)