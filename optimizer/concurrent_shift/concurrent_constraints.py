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
        #self.add_concurrent_ri()
        
        

    def add_concurrent_ri(self):
        """
        RI
        - 月〜土は1名
        - 日曜祝日は0名、上で定義済み
        - 休み希望の日は配置しない,上で定義済み
        - 配置可能なスタッフがいない場合は0人でも許容
        - TODO:割り振りの優先度 name == > name == > name == > 条件シートの優先度
        """
        for day in range(1,self.days +1):
            concurrent_ri_id = 4
            assigned_staff_ri = []
            assigned_ri_ids = []
            section_configs = {}
            
        
    def add_concurrent_porifa(self):
        """
        金曜午後のポリファーマシーの配置
        火曜1日は専属業務で配置
        - メンバー全員が出勤可能の日に開催する
        - 1人でも参加不可のスタッフがいればその日は対象外とする
        - 火曜日に開催されていればその週は開催しない
        - TODO:専属業務が何も無い日は対象外としたい、get_porifa_week_numで定義した週に適用する
        - なるべく専属業務は出勤としたい
        - なるべく専属業務がない日は避けたい
        
        """
        penaltiles = []
        self.tuesday_porifa_week_num ,self.friday_porifa_week_num = self.meeting_constraints.get_porifa_week_num()
        
        for day in range(1,self.days+1):            
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
            #デバッグ　ポリファーマシー対応可能なスタッフをprintする
            print(f"Day{day}ポリファーマシーに対応可能なスタッフ{assigned_porifa_ids}です")
            #曜日、祝日、前日祝日を取得
            weekday = self._get_weekday(day)
            is_wekday = weekday <=4 #月〜金
            is_holiday = self._is_holiday(day)
            is_monday = weekday == 0
            is_tuesday = weekday ==1
            is_friday = weekday == 4
            prev_day_is_holiday = day >1 and self._is_holiday(day-1)
            
        
            if is_friday and not is_holiday and self.friday_porifa_week_num == (day-1)//7 +1:
                print(f"Day {day}はポリファーマシーの配置対象日です")
                if assigned_staff_porifa:
                    available_porifa = section_configs['ポリファーマシー']['available_list']
                    if available_porifa:
                        #全員が配置可能(全is_available == 1)かをBoolVarで確認
                        all_porifa_available = self.model.NewBoolVar(f'all_porifa_available_{day}')
                        self.model.AddMinEquality(all_porifa_available,available_porifa)
                        #全員揃えば開催 section(cocurrent):10
                        for porifa_staff in assigned_porifa_ids:
                            #ポリファーマシー(section10)に割り当てる
                            self.model.Add(self.concurrent_shifts[(porifa_staff,day,concurrent_porifa_id)]==1).OnlyEnforceIf(all_porifa_available)
                            #兼務業務なしは許容しない
                            self.model.Add(self.concurrent_shifts[(porifa_staff,day,concurrent_porifa_id)]==0).OnlyEnforceIf(all_porifa_available.Not())
                            
                            #なるべく専属業務が休みにならないようにペナルティを追加
                            penalty_var = self.model.NewBoolVar('penalty_friday_porifa_'+str(porifa_staff)+'_'+str(day))
                            self.model.Add(self.shifts[(porifa_staff,day,0)]==0).OnlyEnforceIf(penalty_var.Not())
                            penaltiles.append(penalty_var)
                            
                        #欠席者がいれば開催なし
                        self.model.Add(sum(assigned_staff_porifa)==0).OnlyEnforceIf(all_porifa_available.Not())
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
