from optimizer.base_constraint import BaseConstraint
from datetime import datetime
from optimizer.concurrent_shift import MeetingConstraints
from config.objective_weights import WEIGHT_AUDIT_FAIRNESS, WEIGHT_HEART_TEAM_FAIRNESS
import pandas as pd
class ConcurrentConstraints(BaseConstraint):
    def __init__(self, model, optimizer):
        super().__init__(model, optimizer)
        self.meeting_constraints = MeetingConstraints(model, optimizer)

    def apply(self):
        """
        兼務業務の制約を適用する関数
        - 兼務業務は専属業務をもつスタッフ飲みに割り当てる
        - スタッフの業務可能な条件.xlsxの条件に基づいて割り当てる
        - 各兼務業務の必要人数を確保する
        """
        self.eligible_sections = self.get_eligible_sections#割り当て可能な業務名の制約を取得
        # add_concurrent_porifa は WorkConstraints 側の目的関数設定で1回だけ呼び出す
        # （ここで再度呼ぶと同名制約・変数が重複してモデルが不安定になる）
        self.add_concurrent_ri()
        # 医薬品安全使用WGの制約を追加し、ペナルティを集約
        safety_wg_penalties = self.add_safety_wg()
        dem_round_penalties = self.add_dem_round()
        heart_team_penalties = self.add_heart_team()
        if safety_wg_penalties:
            WEIGHT_SAFETY_WG = 10  # 他の制約と同等の優先度
            safety_wg_penalty_term = WEIGHT_SAFETY_WG * sum(safety_wg_penalties) if safety_wg_penalties else 0
            self.optimizer.register_objective_term("safety_wg", safety_wg_penalty_term)
        if dem_round_penalties:
            WEIGHT_DEM_ROUND = 4
            dem_round_penalty_term = WEIGHT_DEM_ROUND * sum(dem_round_penalties) if dem_round_penalties else 0
            self.optimizer.register_objective_term("dem_round", dem_round_penalty_term)
        if heart_team_penalties:
            WEIGHT_HEART_TEAM = 4
            heart_team_penalty_term = WEIGHT_HEART_TEAM * sum(heart_team_penalties) if heart_team_penalties else 0
            self.optimizer.register_objective_term("heart_team", heart_team_penalty_term)
        self.add_audit_staff()
        
        audit_fairness_penalties = self.add_audit_fairness_penalties()
        if audit_fairness_penalties:
            self.optimizer.register_objective_term("audit_fairness",
                                                WEIGHT_AUDIT_FAIRNESS * sum(audit_fairness_penalties) if audit_fairness_penalties else 0)

        heart_team_fairness_penalties = self.add_heart_team_fairness_penalties()
        if heart_team_fairness_penalties:
            self.optimizer.register_objective_term("heart_team_fairness",
                                                WEIGHT_HEART_TEAM_FAIRNESS * sum(heart_team_fairness_penalties) if heart_team_fairness_penalties else 0)
            
    def add_concurrent_ri(self):
        """
        RI
        - 月〜土は1名
        - 日曜祝日は0名、上で定義済み
        - 休み希望の日は配置しない,上で定義済み
        - 配置可能なスタッフがいない場合は0人でも許容
        - 割り振りの優先度 name == > name == > name == > 条件シートの優先度 RI優先度1>2>3
        """
        for day in range(1,self.days +1):
            floor_ri_id = 22#ge_eligible_sectionsでRI対応可能に割り当てているセクションID,sections.py
            concurrent_ri_id = 4#兼務業務のセクションID,concurrent_sections.py
            assigned_staff_ri = []#RIに割り当てる候補者リスト
            assigned_ri_ids = []#perstaff制約用
            #セクション設定を定義
            section_configs = {
                'RI':{
                    'section_id': floor_ri_id,
                    'assigned_list': assigned_staff_ri,
                    'assigned_ids': assigned_ri_ids,
                    'available_list': [],
                    'check_day_off':True,
                    'check_oncall_next':True,
                }
            }
            self._build_section_availability(
                section_configs=section_configs,day = day,year=self.year,
                required_staff_12=None,
                required_staff_12_assigned=None,
                required_staff_12_available=None,
                di_eligible_staff_ids=None,
                porifa_staff_ids=None,
                ri_staff_ids=assigned_ri_ids,
            )
            #デバッグ　RI対応可能なスタッフをprintする
            #曜日、祝日、前日祝日を取得
            weekday = self._get_weekday(day)
            is_wekday = weekday <=4 #月〜金
            is_holiday = self._is_holiday(day)
            is_saturday = weekday == 5
            is_sunday = weekday == 6
            prev_day_is_holiday = day >1 and self._is_holiday(day-1)    
            
            if not is_sunday and not is_holiday:
                if assigned_staff_ri:
                    required = 1
                    available_ri_vars = section_configs['RI']['available_list']
                    if available_ri_vars:
                        any_ri_available = self.model.NewBoolVar(f'any_ri_available_{day}')
                        self.model.AddMaxEquality(any_ri_available, available_ri_vars)#配置可能なスタッフの中に1人でも配置可能なスタッフがいればany_ri_available=1

                        ri_assign_vars = []
                        priority_buckets = {}
                        for idx, ri_staff in enumerate(assigned_ri_ids):
                            assign_var = self.concurrent_shifts[(ri_staff,day,concurrent_ri_id)]#RIに割り当てる変数
                            available_var = available_ri_vars[idx]#RIに割り当てるスタッフが配置可能かを示す変数
                            self.model.Add(assign_var <= available_var)#配置する場合は配置可能でなければならない
                            ri_assign_vars.append(assign_var)

                            priority = self.get_ri_priority(ri_staff)#RIの優先度を取得する関数を定義して、優先度ごとにスタッフをバケット分けする
                            priority_buckets.setdefault(priority, []).append((assign_var, available_var))#優先度ごとにスタッフをバケット分けする辞書　例: {1: [(assign_var1, available_var1), (assign_var2, available_var2)], 2: [(assign_var3, available_var3)]} 優先度1のスタッフが複数いる場合も考慮

                        self.model.Add(sum(ri_assign_vars) == required).OnlyEnforceIf(any_ri_available)#配置可能なスタッフがいれば1人を配置する制約を追加
                        self.model.Add(sum(ri_assign_vars) == 0).OnlyEnforceIf(any_ri_available.Not())#配置可能なスタッフがいなければ0人を配置する制約を追加

                        sorted_priorities = sorted(priority_buckets.keys())
                        for priority in sorted_priorities:
                            current_bucket = priority_buckets[priority]#現在の優先度のバケット　例: [(assign_var1, available_var1), (assign_var2, available_var2)]
                            current_available = [available_var for _, available_var in current_bucket]#現在の優先度のスタッフの配置可能変数のリスト　例: [available_var1, available_var2]
                            lower_assign_vars = [
                                assign_var
                                for lower_priority in sorted_priorities
                                if lower_priority > priority#現在の優先度より低い優先度のバケットのスタッフの割り当て変数のリスト　例: [assign_var3] 優先度2のスタッフがいる場合
                                for assign_var, _ in priority_buckets[lower_priority]#現在の優先度より低い優先度のバケットのスタッフの割り当て変数のリスト　例: [assign_var3] 優先度2のスタッフがいる場合
                            ]

                            higher_available = self.model.NewBoolVar(f'ri_priority_{priority}_available_{day}')#現在の優先度のスタッフの中に1人でも配置可能なスタッフがいればhigher_available=1
                            self.model.AddMaxEquality(higher_available, current_available)#現在の優先度のスタッフの中に1人でも配置可能なスタッフがいればhigher_available=1
                            if lower_assign_vars:
                                self.model.Add(sum(lower_assign_vars) == 0).OnlyEnforceIf(higher_available)#現在の優先度のスタッフの中に配置可能なスタッフがいれば、より低い優先度のスタッフは配置しない制約を追加

                        print(f"Day{day}: RI は優先度が高いスタッフから1人を配置")
                else:
                    print(f"⚠️ [RI] Day {day}: RIに対応可能なスタッフが登録されていません。配置可能なスタッフがいない場合は0人でも許容します。")
                    # 配置可能なスタッフがいない場合は0人でも許容するため、特に制約は追加しない
            else:
                pass#日曜祝日のRI対応は0人の制約を追加する必要がないためここでは制約を追加しない
        
    def add_concurrent_porifa(self):
        """
        金曜午後のポリファーマシーの配置
        - メンバー全員が出勤可能な金曜日に配置する（CP-SAT変数で最適週を決定）
        - 1人でも参加不可（休み希望または当直明け）のスタッフがいればその日は開催しない
        - 原則として月1回開催
        - 開催時は専属業務をなるべく出勤とする
        """
        penalties = []
        hold_porifa_friday_vars = []
        porifa_friday_schedulable_vars = []
        concurrent_porifa_id = 10  # 兼務業務のセクションID
        floor_porifa_id = 11  # 専属業務のセクションID
        
        for day in range(1, self.days + 1):            
            assigned_staff_porifa = []
            assigned_porifa_ids = []  # perstaff制約用
            required_porifa_staff = []
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
            
            weekday = self._get_weekday(day)
            is_friday = (weekday == 4)
            is_holiday = self._is_holiday(day)

            if is_friday and not is_holiday:
                hold_porifa_friday = self.optimizer.porifa_friday_vars.get(
                    day, self.model.NewBoolVar(f'hold_porifa_friday_{day}')
                )
                self.optimizer.porifa_friday_vars[day] = hold_porifa_friday
                hold_porifa_friday_vars.append(hold_porifa_friday)

                porifa_friday_schedulable = self.model.NewBoolVar(f'porifa_friday_schedulable_{day}')
                porifa_friday_schedulable_vars.append(porifa_friday_schedulable)

                if assigned_porifa_ids:
                    # 明けシフト(shift_id=17)を持つスタッフの確認
                    porifa_ake_vars = [self.shifts[(porifa_staff, day, 17)] for porifa_staff in assigned_porifa_ids]
                    any_porifa_ake = self.model.NewBoolVar(f'any_porifa_ake_friday_{day}')
                    if porifa_ake_vars:
                        self.model.AddMaxEquality(any_porifa_ake, porifa_ake_vars)
                    else:
                        self.model.Add(any_porifa_ake == 0)

                    available_porifa = section_configs['ポリファーマシー']['available_list']
                    if available_porifa:
                        all_porifa_available = self.model.NewBoolVar(f'all_porifa_available_{day}')
                        self.model.AddMinEquality(all_porifa_available, available_porifa)

                        # 全員可用 かつ 当直明けなし のときのみ開催可能
                        self.model.AddMinEquality(porifa_friday_schedulable, [all_porifa_available, any_porifa_ake.Not()])
                        self.model.Add(hold_porifa_friday <= porifa_friday_schedulable)

                        for porifa_staff in assigned_porifa_ids:
                            # 開催時: 兼務業務にポリファ(10)を割り当て、明けはなし
                            self.model.Add(self.shifts[(porifa_staff, day, 17)] == 0).OnlyEnforceIf(hold_porifa_friday)
                            self.model.Add(self.concurrent_shifts[(porifa_staff, day, concurrent_porifa_id)] == 1).OnlyEnforceIf(hold_porifa_friday)
                            # 非開催時: 兼務業務(10)は0
                            self.model.Add(self.concurrent_shifts[(porifa_staff, day, concurrent_porifa_id)] == 0).OnlyEnforceIf(hold_porifa_friday.Not())

                            # 開催日はなるべく専属業務を休み(0)にしないソフト制約
                            penalty_var = self.model.NewBoolVar(f'penalty_friday_porifa_{porifa_staff}_{day}')
                            self.model.Add(self.shifts[(porifa_staff, day, 0)] == 0).OnlyEnforceIf([hold_porifa_friday, penalty_var.Not()])
                            penalties.append(penalty_var)
                    else:
                        self.model.Add(hold_porifa_friday == 0)
                        self.model.Add(porifa_friday_schedulable == 0)
                        for porifa_staff in assigned_porifa_ids:
                            self.model.Add(self.concurrent_shifts[(porifa_staff, day, concurrent_porifa_id)] == 0)
                else:
                    self.model.Add(hold_porifa_friday == 0)
                    self.model.Add(porifa_friday_schedulable == 0)
            else:
                # 金曜（非祝日）以外はポリファ兼務(10)は配置しない
                for porifa_staff in assigned_porifa_ids:
                    self.model.Add(self.concurrent_shifts[(porifa_staff, day, concurrent_porifa_id)] == 0)

        # 月内で金曜ポリファ開催を原則1回行う
        if hold_porifa_friday_vars:
            any_schedulable_friday_porifa = self.model.NewBoolVar('any_schedulable_friday_porifa')
            if porifa_friday_schedulable_vars:
                self.model.AddMaxEquality(any_schedulable_friday_porifa, porifa_friday_schedulable_vars)
                self.model.Add(sum(hold_porifa_friday_vars) == 1).OnlyEnforceIf(any_schedulable_friday_porifa)
                self.model.Add(sum(hold_porifa_friday_vars) == 0).OnlyEnforceIf(any_schedulable_friday_porifa.Not())
            else:
                self.model.Add(sum(hold_porifa_friday_vars) == 0)
        else:
            print("金曜ポリファ開催候補がないため、月内制約をスキップします。")

        return penalties

    #土曜日のケモ
    def add_concurrent_chemo(self):
        """
        土は2名を調剤室へ配置、専属業務としてのケモは0名→work_constraintsへ
        兼務業務にケモを配置する制約
        配置可能なメンバーから最大2名を配置する
        - 調剤室へ配置した最大2名が対象になる
        - 明けの次の日の休みになるべく配置しない
        Returns:
            list: 土曜ケモ不足人数（2人に満たない分）のペナルティ
        """
        penalties = []
        for day in range(1,self.days +1):
            floor_chemo_id = 9#専属業務のセクションID
            concurrent_chemo_id = 11#兼務業務のセクションID
            #配置可能なスタッフリスト
            assigned_staff_chemo = []
            assigned_chemo_ids = []#perstaff制約用
            #セクション設定を定義
            section_configs = {
                '化療':{
                    'section_id':floor_chemo_id,
                    'assigned_list':assigned_staff_chemo,
                    'assigned_ids':assigned_chemo_ids,
                    'available_list': [],
                    'check_day_off':True,
                    'check_oncall_next':True,
                }
            }
            self._build_section_availability(
                section_configs=section_configs,day = day,
                required_staff_12=None,
                required_staff_12_assigned=None,
                required_staff_12_available=None,
                di_eligible_staff_ids=None,
                porifa_staff_ids=None,
                chemo_staff_ids=assigned_chemo_ids,
            )
            #デバッグ　化療対応可能なスタッフをprintする
            print(f"Day{day}化療に対応可能なスタッフ{assigned_chemo_ids}です")
            #曜日、祝日、前日祝日を取得
            weekday = self._get_weekday(day)
            is_wekday = weekday <=4 #月〜金
            is_holiday = self._is_holiday(day)
            is_saturday = weekday == 5
            prev_day_is_holiday = day >1 and self._is_holiday(day-1)
            
            available_chemo_vars = section_configs['化療']['available_list']
            n_available_chemo = sum(available_chemo_vars)
            
            if is_saturday and not is_holiday:
                print(f"Day{day}: 化療に対応可能なスタッフ{assigned_chemo_ids}です")
                if assigned_staff_chemo:
                    required = 2
                    if available_chemo_vars:
                        # 配置人数は「2名固定」ではなく可用人数連動にする。
                        # これにより当直明け/休み希望で可用人数が1名以下の日もINFEASIBLEを回避できる。
                        effective_required = self.model.NewIntVar(0, required, f'concurrent_chemo_effective_required_{day}')
                        self.model.AddMinEquality(effective_required, [n_available_chemo, required])

                        chemo_assign_vars = []
                        for idx, chemo_staff in enumerate(assigned_chemo_ids):
                            assign_var = self.concurrent_shifts[(chemo_staff, day, concurrent_chemo_id)]
                            available_var = available_chemo_vars[idx]
                            # 配置できるのは当日可用なスタッフのみ
                            self.model.Add(assign_var <= available_var)
                            chemo_assign_vars.append(assign_var)

                        self.model.Add(sum(chemo_assign_vars) == effective_required)

                        # 2名に満たない不足分はソフト化して目的関数で最小化
                        shortage = self.model.NewIntVar(0, required, f'concurrent_chemo_shortage_{day}')
                        self.model.Add(shortage == required - sum(chemo_assign_vars))
                        penalties.append(shortage)

                        print(f"Day{day}: 化療 兼務業務は可用人数連動で最大{required}名を配置（不足はペナルティ化）")
            else:
                pass#土曜日以外の化療対応は専属業務で配置するためここでは制約を追加しない
        return penalties
    
    #認知症せん妄ラウンド
    def add_dem_round(self):
        """
        認知症せん妄ラウンド
        - 火曜、金曜
        - 条件.xlsx['認知症せん妄ラウンド']==TRUEのスタッフが対象
        - 対象日以外には配置しない
        - 兼務業務に配置
        - 最低1名以上配置する
        - 当直制約へ明けが配置対象日にならないように設定
        """
        penalties = []
        for day in range(1,self.days +1):
            floor_dem_round_id = 12#専属業務のセクションID
            concurrent_dem_round_id = 12#兼務業務のセクションID
            
            #配置可能なスタッフリスト
            assigned_staff_dem_round = []
            assigned_dem_round_ids = []#perstaff制約用
            
            #セクション設定を定義
            section_configs = {
                '認知症せん妄ラウンド':{
                    'section_id':floor_dem_round_id,
                    'assigned_list':assigned_staff_dem_round,
                    'assigned_ids':assigned_dem_round_ids,
                    'available_list': [],
                    'check_day_off':True,
                    'check_oncall_next':True,
                }
            }
            self._build_section_availability(
                section_configs=section_configs,day = day,year=self.year,
                required_staff_12=None,
                required_staff_12_assigned=None,
                required_staff_12_available=None,
                di_eligible_staff_ids=None,
                porifa_staff_ids=None,
                safety_wg_staff_ids=None,
                dem_round_staff_ids=assigned_dem_round_ids,
            )
            #曜日、祝日、前日祝日を取得
            weekday = self._get_weekday(day)
            is_wekday = weekday <=4 #月〜金
            is_holiday = self._is_holiday(day)
            is_tuesday = weekday == 1
            is_friday = weekday == 4
            prev_day_is_holiday = day >1 and self._is_holiday(day-1)
            if (is_tuesday or is_friday) and not is_holiday:
                print(f"day{day}認知症せん妄ラウンドの配置対象日です")
                print(f"day{day}認知症せん妄ラウンドに対応可能なスタッフ{assigned_dem_round_ids}です")
                if assigned_staff_dem_round:#対応可能なスタッフがいる場合のみ制約を追加
                    available_dem_round = section_configs['認知症せん妄ラウンド']['available_list']
                    dem_round_assign_vars = []
                    for idx, dem_round_staff in enumerate(assigned_dem_round_ids):
                        # 対応可能なスタッフから、現在のインデックスの利用可能性フラグを取得
                        available_var = available_dem_round[idx]
                        # このスタッフの当該日のWG兼務割り当て決定変数を取得
                        assign_var = self.concurrent_shifts[(dem_round_staff,day,concurrent_dem_round_id)]
                        # 休み希望・当直明けのスタッフはWG兼務に配置しない
                        self.model.Add(assign_var <= available_var)
                        dem_round_assign_vars.append(assign_var)
                    #当日配置可能かを確認
                    any_available_dem_round = self.model.NewBoolVar(f'any_available_dem_round_{day}')
                    self.model.AddMaxEquality(any_available_dem_round, available_dem_round)
                    #配置可能であれば1人以上配置する
                    self.model.Add(sum(dem_round_assign_vars) >= 1).OnlyEnforceIf(any_available_dem_round)

                    if available_dem_round:
                        # ペナルティ計算: 対応可能スタッフ数 - 配置スタッフ数
                        unallocated_penalty = self.model.NewIntVar(0, len(available_dem_round), f'unallocated_penalty_dem_round_{day}')
                        self.model.Add(unallocated_penalty == len(available_dem_round) - sum(dem_round_assign_vars))
                        penalties.append(unallocated_penalty)
                        
                        allocated_count = sum(dem_round_assign_vars)
                        available_count = len(available_dem_round)
                        print(f"Day{day}: 認知症せん妄ラウンド 可用なスタッフ数={available_count}, 配置目標スタッフ数={available_count}")
                    else:
                        print(f"Day{day}: 認知症せん妄ラウンド 対応可能なスタッフがいません")
                else:
                    print(f"⚠️ [認知症せん妄ラウンド] Day {day}: 認知症せん妄ラウンドに対応可能なスタッフが登録されていません")
            else:
                #対象日以外には配置しない
                for dem_round_staff in assigned_dem_round_ids:
                    self.model.Add(self.concurrent_shifts[(dem_round_staff,day,concurrent_dem_round_id)]==0)
        return penalties
    
    def add_safety_wg(self):
        """
        医薬品安全使用WG（ソフト制約版）
        - 休み希望があれば優先,build_section_availabilityのcheck_day_offで対応
        - 第4金曜日に開催
        - 条件.xlsx[,"医薬品安全使用WG"]==TRUEのスタッフが対象
        - 対象日以外には配置しない
        - 兼務業務に配置
        - メンバーはなるべく全員配置（ソフト制約）
        - 未配置スタッフ数をペナルティとして目的関数に追加
        - TODO：当直制約へ明けが配置対象日にならないように設定
        - TODO:対象者はwork_requestsにてなるべく休みにならないようにペナルティを加算,fxed_manager_meetingを参考に
        Returns:
            list: ペナルティ項のリスト（目的関数に追加される）
        """
        penalties = []
        for day in range(1,self.days +1):
            floor_safety_wg_id = 24#専属業務のセクションID
            concurrent_safety_wg_id = 8#兼務業務のセクションID
            
            #配置可能なスタッフリスト
            assigned_staff_safety_wg = []
            assigned_safety_wg_ids = []#perstaff制約用
            #セクション設定を定義
            section_configs = {
                '医薬品安全使用WG':{
                    'section_id':floor_safety_wg_id,
                    'assigned_list':assigned_staff_safety_wg,
                    'assigned_ids':assigned_safety_wg_ids,
                    'available_list': [],
                    'check_day_off':True,
                    'check_oncall_next':True,
                }
            }
            self._build_section_availability(
                section_configs=section_configs,day = day,year=self.year,
                required_staff_12=None,
                required_staff_12_assigned=None,
                required_staff_12_available=None,
                di_eligible_staff_ids=None,
                porifa_staff_ids=None,
                safety_wg_staff_ids=assigned_safety_wg_ids,
            )
            #曜日、祝日、前日祝日を取得
            weekday = self._get_weekday(day)
            is_wekday = weekday <=4 #月〜金
            is_holiday = self._is_holiday(day)
            is_friday = weekday == 4
            prev_day_is_holiday = day >1 and self._is_holiday(day-1)
            if is_friday and not is_holiday and (day-1)//7 +1 == 4:#第４金曜日
                print(f"day{day}医薬品安全使用WGの配置対象日です")
                print(f"day{day}医薬品安全使用WGに対応可能なスタッフ{assigned_safety_wg_ids}です")
                if assigned_staff_safety_wg:
                    available_safety_wg = section_configs['医薬品安全使用WG']['available_list']
                    wg_assign_vars = []
                    for idx, safety_wg_staff in enumerate(assigned_safety_wg_ids):
                        # 対応可能なスタッフから、現在のインデックスの利用可能性フラグを取得
                        available_var = available_safety_wg[idx]
                        # このスタッフの当該日のWG兼務割り当て決定変数を取得
                        assign_var = self.concurrent_shifts[(safety_wg_staff,day,concurrent_safety_wg_id)]
                        # 休み希望・当直明けのスタッフはWG兼務に配置しない
                        self.model.Add(assign_var <= available_var)
                        wg_assign_vars.append(assign_var)

                    if available_safety_wg:
                        # ペナルティ計算: 対応可能スタッフ数 - 配置スタッフ数
                        # sum(wg_assign_vars) = 配置スタッフ数
                        # len(available_safety_wg) = 対応可能スタッフ数
                        unallocated_penalty = len(available_safety_wg) - sum(wg_assign_vars)
                        penalties.append(unallocated_penalty)
                        
                        allocated_count = sum(wg_assign_vars)
                        available_count = len(available_safety_wg)
                        print(f"Day{day}: 医薬品安全使用WG 可用なスタッフ数={available_count}, 配置目標スタッフ数={available_count}")
                    else:
                        print(f"Day{day}: 医薬品安全使用WG 対応可能なスタッフがいません")
                else:
                    print(f"⚠️ [医薬品安全使用WG] Day {day}: 医薬品安全使用WGに対応可能なスタッフが登録されていません")
            else:
                #対象日以外には配置しない
                for safety_wg_staff in assigned_safety_wg_ids:
                    self.model.Add(self.concurrent_shifts[(safety_wg_staff,day,concurrent_safety_wg_id)]==0)
        
        return penalties
    
    def add_heart_team(self):
        """
        心不全回診
        - 火曜午後
        - 条件.xlsx[,"心不全回診"]==TRUEのスタッフが対象
        - 対象日以外には配置しない
        - 兼務業務に配置
        - 最低1名いれば良い
        - 配置可能スタッフがなるべく均等に配置される
        """
        penalties = []
        for day in range(1,self.days +1):
            if (weekday := self._get_weekday(day)) != 1:  # 火曜午後以外はスキップ
                continue
            floor_heart_team_id = 18 #専属業務のセクションID
            concurrent_heart_team_id = 1 #兼務業務のセクションID
            
            #配置可能なスタッフリスト
            assigned_staff_heart_team = []
            assigned_heart_team_ids = []#perstaff制約用
            
            #セクション設定を定義
            section_configs = {
                '心不全回診':{
                    'section_id':floor_heart_team_id,
                    'assigned_list':assigned_staff_heart_team,
                    'assigned_ids':assigned_heart_team_ids,
                    'available_list': [],
                    'check_day_off':True,
                    'check_oncall_next':True,
                }
            }
            self._build_section_availability(
                section_configs=section_configs,day = day,year=self.year,
                required_staff_12=None,
                required_staff_12_assigned=None,
                required_staff_12_available=None,
                di_eligible_staff_ids=None,
                porifa_staff_ids=None,
                heart_team_staff_ids=assigned_heart_team_ids,
            )
            
            if assigned_staff_heart_team:
                available_heart_team = section_configs['心不全回診']['available_list']
                heart_team_assign_vars = []
                for idx,heart_team_staff in enumerate(assigned_heart_team_ids):
                    available_var = available_heart_team[idx]
                    assign_var = self.concurrent_shifts[(heart_team_staff,day,concurrent_heart_team_id)]
                    self.model.Add(assign_var <= available_var)
                    heart_team_assign_vars.append(assign_var)
                if available_heart_team:
                    self.model.Add(sum(heart_team_assign_vars) <= 1)  # 火曜午後は最大1名まで配置
                    unallocated_penalty = len(available_heart_team) - sum(heart_team_assign_vars)
                    penalties.append(unallocated_penalty)
                else:
                    print(f"Day{day}: 心不全回診 対応可能なスタッフがいません")
            else:
                print(f"⚠️ [心不全回診] Day {day}: 心不全回診に対応可能なスタッフが登録されていません")
        return penalties

    def add_heart_team_fairness_penalties(self):
        """心不全回診の公平性ペナルティ"""
        heart_team_id = 18  # 心不全回診の専属業務のセクションID
        concurrent_heart_team_id = 1  # 心不全回診の兼務業務のセクションID
        
        eligible_staff = [
            staff for staff in self.staff.index
            if heart_team_id in self.eligible_sections.get(staff, [])
        ]
        if len(eligible_staff) < 2:
            print("⚠️ [心不全回診] 対応可能なスタッフが2名未満のため、公平性ペナルティは適用されません。")
            return []
        
        heart_team_counts = {staff: 0 for staff in eligible_staff}
        
        max_heart_team_count = self.model.NewIntVar(0, self.days, 'max_heart_team_count')
        min_heart_team_count = self.model.NewIntVar(0, self.days, 'min_heart_team_count')
        spread = self.model.NewIntVar(0, self.days, 'heart_team_spread')
        
        self.model.AddMaxEquality(max_heart_team_count, heart_team_counts.values())
        self.model.AddMinEquality(min_heart_team_count, heart_team_counts.values())
        self.model.Add(spread == max_heart_team_count - min_heart_team_count)   
        
        return [spread]  # 公平性のペナルティとして、最大割り当て数と最小割り当て数の差を返す
            
    def add_audit_staff(self):
        """
        監査スタッフの配置
        - 当日調剤室に配置されたスタッフの中から1日1人を選ぶ
        - 必ず1名選択される
        - 監査は兼務業務として AM/PM の変数に割り当てる
        - 1日に同じ人が AM と PM の両方に入ることはなく、合計で1名のみとする
        - TODO:当日RI担当の場合は監査PMに割り当てられないようにする
        - TODO:当日緩和ケア担当の場合には監査に割り当てられないようにする
        - 監査の公平性を考慮し、過去の割り当て回数に基づいてペナルティを追加する
        - 土曜午前の監査は、化療フロアが調剤室にいる場合には非化療フロアのスタッフは割り当てられないようにする
        - 土曜午後の監査は、化療フロアが調剤室にいる場合には化療フロアのスタッフは割り当てられないようにする
        - 7月前半までは0年目のスタッフが監査に割り当てられないようにする
        """
        concurrent_audit_id_AM = 13  # 監査AM兼務業務のセクションID
        concurrent_audit_id_PM = 14  # 監査PM兼務業務のセクションID
        dispensing_section_id = 1  # 調剤室専属業務のセクションID

        for day in range(1, self.days + 1):
            # 曜日、祝日、前日祝日を取得
            weekday = self._get_weekday(day)
            is_holiday = self._is_holiday(day)
            is_sunday = weekday == 6
            is_saturday = weekday == 5
            prev_day_is_holiday = day > 1 and self._is_holiday(day - 1)
            
            if is_sunday or is_holiday:
                # 日曜祝日は監査を配置しない
                for staff in self.staff.index:
                    self.model.Add(self.concurrent_shifts[(staff, day, concurrent_audit_id_AM)] == 0)
                    self.model.Add(self.concurrent_shifts[(staff, day, concurrent_audit_id_PM)] == 0)
                continue
            
            is_july_early = (self.month >= 4 and self.month <= 7 and day <= 15)  # 4-7月の前半までの期間を判定するフラグ
            
            candidate_staff_ids = []
            chemo_candidate_staff_ids = []
            non_chemo_candidate_staff_ids = []
            audit_vars_am = []
            audit_vars_pm = []
            chemo_dispensing_vars = []
            non_chemo_audit_vars_am = []
            chemo_audit_vars_pm = []
            dispensing_vars = []

            for staff in self.staff.index:
                is_chemo_floor = 9 in self.eligible_sections.get(staff, [])
                
                
                assign_var_AM = self.concurrent_shifts[(staff, day, concurrent_audit_id_AM)]
                assign_var_PM = self.concurrent_shifts[(staff, day, concurrent_audit_id_PM)]
                
                #4-7月前半
                if is_july_early :
                    sync_value = self.staff.loc[staff, '同期変数']
                    if pd.notna(sync_value) and sync_value == 0:
                        self.model.Add(assign_var_AM == 0)
                        self.model.Add(assign_var_PM == 0)
                        continue
                    
                if dispensing_section_id not in self.eligible_sections[staff]:
                    self.model.Add(assign_var_AM == 0)
                    self.model.Add(assign_var_PM == 0)
                    continue

                dispensing_var = self.shifts.get((staff, day, dispensing_section_id))
                if dispensing_var is None:
                    self.model.Add(assign_var_AM == 0)
                    self.model.Add(assign_var_PM == 0)
                    continue

                candidate_staff_ids.append(staff)
                dispensing_vars.append(dispensing_var)
                if is_chemo_floor:
                    chemo_candidate_staff_ids.append(staff)
                else:
                    non_chemo_candidate_staff_ids.append(staff)

                # 監査は調剤室担当者に限定し、同日 1 名を必須とする制約を追加
                self.model.Add(assign_var_AM <= dispensing_var)
                self.model.Add(assign_var_PM <= dispensing_var)
                
                if is_chemo_floor:
                    chemo_dispensing_vars.append(dispensing_var)
                    chemo_audit_vars_pm.append(assign_var_PM)
                else:
                    non_chemo_audit_vars_am.append(assign_var_AM)
                    
                
                #同一人物が両日のAMとPMの両方に割り当てられない制約を追加
                self.model.Add(assign_var_AM + assign_var_PM <= dispensing_var)
                
                audit_vars_am.append(assign_var_AM)
                audit_vars_pm.append(assign_var_PM)

            if candidate_staff_ids:
                print(
                    f"[DEBUG監査] Day{day}:"
                    f"候補総数={len(candidate_staff_ids)}"
                    f" chemo候補={chemo_candidate_staff_ids}"
                    f" non_chemo候補={non_chemo_candidate_staff_ids}"
                )
                if is_saturday and not is_holiday and chemo_dispensing_vars:
                    any_chemo_dispensing = self.model.NewBoolVar(f'any_chemo_dispensing_{day}')
                    self.model.AddMaxEquality(any_chemo_dispensing, chemo_dispensing_vars)
                    print(
                        f"[DEBUG監査] Day{day}: 土曜条件あり"
                        f" chemo_dispensing候補数={len(chemo_dispensing_vars)}"
                        f" non_chemo_AM候補数={len(non_chemo_audit_vars_am)}"
                        f" chemo_PM候補数={len(chemo_audit_vars_pm)}"
                    )
                    if not chemo_candidate_staff_ids:
                        print(
                            f"[DEBUG監査警告] Day{day}: 土曜に化療候補が0です。"
                            "化療スタッフが調剤室に入る前提が必要な場合はAM/PMのexact制約と競合する可能性があります。"
                        )
                    if not non_chemo_candidate_staff_ids:
                        print(
                            f"[DEBUG監査警告] Day{day}: 土曜に非化療候補が0です。"
                            "PM監査で非化療候補が必要な条件と競合する可能性があります。"
                        )
                    for assign_var_am in non_chemo_audit_vars_am:
                        self.model.Add(assign_var_am == 0).OnlyEnforceIf(any_chemo_dispensing)#午前の監査は、化療フロアが調剤室にいる場合には非化療フロアのスタッフは割り当てられないようにする
                    for assign_var_pm in chemo_audit_vars_pm:
                        self.model.Add(assign_var_pm == 0).OnlyEnforceIf(any_chemo_dispensing)#午後の監査は、化療フロアが調剤室にいる場合には化療フロアのスタッフは割り当てられないようにする

                any_audit_schedulable = self.model.NewBoolVar(
                    f'any_audit_schedulable_{day}'
                )
                self.model.AddMaxEquality(any_audit_schedulable, dispensing_vars)
                self.model.Add(sum(audit_vars_am) >= 1).OnlyEnforceIf(any_audit_schedulable)
                self.model.Add(sum(audit_vars_pm) >= 1).OnlyEnforceIf(any_audit_schedulable)
                self.model.Add(sum(audit_vars_am) == 0).OnlyEnforceIf(any_audit_schedulable.Not())
                self.model.Add(sum(audit_vars_pm) == 0).OnlyEnforceIf(any_audit_schedulable.Not())
                print(f"Day{day}: 監査候補={candidate_staff_ids} から 1 人を選択")
            else:
                print(f"Day{day}: 監査候補がいないため 0 人とする")
                for staff in self.staff.index:
                    self.model.Add(self.concurrent_shifts[(staff, day, concurrent_audit_id_AM)] == 0)
                    self.model.Add(self.concurrent_shifts[(staff, day, concurrent_audit_id_PM)] == 0)
    
    def add_audit_fairness_penalties(self):
        """
        監査の公平性ペナルティ
        """
        audit_section_ids = (13,14)  # 監査AM兼務業務のセクションIDと監査PM兼務業務のセクションID
        dispending_section_id = 1  # 調剤室専属業務のセクションID
        
        eligible_staff = [
            staff for staff in self.staff.index
            if dispending_section_id in self.eligible_sections.get(staff,[])
        ]
        if len(eligible_staff) < 2:
            print("⚠️ 監査の公平性ペナルティを計算するには、調剤室に対応可能なスタッフが2名以上必要です。")
            return []
        
        audit_counts = {staff: 0 for staff in eligible_staff}
        
        max_audit_count = self.model.NewIntVar(0,self.days,f'max_audit_count')
        min_audit_count = self.model.NewIntVar(0,self.days,f'min_audit_count')
        spread = self.model.NewIntVar(0,self.days,f'audit_spread')
        
        self.model.AddMaxEquality(max_audit_count,audit_counts.values())
        self.model.AddMinEquality(min_audit_count,audit_counts.values())
        self.model.Add(spread == max_audit_count - min_audit_count)
        
        return [spread]  # 監査の公平性ペナルティとして、最大割り当て数と最小割り当て数の差を返す