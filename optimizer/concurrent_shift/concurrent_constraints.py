from optimizer.base_constraint import BaseConstraint
from datetime import datetime
from optimizer.concurrent_shift import MeetingConstraints

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
        if safety_wg_penalties:
            WEIGHT_SAFETY_WG = 10  # 他の制約と同等の優先度
            safety_wg_penalty_term = WEIGHT_SAFETY_WG * sum(safety_wg_penalties) if safety_wg_penalties else 0
            self.optimizer.register_objective_term("safety_wg", safety_wg_penalty_term)
        if dem_round_penalties:
            WEIGHT_DEM_ROUND = 4
            dem_round_penalty_term = WEIGHT_DEM_ROUND * sum(dem_round_penalties) if dem_round_penalties else 0
            self.optimizer.register_objective_term("dem_round", dem_round_penalty_term)

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
                section_configs=section_configs,day = day,
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
        火曜1日は専属業務で配置
        - メンバー全員が出勤可能の日に開催する
        - 1人でも参加不可のスタッフがいればその日は対象外とする
        - 火曜日に開催されていればその週は開催しない
        - なるべく専属業務は出勤としたい
        - なるべく専属業務がない日は避けたい
        
        """
        penaltiles = []
        self.tuesday_porifa_week_num ,self.friday_porifa_week_num = self.meeting_constraints.get_porifa_week_num()
        
        for day in range(1,self.days+1):            
            # セクションID設定：ポリファーマシーは専属業務(11)、兼務業務は(10)
            floor_porifa_id = 11#get_eligible_sectionsで決めているポリファーマシー配置可能に割り当てられているセクションID
            concurrent_porifa_id = 10#兼務業務のセクションID
            #配置可能なスタッフリスト
            assigned_staff_porifa = []
            assigned_porifa_ids = []#perstaff制約用
            #必須メンバーのリスト
            required_porifa_staff = []
            #セクション設定を定義
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
            #曜日、祝日、前日祝日を取得
            weekday = self._get_weekday(day)
            is_wekday = weekday <=4 #月〜金
            is_holiday = self._is_holiday(day)
            is_monday = weekday == 0
            is_tuesday = weekday ==1
            is_friday = weekday == 4
            prev_day_is_holiday = day >1 and self._is_holiday(day-1)
            
        
            # 金曜日で、祝日でなく、設定されたポリファーマシー週の場合のみ処理
            if is_friday and not is_holiday and self.friday_porifa_week_num == (day-1)//7 +1:
                print(f"Day {day}はポリファーマシーの配置対象日です")
                if assigned_staff_porifa:
                    # 明けシフト(shift_id=17)を持つスタッフを取得
                    porifa_ake_vars = [self.shifts[(porifa_staff, day, 17)] for porifa_staff in assigned_porifa_ids]#
                    # 誰か1人でも明けシフトがあるかを判定
                    any_porifa_ake = self.model.NewBoolVar(f'any_porifa_ake_friday_{day}')
                    if porifa_ake_vars:
                        self.model.AddMaxEquality(any_porifa_ake, porifa_ake_vars)
                    else:
                        self.model.Add(any_porifa_ake == 0)

                    available_porifa = section_configs['ポリファーマシー']['available_list']
                    if available_porifa:
                        #全員が配置可能(全is_available == 1)かをBoolVarで確認
                        all_porifa_available = self.model.NewBoolVar(f'all_porifa_available_{day}')
                        self.model.AddMinEquality(all_porifa_available,available_porifa)
                        #全員揃えば開催 section(cocurrent):10
                        for porifa_staff in assigned_porifa_ids:
                            self.model.Add(self.shifts[(porifa_staff,day,17)] == 0).OnlyEnforceIf([all_porifa_available, any_porifa_ake.Not()])#
                            #ポリファーマシー(section10)に割り当てる
                            self.model.Add(self.concurrent_shifts[(porifa_staff,day,concurrent_porifa_id)]==1).OnlyEnforceIf([all_porifa_available, any_porifa_ake.Not()])
                            #兼務業務なしは許容しない
                            self.model.Add(self.concurrent_shifts[(porifa_staff,day,concurrent_porifa_id)]==0).OnlyEnforceIf(all_porifa_available.Not())
                            self.model.Add(self.concurrent_shifts[(porifa_staff,day,concurrent_porifa_id)]==0).OnlyEnforceIf(any_porifa_ake)
                            
                            #なるべく専属業務が休みにならないようにペナルティを追加
                            penalty_var = self.model.NewBoolVar('penalty_friday_porifa_'+str(porifa_staff)+'_'+str(day))
                            self.model.Add(self.shifts[(porifa_staff,day,0)]==0).OnlyEnforceIf(penalty_var.Not())
                            penaltiles.append(penalty_var)
                            
                        #欠席者がいれば開催なし
                        self.model.Add(sum(assigned_staff_porifa)==0).OnlyEnforceIf(all_porifa_available.Not())
                        self.model.Add(sum(assigned_staff_porifa)==0).OnlyEnforceIf(any_porifa_ake)
                        print(f"Day {day}:ポリファーマシー 全員揃えば出勤+兼務業務に配置、なしにはならない")
                    else:
                        print(f"day{day}:ポリファーマシーの配置可能なスタッフが0人です")
                        self.model.Add(sum(assigned_staff_porifa)==0)
                else:
                    print(f"⚠️ [ポリファーマシー] Day {day}: ポリファーマシーに対応可能なスタッフが登録されていません")
                    self.model.Add(sum(assigned_staff_porifa)==0)
        
            else:
                pass#火曜日のポリファーマシー対応は専属業務で配置するためここでは制約を追加しない
        
        return penaltiles

    #土曜日のケモ
    def add_concurrent_chemo(self):
        """
        土は2名を調剤室へ配置、専属業務としてのケモは0名→work_constraintsへ
        兼務業務にケモを配置する制約
        配置可能なメンバーから最大2名を配置する
        - 調剤室へ配置した最大2名が対象になる
        - 明けの次の日の休みになるべく配置しない
        - TODO:例外的にwork_constraintsで定義のため、必要なくなるかも
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
        - 最低1名いれば良い
        - TODO:当直制約へ明けが配置対象日にならないように
        
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
                section_configs=section_configs,day = day,
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

                    if available_dem_round:
                        # ペナルティ計算: 対応可能スタッフ数 - 配置スタッフ数
                        unallocated_penalty = len(available_dem_round) - sum(dem_round_assign_vars)
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
                section_configs=section_configs,day = day,
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
