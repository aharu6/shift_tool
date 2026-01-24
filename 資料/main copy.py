from ortools.sat.python import cp_model
from openpyxl import Workbook
from openpyxl.styles import PatternFill,Font,Alignment
def create_shift_schedule():
    """
    create_shift_schedule の Docstring
    [e,d,s]==[従業員,日,シフト]
    """
    # モデルの作成
    model = cp_model.CpModel()
    # パラメータ
    num_employees = 52 # 従業員数
    num_days = 31  # 1ヶ月
    num_shifts = 4  # 休み、出勤、当直,当直明け

    #休み希望の例
    day_off_requests = {
        0:[5,12,19],
        1:[6,13,20],
        2:[7,14],
    }

    # 月毎に異なる出勤可能日数
    max_working_days_per_month = 20  # 例として20日に設定
    min_working_days_per_month = 15  # 例として15日に設定

    #　必要人数の設定
    #日毎に必要人数異なる
    required_staff_per_shift = {}
    for d in range(num_days):
        if d in [6,13,20,28]:
            required_staff_per_shift[d] = 4
        else:
            required_staff_per_shift[d] = 27

    # 変数: shifts[(e, d, s)] は従業員eが日dにシフトsで勤務するかどうか
    shifts = {}
    for e in range(num_employees):
        for d in range(num_days):
            for s in range(num_shifts):
                shifts[(e, d, s)] = model.NewBoolVar(f'shift_e{e}_d{d}_s{s}')
    
    #休み希望が叶えられたかを示す変数
    day_off_granted = {}
    for e in day_off_requests:
        for d in day_off_requests[e]:
            day_off_granted[(e,d)] = model.NewBoolVar(f'day_off_granted_e{e}_d{d}')
            model.Add(shifts[(e,d,0)] == 1).OnlyEnforceIf(day_off_granted[(e,d)])
            model.Add(shifts[(e,d,0)] == 0).OnlyEnforceIf(day_off_granted[(e,d)].Not())

    # 制約1: いずれかのシフトに1日1回だけ割り当てる
    for e in range(num_employees):
        for d in range(num_days):
            model.Add(sum(shifts[(e, d, s)] for s in range(num_shifts)) <= 1)
    
    # 制約2: 各シフトには出勤s=1 と当直S=2を合わせて最大人数を設定
    for d in range(num_days):
        for s in range(num_shifts):
            model.Add(sum(shifts[(e, d, 1)] for e in range(num_employees)) +sum(shifts[(e, d, 2)] for e in range(num_employees)) >= required_staff_per_shift[d])
    
    #制約：毎日2人はS=2（当直）を割り当てる
    for d in range(num_days):
        model.Add(sum(shifts[(e, d, 2)] for e in range(num_employees)) == 2)

    # 制約3: 各従業員の勤務日数を最小・最大で制限
    #TODO:月によって指定の休みが変わるから、最大勤務日数も異なりそう
    for e in range(num_employees):
        workind_day = sum(shifts[(e, d, 1)] + shifts[(e, d, 2)] + shifts[(e, d, 3)] for d in range(num_days))
        model.Add(workind_day <= max_working_days_per_month)
        model.Add(workind_day >= min_working_days_per_month)

    #制約：各従業員は月に当直(S=2)を最大2日まで
    for e in range(num_employees):
        model.Add(sum(shifts[(e, d, 2)] for d in range(num_days)) <= 2)

    #制約：　s=1とs=2の連続は最低1回、最大6回まで
    for e in range(num_employees):
        for d in range(num_days-6):
            model.Add(sum(shifts[(e, d + i, 1)]+shifts[(e, d + i, 2)]+shifts[(e, d + i, 3)] for i in range(7)) <= 6)


    #
    # 制約4: s=2（当直）次の日はs=3（当直明け）を指定
    for e in range(num_employees):
        for d in range(num_days - 1):
            model.Add(shifts[(e, d + 1, 3)] == 1).OnlyEnforceIf(shifts[(e, d, 2)])

    #制約5: S=3（当直明け）はS=2の次の日にのみ設定できる
    for e in range(num_employees):
        for d in range(1, num_days):
            model.Add(shifts[e,d-1,2] == 1).OnlyEnforceIf(shifts[e,d,3])

    #ソフト制約：　S=3（当直明け）の次の日は可能な限りS=0(休み)を設定
    day_off_after_ake = {}
    for e in range(num_employees):
        for d in range(num_days -1):
            day_off_after_ake[(e,d)] = model.NewBoolVar(f'day_off_after_ake_e{e}_d{d}')
            model.Add(shifts[(e,d+1,0)] == 1).OnlyEnforceIf([shifts[(e,d,3)],day_off_after_ake[(e,d)]])
            model.Add(shifts[(e,d+1,0)] == 0).OnlyEnforceIf([shifts[(e,d,3)],day_off_after_ake[(e,d)].Not()])

    #制約: 前回の当直から次回の当直は最低6日以上空ける
    for e in range(num_employees):
        for d in range(num_days - 6):
            model.Add(sum(shifts[(e, d + i, 2)] for i in range(7)) <= 1)
    #目的関数：休み希望が叶えられた数を最大化
    #両方に同じ重みをつけているが、優先度を変えることはできる
    model.Maximize(
        sum(day_off_granted.values())+sum(day_off_after_ake.values())
    )

    # ソルバーの実行
    solver = cp_model.CpSolver()
    status = solver.Solve(model)
    
    if status == cp_model.OPTIMAL or status == cp_model.FEASIBLE:
        print('勤務表:')
        print('従業員 | ' + ' '.join([f'{d+1:2}' for d in range(num_days)]))
        for e in range(num_employees):
            schedule = []
            for d in range(num_days):
                assigned = False
                for s in range(num_shifts):
                    if solver.Value(shifts[(e, d, s)]):
                        schedule.append(s)
                        assigned = True
                        break
                if not assigned:
                    schedule.append('-')
            print(f'従業員{e} | {" ".join(map(str, schedule))}')
            
    else:
        print('解が見つかりませんでした')

if __name__ == '__main__':
    create_shift_schedule()