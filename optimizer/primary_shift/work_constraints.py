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
    WEIGHT_PORIFA_FRIDAY,
    WEIGHT_CHEMO_SATURDAY,
    WEIGHT_PRIMARY_FAIRNESS,
    WEIGHT_CONSECUTIVE_WORK_FAIRNESS,
    WEIGHT_CONSECUTIVE_OFF_FAIRNESS,
    CONSECUTIVE_WORK_FAIRNESS_TOLERANCE,
    CONSECUTIVE_OFF_FAIRNESS_TOLERANCE,
    WEIGHT_SECOND_FRIDAY_CONFERENCE,
    WEIGHT_MANAGER,
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
            #デバッグ用
            print(f"スタッフ{staff}の{day-1}日の当直ペア変数: {prev_day_oncall}")
            if prev_day_oncall:
                self.model.AddMaxEquality(had_oncall_yesterday, prev_day_oncall)
                #デバッグ用
            else:
                self.model.Add(had_oncall_yesterday == 0)
        else:
            # 前月末の当直担当者リストが与えられている場合は day=1 の明けへ反映する
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
        self.add_on_call_primary_section_constraint()#当直日に専属業務を休みにしない
        self.add_on_call_day_off_nextday_constraints()#当直明けの制約を適用
    
        sunday_holiday_penalties = self.add_sunday_holiday_work_constraints()#日曜祝日の出勤は可能な限り月1回までとする
        consecutive_work_penalties = self.add_consecutive_work_constraints()#連続勤務の制約（超過ペナルティ）を追加
        #ポリファ開催は第何週になるかの判定
        self.tuesday_porifa_week_num ,self.friday_porifa_week_num = self.meeting_constraints.get_porifa_week_num()#火曜と金曜のポリファ開催週を判定
        self.apply_weighted_dayworkpenalties(
            sunday_holiday_penalties,
            consecutive_work_penalties,
            )#重みづけした目的関数を設定
        """当直明けの休みの制約"""
        self.add_section_requests()#セクションごとの配置数人
        
    def _add_basic_constraints(self):
        """専属業務は1人1日1セクションのみ"""
        # 1. 専属業務は1人1日1セクションのみ
        for staff in self.staff.index:
            #primary_sections のうち、割り当て可能なセクションのみを対象とする
            staff_primary_sections = [s for s in self.primary_sections if s in self.eligible_sections[staff]]
            #staff_primary_sectionsが空の場合はデフォルトのself.staff_primary_sectionsを使用
            if not staff_primary_sections:
                staff_primary_sections = list(self.primary_sections)
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
                    # 2. 兼務業務は出勤している（休みでない）場合のみ割り当て可能
                    # 専属業務に「休み(0)」以外が少なくとも1つある場合のみ兼務可能
                    non_off_sections = [s for s in staff_primary_sections if s != 0]
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
        
        """
        for staff in self.staff.index:
            for day in range(1, self.days + 1):
                if self._get_hope_value(staff, day, default=7) == 0: #休み希望がある場合
                    self.model.Add(
                        sum(self.shifts[(staff, day, section)] for section in self.primary_sections) == 0  
                    )
                elif self._get_hope_value(staff, day, default=7) == 3:
                    self.model.Add(
                        sum(self.shifts[(staff, day, section)] for section in self.primary_sections) == 0  
                    )
        
                    
    #該当者は基本的に日曜祝日は休みにする
    
    def add_on_call_primary_section_constraint(self):
        """
        当直に割り当てられている日に専属業務を休みにしない !=0
        - ハード制約
        - TODO:前月の月末が当直の場合は、月初の1日も当直明けとして扱う必要がある
        """
        print("当直日に専属業務を休みにしない制約を適用します。")
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
                
                #非休み・非明けの専属業務
                staff_primary_sections = [
                    s for s in self.primary_sections
                    if s in self.eligible_sections[staff] and s != 0 and s != 17
                ]
                if not staff_primary_sections:
                    #選択肢がないスタッフはその日は当直不可にして矛盾を防ぐ
                    self.model.Add(oncall_today == 0)
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
        floor_sections = [1,2,3,4, 5, 6, 7, 8, 9,10, 11, 14,16,18,19,20,21,22,23,24,25,26]  # section_id の17(明け)以外
        #TODO:sections.pyからインポートする,17以外で定義する

        for staff in self.staff.index:
            for day in range(1, self.days + 1):
                had_oncall_yesterday = self._get_had_oncall_yesterday_var(staff, day)#前日に当直があったかどうかの変数を取得
                print(f"スタッフ{staff}の{day}日の前日当直変数: {had_oncall_yesterday}")
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

                # 当日が明けの場合,業務には割り当てない
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
            if (self.staff.loc[staff, 'Floor'] == 9) and (self._get_hope_value(staff, day, default=7) == 3):
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
            chemo_required = 0

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

            available_count = available_counts.get(section_name, 0)
            if not isinstance(available_count, numbers.Real):
                print(f"ℹ️ [事前検証] Day {day} {section_name}: 当直明け依存のため静的検証をスキップ")
                continue
            if available_count < required_count:
                conflict_messages.append(
                    f"{section_name}: 必要{required_count}人 / 配置可能上限{available_count}人"
                )

        if conflict_messages:
            print(f"🚨 [事前検証] Day {day}: 競合候補を検出")
            for message in conflict_messages:
                print(f"   - {message}")
            return False

        return True
                
    ##配置
    def add_section_requests(self):
        porifa_tuesday_penalties= []
        hold_porifa_tuesday_vars = []
        porifa_tuesday_schedulable_vars = []
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
            

            #配置可能なスタッフリスト
            assigned_staff_12 = []
            assigned_staff_3 = []
            assigned_staff_4 = []
            assigned_staff_5 = []
            assigned_staff_chemo = []
            assigned_staff_di = []
            di_eligible_staff_ids = []
            assigned_staff_dispensing = []
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
            
            #必須メンバーのリスト
            required_staff_12 = [7,10,11,14]  #休み希望の場合は条件より除外する
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
                '調剤室': {
                    'section_id': floor_dispensing_section_id,
                    'assigned_list': assigned_staff_dispensing,
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
                    'check_day_off': False,
                    'check_oncall_next': False,
                },
                'NST':{#配置可能な業務として登録するが、専属業務のシフトには含めない
                    'section_id':floor_nst_id,
                    'assigned_list': assigned_staff_nst,
                    'available_list': [],
                    'check_day_off': False,
                    'check_oncall_next': False,
                },
                '実習':{#配置可能な業務として登録するが、専属業務のシフトには含めない
                    'section_id':floor_jishu_id,
                    'assigned_list': assigned_staff_jishu,
                    'available_list': [],
                    'check_day_off': False,
                    'check_oncall_next': False,
                },
                'マスター管理':{#配置可能な業務として登録するが、専属業務のシフトには含めない
                    'section_id':floor_master_id,
                    'assigned_list': assigned_staff_master,
                    'available_list': [],
                    'check_day_off': False,
                    'check_oncall_next': False,
                },
                'RI':{#配置可能な業務として登録するが、専属業務のシフトには含めない
                    'section_id':floor_ri_id,
                    'assigned_list': assigned_staff_ri,
                    'available_list': [],
                    'check_day_off': False,
                    'check_oncall_next': False,
                },
                '課長業務':{#配置可能な業務として登録するが、専属業務のシフトには含めない
                    'section_id':floor_kacho_id,
                    'assigned_list': assigned_staff_kacho,
                    'available_list': [],
                    'check_day_off': False,
                    'check_oncall_next': False,
                },
                '医薬品安全使用WG':{#配置可能な業務として登録するが、専属業務のシフトには含めない
                    'section_id':floor_safetyWG_id,
                    'assigned_list': assigned_staff_safetyWG,
                    'available_list': [],
                    'check_day_off': False,
                    'check_oncall_next': False,
                }
            }
            
            self._build_section_availability(section_configs=section_configs,day = day,
                                            required_staff_12_available=required_staff_12_available,
                                            required_staff_12_assigned=required_staff_12_assigned,
                                            required_staff_12=required_staff_12,
                                            di_eligible_staff_ids=di_eligible_staff_ids,
                                            porifa_staff_ids=porifa_staff_ids,)            

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
        
            requirements = self._get_section_min_requirements(
                day=day,
                weekday=weekday,
                is_holiday=is_holiday,
                prev_day_is_holiday=prev_day_is_holiday,
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
                    
            """
            ポリファーマシーチーム
            - 一日専属の火曜日と半日のみの金曜日がある
            - こちらで設定するのは1日専属の火曜日のみ
            - 所属メンバー全員が揃っている火曜日もしくは金曜日に配置する
            - 金曜半日午後は兼務業務で設定する
            - len(assigned_staff_porifa) == len(eligible_staff_porifa) で全員が配置可能か確認
            - 所属メンバーは条件.xlsx floor=11のスタッフ
            - 週に入れられるのは火曜日もしくは金曜日のどちらか一方、get_porifa_week_numで定義すみ
            - TODO:最低月1回以上はほしい
            - どちらも存在しない週も可
            - get_porifa_week_numで算出した週番号をもとにポリファーマシーメンバーを確保する
            - メンバーに入れたら該当病棟の配置必須スタッフより除外
            """
            available_porifa_vars = section_configs['ポリファーマシー']['available_list']
            registered_porifa_count = len(assigned_staff_porifa)
            eligible_porifa_count = len(porifa_staff_ids)
            
            if is_tuesday and not is_holiday and self.tuesday_porifa_week_num == (day-1)//7 +1:#火曜日かつ祝日でなく、tuesday_porifa_week_numの週番号と一致する場合
                print(f"day{day}: ポリファーマシー配置の対象日です。")
                hold_porifa_tuesday = self.model.NewBoolVar(f'hold_porifa_tuesday_{day}')
                hold_porifa_tuesday_vars.append(hold_porifa_tuesday)

                
                porifa_tuesday_schedulable = self.model.NewBoolVar(f'porifa_tuesday_schedulable_{day}')#ポリファーマシー火曜日開催可能かどうかの変数
                porifa_tuesday_schedulable_vars.append(porifa_tuesday_schedulable)#

                if available_porifa_vars and registered_porifa_count == eligible_porifa_count:
                    self.model.AddMinEquality(porifa_tuesday_schedulable, available_porifa_vars)
                    self.model.Add(hold_porifa_tuesday == porifa_tuesday_schedulable)#
                    self.model.Add(
                        sum(assigned_staff_porifa) == registered_porifa_count
                    ).OnlyEnforceIf(hold_porifa_tuesday)
                    self.model.Add(sum(assigned_staff_porifa) == 0).OnlyEnforceIf(hold_porifa_tuesday.Not())
                    print(
                        f"day{day}: ポリファーマシーは全{registered_porifa_count}人が配置可能な場合のみ開催します。"
                    )
                else:
                    self.model.Add(hold_porifa_tuesday == 0)
                    self.model.Add(porifa_tuesday_schedulable == 0)
                    self.model.Add(sum(assigned_staff_porifa) == 0)
                    print(
                        f"day{day}: ポリファーマシーは登録{registered_porifa_count}人中、"
                        f"休み希望等を除く候補が{eligible_porifa_count}人のため開催しません。"
                    )
            #tuesday_porifa_week_numの週番号以外の火曜日は配置しない
            else:
                self.model.Add(sum(assigned_staff_porifa) == 0)
                print(f"day{day}: ポリファーマシー配置の対象日ではありません。")
                
            """
            12F
            - weekdayの場合、3人配置
            - 日祝日は0人、上で定義済み
            """
            print(f"day{day}:編集後の12F必須メンバーリスト{required_staff_12}")
            print(f"day{day}:編集後の配置可能リストに基づく12Fの配置必須メンバーのavailable_list: {[var.Name() for var in required_staff_12_available]}")
            if not is_sunday and not is_holiday:
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
                    effective_required_12f = self.model.NewIntVar(0, required_12f, f'12f_effective_required_{day}')
                    self.model.AddMinEquality(effective_required_12f, [n_avail_12f, required_12f])
                    self.model.Add(sum(assigned_staff_12) >= effective_required_12f)
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

            if is_tuesday and not is_holiday:
                required_3f = 5
                if available_3f_vars:
                    effective_required = self.model.NewIntVar(0, required_3f, f'3f_effective_required_{day}')
                    self.model.AddMinEquality(effective_required, [n_avail_3f, required_3f])
                    self.model.Add(sum(assigned_staff_3) >= effective_required)
                    print(f"day{day}: 3Fの配置人数は{required_3f}人です。(上限は{len(available_3f_vars)}人)")
            elif not is_sunday and not is_holiday:
                required_3f = 4
                if available_3f_vars:
                    effective_required = self.model.NewIntVar(0, required_3f, f'3f_effective_required_{day}')
                    self.model.AddMinEquality(effective_required, [n_avail_3f, required_3f])
                    self.model.Add(sum(assigned_staff_3) >= effective_required)
                    print(f"day{day}: 3Fの配置人数は{required_3f}人です。(上限は{len(available_3f_vars)}人)")

            """
            4階：月のみ5名、他は4名。
            - 日曜祝日は0名、上で定義済み
            """
            available_4f_vars = section_configs['4F']['available_list']
            n_acvailable_4f = sum(available_4f_vars)  # CP-SAT式: 実際に配置可能な人数
            
            if is_monday and not is_holiday:
                required_4f = 5
                if available_4f_vars:
                    effective_required = self.model.NewIntVar(0, required_4f, f'4f_effective_required_{day}')
                    self.model.AddMinEquality(effective_required, [n_acvailable_4f, required_4f])
                    self.model.Add(sum(assigned_staff_4) >= effective_required)
                    print(f"day{day}: 4Fの配置人数は{required_4f}人です。(上限は{len(available_4f_vars)}人)")
            elif not is_sunday and not is_holiday:
                required_4f = 4
                if available_4f_vars:
                    effective_required = self.model.NewIntVar(0, required_4f, f'4f_effective_required_{day}')
                    self.model.AddMinEquality(effective_required, [n_acvailable_4f, required_4f])
                    self.model.Add(sum(assigned_staff_4) >= effective_required)
                    print(f"day{day}: 4Fの配置人数は{required_4f}人です。(上限は{len(available_4f_vars)}人)")
            
            """
            5階：連休明けでない火曜は4名、月・水は5名、木～土は4名
            - 日曜祝日は0名、上で定義済み
            - 連休明けの定義：前日が祝日、もしくは祝日の次の日が火曜日の場合
            - 連休明け火曜は5名
            - それ以外の火曜は4名
            """
            available_5f_vars  = section_configs['5F']['available_list']
            n_available_5f = sum(available_5f_vars)  # CP-SAT式: 実際に配置可能な人数
            
            if is_tuesday and prev_day_is_holiday:#連休明け火曜
                required_5f = 5
                if available_5f_vars:
                    effective_required = self.model.NewIntVar(0, required_5f, f'5f_effective_required_{day}')
                    self.model.AddMinEquality(effective_required, [n_available_5f, required_5f])
                    self.model.Add(sum(assigned_staff_5) >= effective_required)
                    print(f"day{day}: 5Fの配置人数は{required_5f}人です（連休明け火曜のため）。(上限は{len(available_5f_vars)}人)")
            elif (is_monday and not is_holiday) or (is_wednesday and not is_holiday):#平日の月・水
                required_5f = 5
                if available_5f_vars:
                    effective_required = self.model.NewIntVar(0, required_5f, f'5f_effective_required_{day}')
                    self.model.AddMinEquality(effective_required, [n_available_5f, required_5f])
                    self.model.Add(sum(assigned_staff_5) >= effective_required)
                    print(f"day{day}: 5Fの配置人数は{required_5f}人です（月・水のため）。(上限は{len(available_5f_vars)}人)")
            elif is_tuesday and not prev_day_is_holiday:#通常の火曜は4名
                #可能人数が4人以上ならば最低人数を4人とする
                #4人未満ならば、配置可能人数を最低人数とする
                if available_5f_vars:
                    effective_required = self.model.NewIntVar(0, 4, f'5f_effective_required_{day}')
                    self.model.AddMinEquality(effective_required, [n_available_5f, 4])
                    self.model.Add(sum(assigned_staff_5) >= effective_required)
                    print(f"day{day}: 5Fの配置人数は4人です（通常の火曜のため）。(上限は{len(available_5f_vars)}人)")
            elif (is_thursday or is_friday or is_saturday) and not is_holiday:#木～土
                if available_5f_vars:
                    effective_required = self.model.NewIntVar(0, 4, f'5f_effective_required_{day}')
                    self.model.AddMinEquality(effective_required, [n_available_5f, 4])
                    self.model.Add(sum(assigned_staff_5) >= effective_required)
                    print(f"day{day}: 5Fの配置人数は4人です（木～土のため）。(上限は{len(available_5f_vars)}人)")
            """
            化学療法 floor=6
            - 育休中のスタッフがいる場合、月〜金は3名
            - hope_list == 3(育休)
            - 育休中のスタッフがいない場合、月〜金は4名
            - 土曜日（専属業務）は0名
            - TODO:土曜日は調剤室に配置されるので、化学療法は土曜日に限り兼務業務に配置する
            - 日曜祝日は0名、上で定義済み
            - 土曜日（専属業務）は0名、上で定義すみ
            """
            available_chemo_vars = section_configs['化療']['available_list']
            n_avail_chemo = sum(available_chemo_vars)  # CP-SAT式: 実際に配置可能な人数
            
            if is_weekday and not is_holiday:#月〜金
                required_chemo = 3 if self._has_maternity_leave_in_chemo(day) else 4
                chemo_available_expr = sum(section_configs['化療']['available_list'])
                print(f"day{day}:化学療法の配置可能人数（当直明け反映）は {chemo_available_expr} です。育休中のスタッフがいるか確認します。")
                if available_chemo_vars:
                    effective_required = self.model.NewIntVar(0, required_chemo, f'chemo_effective_required_{day}')
                    self.model.AddMinEquality(effective_required, [n_avail_chemo, required_chemo])
                    self.model.Add(sum(assigned_staff_chemo) >= effective_required)
                    if self._has_maternity_leave_in_chemo(day):
                        print(f"day{day}: 化学療法の配置人数は{required_chemo}人です（育休中のスタッフがいるため）。(上限は{len(available_chemo_vars)}人)")
                    else:
                        print(f"day{day}: 化学療法の配置人数は{required_chemo}人です（育休中のスタッフがいないため）。(上限は{len(available_chemo_vars)}人)")
            
            """
            DI
            - 2月前、の週の5日間は1日2名 薬審:偶数月の第一木曜日
            - 1名になる日は月曜日以外なら可
            - それ以外は月のみ2名、火～土は1名。(name==6は除く)
            - 火～土はname==6以外のメンバーで1名以上配置,name6の勤務希望はDIとは別セクションで定義
            - 日曜祝日は0名、上で定義済み
            - 出勤希望がなければ配置は0名を許容
            """
            yakushin_month = [2,8,10,12]
            pre_yakushin_month = [(m-1) if m>1 else 12 for m in yakushin_month]
            available_di_vars = section_configs['DI']['available_list']
            n_avail_di = sum(available_di_vars)  # CP-SAT式: 実際に配置可能な人数
            
            if self.month in pre_yakushin_month:
                #当月の最終5日間を取得
                last_week_days = [d for d in range(self.days-4,self.days +1)]
                print(f"DIの当月最終5日間: {last_week_days}")
                if day in last_week_days and not is_holiday:
                    required_di = 2
                    if available_di_vars:
                        effective_required = self.model.NewIntVar(0, required_di, f'di_effective_required_{day}')
                        self.model.AddMinEquality(effective_required, [n_avail_di, required_di])
                        self.model.Add(sum(assigned_staff_di) >= effective_required)
                        print(f"day{day}: DIの配置人数は{required_di}人です（当月最終5日間のため）。(上限は{len(available_di_vars)}人)")
                elif is_monday and not is_holiday:
                    required_di = 2
                    if available_di_vars:
                        effective_required = self.model.NewIntVar(0, required_di, f'di_effective_required_{day}')
                        self.model.AddMinEquality(effective_required, [n_avail_di, required_di])
                        self.model.Add(sum(assigned_staff_di) >= effective_required)
                elif (is_tuesday and not is_holiday) or (is_wednesday and not is_holiday) or (is_thursday and not is_holiday) or(is_friday and not is_holiday) or (is_saturday and not is_holiday): 
                    required_di = 1
                    if available_di_vars:
                        effective_required = self.model.NewIntVar(0, required_di, f'di_effective_required_{day}')
                        self.model.AddMinEquality(effective_required, [n_avail_di, required_di])
                        self.model.Add(sum(assigned_staff_di) >= effective_required)
                
            else:
                if is_monday and not is_holiday:#月曜
                    required_di = 2
                    if available_di_vars:
                        effective_required = self.model.NewIntVar(0, required_di, f'di_effective_required_{day}')
                        self.model.AddMinEquality(effective_required, [n_avail_di, required_di])
                        self.model.Add(sum(assigned_staff_di) >= effective_required)
                elif (is_tuesday and not is_holiday) or (is_wednesday and not is_holiday) or (is_thursday and not is_holiday) or(is_friday and not is_holiday) or (is_saturday and not is_holiday):#火〜土
                    required_di = 1
                    if available_di_vars:
                        effective_required = self.model.NewIntVar(0, required_di, f'di_effective_required_{day}')
                        self.model.AddMinEquality(effective_required, [n_avail_di, required_di])
                        self.model.Add(sum(assigned_staff_di) >= effective_required)
                
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
            - TODO:GW、年末年始を除く
            - 兼務業務と比較して午前のみ、午後のみのスタッフが生じる場合には1日の必要人数を+1
            - 化学療法(課長)は平日化学療法、土曜日のみ調剤室配置可能とする
            - 化学療法室&課長&主任以上のスタッフは平日調剤室配置から除外、土曜日のみ配置可能
            - スタッフ条件['日曜出勤']FALSEのスタッフは日曜祝日配置から除外する
            - 出勤希望があれば日曜祝日配置可能とする
            """
            available_dispensing_vars= section_configs['調剤室']['available_list']
            n_avail_dispensing = sum(available_dispensing_vars)# CP-SAT式: 実際に配置可能な人数
            if (is_monday or is_tuesday or is_wednesday or is_thursday)and not is_holiday:
                #- 化学療法室&課長&主任以上のスタッフは平日調剤室配置から除外
                section_configs['調剤室']['available_list'] = [
                    var for var, staff in zip(section_configs['調剤室']['available_list'], self.staff.index)
                    if not ((floor_chemo_secion_id in self.eligible_sections[staff]) and (self.staff.loc[staff, 'Floor2'] in ['課長']) and (self.staff.loc[staff, 'Floor'] in ['主任以上']))
                ]  
                section_configs['調剤室']['available_list'] = [
                                    var for var, staff in zip(section_configs['調剤室']['available_list'], self.staff.index)
                                    if not ((floor_chemo_secion_id in self.eligible_sections[staff]) and (self.staff.loc[staff, 'Floor2'] in ['課長']) and (self.staff.loc[staff, 'Floor2'] in ['主任以上']))
                                ]
                section_configs['調剤室']['available_list'] = [
                                    var for var, staff in zip(section_configs['調剤室']['available_list'], self.staff.index)
                                    if not ((floor_chemo_secion_id in self.eligible_sections[staff]) and (self.staff.loc[staff, 'Floor2'] in ['課長']) and (self.staff.loc[staff, 'Floor3'] in ['主任以上']))
                                ]
                
                required_dispensing = 6
                if available_dispensing_vars:
                    effective_required = self.model.NewIntVar(0, required_dispensing, f'dispensing_effective_required_{day}')
                    self.model.AddMinEquality(effective_required, [n_avail_dispensing, required_dispensing])
                    self.model.Add(sum(assigned_staff_dispensing) >= effective_required)
                    print(f"day{day}: 調剤室の配置人数は{required_dispensing}人です（月～木のため）。(上限は{len(available_dispensing_vars)}人)")
            elif is_friday and not is_holiday:
                #- 化学療法室&課長&主任以上のスタッフは平日調剤室配置から除外
                section_configs['調剤室']['available_list'] = [
                    var for var, staff in zip(section_configs['調剤室']['available_list'], self.staff.index)
                    if not ((floor_chemo_secion_id in self.eligible_sections[staff]) and (self.staff.loc[staff, 'Floor2'] in ['課長']) and (self.staff.loc[staff, 'Floor'] in ['主任以上']))
                ]  
                section_configs['調剤室']['available_list'] = [
                                    var for var, staff in zip(section_configs['調剤室']['available_list'], self.staff.index)
                                    if not ((floor_chemo_secion_id in self.eligible_sections[staff]) and (self.staff.loc[staff, 'Floor2'] in ['課長']) and (self.staff.loc[staff, 'Floor2'] in ['主任以上']))
                                ]
                section_configs['調剤室']['available_list'] = [
                                    var for var, staff in zip(section_configs['調剤室']['available_list'], self.staff.index)
                                    if not ((floor_chemo_secion_id in self.eligible_sections[staff]) and (self.staff.loc[staff, 'Floor2'] in ['課長']) and (self.staff.loc[staff, 'Floor3'] in ['主任以上']))
                                ]
                
                
                if is_odd_week:#第1・3週の金曜日　奇数週
                    required_dispensing = 6
                    if available_dispensing_vars:
                        effective_required = self.model.NewIntVar(0, required_dispensing, f'dispensing_effective_required_{day}')
                        self.model.AddMinEquality(effective_required, [n_avail_dispensing, required_dispensing])
                        self.model.Add(sum(assigned_staff_dispensing) >= effective_required)
                        print(f"day{day}: 調剤室の配置人数は{required_dispensing}人です（第1・3週の金曜日のため）。(上限は{len(available_dispensing_vars)}人)")
                else:#第2・4週の金曜日 偶数週
                    required_dispensing = 5
                    if available_dispensing_vars:
                        effective_required = self.model.NewIntVar(0, required_dispensing, f'dispensing_effective_required_{day}')
                        self.model.AddMinEquality(effective_required, [n_avail_dispensing, required_dispensing])
                        self.model.Add(sum(assigned_staff_dispensing) >= effective_required)
                        print(f"day{day}: 調剤室の配置人数は{required_dispensing}人です（第2・4週の金曜日のため）。(上限は{len(available_dispensing_vars)}人)")
                    self.model.Add(sum(assigned_staff_dispensing)>=required_dispensing)
                
            elif is_saturday and not is_holiday:
                # 化学療法かつ調剤室の両方に対応可能なスタッフを抽出
                available_staff = [staff for staff in self.staff.index if (floor_chemo_secion_id in self.eligible_sections[staff]) and (floor_dispensing_section_id in self.eligible_sections[staff])]
                
                print(f"Day {day}: 調剤室と化学療法の両方に対応可能なスタッフ数は {len(available_staff)} 人です。")
                # 化療+調剤室兼務可能スタッフの調剤室配置変数を収集
                chemo_despending_shifts = []
                chemo_concurrent_shifts = []
                for staff in available_staff:
                    shift_var = self.shifts[(staff, day, floor_dispensing_section_id)]
                    chemo_despending_shifts.append(shift_var)
                    chemo_concurrent_shifts.append(self.concurrent_shifts[(staff, day, 11)])
                
                # 土曜は調剤室に配置した同じスタッフを兼務化療にも割り当てる
                if chemo_despending_shifts:
                    required_chemo_dispensing = min(2, len(chemo_despending_shifts))
                    self.model.Add(sum(chemo_despending_shifts) >= required_chemo_dispensing)
                    self.model.Add(sum(chemo_concurrent_shifts) == required_chemo_dispensing)
                    for dispensing_var, concurrent_var in zip(chemo_despending_shifts, chemo_concurrent_shifts):
                        self.model.Add(concurrent_var <= dispensing_var)
                    print(f"Day {day}: 化療+調剤室兼務可能スタッフから調剤室と兼務化療に最大 {required_chemo_dispensing} 名配置します。")
                
                # 調剤室全体の配置人数（化療兼務2名を含む合計)
                self.model.Add(sum(assigned_staff_dispensing) >= 5)
                
            #日曜 前日が祝日でない場合
            elif is_sunday and not prev_day_is_holiday:
                #　当日の出勤希望がない&日曜出勤FALSEのスタッフは日曜祝日配置から除外する
                print(f"day{day}当日の日曜希望{self.hope_list.loc[:,day]}")
                print(f"day{day}当日の日曜出勤{self.staff.loc[:, '日曜出勤']}")
                for staff in self.staff.index:
                    can_work_sunday = self.staff.loc[staff,'日曜出勤']==True
                    has_work_request = self._get_hope_value(staff, day,default=7) == 1
                    
                    if not can_work_sunday and not has_work_request:
                        self.model.Add(
                            self.shifts[(staff,day,floor_dispensing_section_id)] == 0
                        )
                required_dispensing = 4
                if available_dispensing_vars:
                    effective_required = self.model.NewIntVar(0, required_dispensing, f'dispensing_effective_required_{day}')
                    self.model.AddMinEquality(effective_required, [n_avail_dispensing, required_dispensing])
                    self.model.Add(sum(assigned_staff_dispensing) >= effective_required)
                    print(f"day{day}: 調剤室の配置人数は{required_dispensing}人です（日曜日で前日が祝日でないため）。(上限は{len(available_dispensing_vars)}人)")
            #日曜　前日が祝日の場合
            elif is_sunday and prev_day_is_holiday:
                required_dispensing = 7
                if available_dispensing_vars:
                    effective_required = self.model.NewIntVar(0, required_dispensing, f'dispensing_effective_required_{day}')
                    self.model.AddMinEquality(effective_required, [n_avail_dispensing, required_dispensing])
                    self.model.Add(sum(assigned_staff_dispensing) >= effective_required)
                    print(f"day{day}: 調剤室の配置人数は{required_dispensing}人です（日曜日で前日が祝日のため）。(上限は{len(available_dispensing_vars)}人)")
            #祝日　前日が祝日の場合
            elif is_holiday and prev_day_is_holiday:
                required_dispensing = 7
                if available_dispensing_vars:
                    effective_required = self.model.NewIntVar(0, required_dispensing, f'dispensing_effective_required_{day}')
                    self.model.AddMinEquality(effective_required, [n_avail_dispensing, required_dispensing])
                    self.model.Add(sum(assigned_staff_dispensing) >= effective_required)
                    print(f"day{day}: 調剤室の配置人数は{required_dispensing}人です（祝日で前日も祝日のため）。(上限は{len(available_dispensing_vars)}人)")
            #祝日　前日が祝日でない場合
            elif is_holiday and not prev_day_is_holiday:
                required_dispensing = 4
                if available_dispensing_vars:
                    effective_required = self.model.NewIntVar(0, required_dispensing, f'dispensing_effective_required_{day}')
                    self.model.AddMinEquality(effective_required, [n_avail_dispensing, required_dispensing])
                    self.model.Add(sum(assigned_staff_dispensing) >= effective_required)
                    print(f"day{day}: 調剤室の配置人数は{required_dispensing}人です（祝日で前日が祝日でないため）。(上限は{len(available_dispensing_vars)}人)")

            """
            入退院センター 
            - 月〜土は1名
            - 休み希望の日は配置しない、上で定義済み
            - 配置可能なスタッフがいない場合は0人でも許容
            """
            available_nyutain_vars = section_configs['入退院センター']['available_list']
            n_avail_nyutain = sum(available_nyutain_vars)  # CP-SAT式: 実際に配置可能な人数
            if not is_sunday and not is_holiday:
                required_nyutain = 1
                if available_nyutain_vars:
                    effective_required = self.model.NewIntVar(0, required_nyutain, f'nyutain_effective_required_{day}')
                    self.model.AddMinEquality(effective_required, [n_avail_nyutain, required_nyutain])
                    self.model.Add(sum(assigned_staff_nyutain) >= effective_required)
                    print(f"day{day}: 入退院センターの配置人数は{required_nyutain}人です（平日のため）。(上限は{len(available_nyutain_vars)}人)")
            
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
            if not is_sunday and not is_holiday:
                available_list_infection = section_configs['感染管理']['available_list']
                print(f"医療安全・感染管理の配置可能スタッフ数の上限は {len(available_list_infection)} 人です。")
                if available_list_infection:
                    # is_available_var の少なくとも1つが1かをモデル内で判定（当直明け・休み希望を反映）
                    any_available_infection = self.model.NewBoolVar(f'any_available_infection_{day}')
                    self.model.AddMaxEquality(any_available_infection, available_list_infection)
                    self.model.Add(sum(assigned_staff_infection) >= 1).OnlyEnforceIf(any_available_infection)
                    # 配置可能者が0人の場合は0人配置を許容（ハード制約なし）
                else:
                    print(f"警告: Day {day}の感染管理に対応可能なスタッフが登録されていません。")
            
            
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
            
        #月内でポリファ開催を最低1回を行う
        if hold_porifa_tuesday_vars:
            any_schedulable_tuesday_porifa = self.model.NewBoolVar('any_schedulable_tuesday_porifa')#火曜のポリファ開催候補が1日でもあるかを判定する変数
            if porifa_tuesday_schedulable_vars:#候補が1日もなければスキップする
                self.model.AddMaxEquality(any_schedulable_tuesday_porifa, porifa_tuesday_schedulable_vars)
                self.model.Add(sum(hold_porifa_tuesday_vars)>=1).OnlyEnforceIf(any_schedulable_tuesday_porifa)
            else:
                self.model.Add(sum(hold_porifa_tuesday_vars)==0)
        else:
            print("火曜ポリファ開催候補がないため、月内必須制約をスキップします。")
    
        #return porifa_tuesday_penalties
            
    def add_consecutive_work_constraints(self):
        """
        連続出勤の制限
        - 当直明けを含めると6日まで
        - 各個人で配置可能なセクションについて検証する
        - 休み0以外のprimary_sectionが7日以上連続しないようにする
        """
        penalties = []

        for staff in self.staff.index:
            check_sections = sorted(set(self.eligible_sections.get(staff, [])))
            if 0 in check_sections:
                check_sections.remove(0)
            if 17 not in check_sections:
                check_sections.append(17)

            print(f"スタッフ{staff}の勤務可能なセクションは{check_sections}です")

            for start_day in range(1, self.days - 6 + 1):
                work_days_in_window = self.model.NewIntVar(
                    0,
                    7,
                    f'work_days_in_window_{staff}_{start_day}'
                )
                self.model.Add(
                    work_days_in_window == sum(
                        self.shifts[(staff, start_day + offset_day, section)]
                        for offset_day in range(7)
                        for section in check_sections
                    )
                )

                excess_var = self.model.NewIntVar(
                    0,
                    7,
                    f'consecutive_work_excess_{staff}_{start_day}'
                )
                self.model.Add(excess_var >= work_days_in_window - 6)
                self.model.Add(excess_var >= 0)
                penalties.append(excess_var)

        return penalties
                
    def add_sunday_holiday_work_constraints(self):
        """日曜祝日の出勤は可能な限り月1回までとする（ソフト制約）"""
        print("日曜祝日の出勤は可能な限り月1回までとする制約を適用します（ソフト制約）。")
        penalties = []
        for staff in self.staff.index:
            #日曜祝日勤務をカウントする変数を作成
            sunday_holiday_work_count = self.model.NewIntVar(0, self.days, f'sunday_holiday_work_count_{staff}')
            target_sections = {1,3,4,5,6,7,8,9,10,11,12,13,14,15,16,18,19,20,21,22}
            staff_work_sections = target_sections & set(self.eligible_sections.get(staff, []))
            self.model.Add(
                sunday_holiday_work_count == sum(
                    self.shifts[(staff, day, section)]
                    for day in range(1, self.days + 1)
                    for section in staff_work_sections
                    if (self._get_weekday(day) == 6 or self._is_holiday(day))
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
        """専属業務ごとの担当回数の偏り（max-min）をソフト制約で抑制する。"""
        penalties = []
        fairness_sections = [section for section in self.primary_sections if section != 17]#専属業務のうち、当直明けは公平性の対象外とする、休み０も公平性に含めてみる
        print(f"専属業務の公平性ペナルティを計算する対象セクション: {fairness_sections})")
        for section in fairness_sections:#各専属業務ごとに担当回数の偏りを計算する
            eligible_staff = [
                staff for staff in self.staff.index
                if section in self.eligible_sections.get(staff, [])
            ]

            if len(eligible_staff) <= 1:
                continue

            section_counts = []
            for staff in eligible_staff:
                count_var = self.model.NewIntVar(
                    0,
                    self.days,
                    f'primary_section_count_{section}_{staff}'
                )
                self.model.Add(
                    count_var == sum(
                        self.shifts[(staff, day, section)]
                        for day in range(1, self.days + 1)
                    )
                )
                section_counts.append(count_var)

            max_count = self.model.NewIntVar(0, self.days, f'primary_section_max_{section}')
            min_count = self.model.NewIntVar(0, self.days, f'primary_section_min_{section}')
            spread = self.model.NewIntVar(0, self.days, f'primary_section_spread_{section}')

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
        """同一セクション担当可能者間の連勤・連休偏りを抑える。"""
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
        #TODO:連続勤務の制限ペナルティを追加
        
        #役職者会議のペナルティを追加
        fixed_manager_meeting_penalties = self.meeting_constraints.fixed_manager_meeting()
        fixed_manager_meeting = WEIGHT_FIXED_MANAGER_MEETING * sum(fixed_manager_meeting_penalties) if fixed_manager_meeting_penalties else 0
        
        #薬剤部連絡会(役職者)のペナルティを追加
        fixed_general_meeting_penalties = self.meeting_constraints.general_meeting()
        fixed_general_meeting = WEIGHT_FIXED_GENERAL_MEETING * sum(fixed_general_meeting_penalties) if fixed_general_meeting_penalties else 0
        
        #薬審のペナルティを追加
        fixed_yakushin_meeting_penalties = self.meeting_constraints.yakushin()
        fixed_yakushin_meeting = WEIGHT_FIXED_YAKUSHIN_MEETING * sum(fixed_yakushin_meeting_penalties) if fixed_yakushin_meeting_penalties else 0
        
        #ポリファ（金曜日）の日はなるべく出勤とするペナルティを追加
        porifa_friday_penaltiles = self.concurrent_constraints.add_concurrent_porifa()
        porifa_friday_penalty_term = WEIGHT_PORIFA_FRIDAY * sum(porifa_friday_penaltiles) if porifa_friday_penaltiles else 0
        
        
        #化学療法の土曜日配置のペナルティを追加 work_constraintsで定義のため、必要なし
        #chemo_saturday_penalties = self.concurrent_constraints.add_concurrent_chemo()
        #chemo_saturday_penalty_term = WEIGHT_CHEMO_SATURDAY * sum(chemo_saturday_penalties) if chemo_saturday_penalties else 0

        #
        primary_fairness_penalties = self.add_primary_section_fairness_penalties()
        primary_fairness_penalty_term = WEIGHT_PRIMARY_FAIRNESS * sum(primary_fairness_penalties) if primary_fairness_penalties else 0
        
        #第二金曜日、病棟担当者カンファレンス参加のペナルティを追加
        second_friday_conference_penalties = self.meeting_constraints.second_friday_conference()
        second_friday_conference_penalty_term = WEIGHT_SECOND_FRIDAY_CONFERENCE * sum(second_friday_conference_penalties) if second_friday_conference_penalties else 0

        #
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
        
        total_penalty = (
            WEIGHT_ONCALL_NEXTDAY * sum(oncall_nextday_penalties)
            + sunday_penalty_term
            + consecutive_work_penalty_term
            + fixed_manager_meeting
            + fixed_general_meeting
            + fixed_yakushin_meeting
            + porifa_friday_penalty_term
            #+ chemo_saturday_penalty_term
            + primary_fairness_penalty_term
            + streak_work_fairness_term
            + streak_off_fairness_term
            + second_friday_conference_penalty_term
            + manager_penalty_term
        )

        self.optimizer.register_objective_term("work_constraints", total_penalty)