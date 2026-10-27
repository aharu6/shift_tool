from ortools.sat.python import cp_model
import json

from ortools.sat.python import cp_model


model = cp_model.CpModel()
solver = cp_model.CpSolver()

# 1. 変数の定義
x = model.NewBoolVar('x')
y = model.NewBoolVar('y')

# 2. 通常の制約（x と y は同時に True になれない）
model.Add(x + y <= 1)

# ---------------------------------------------------------
# パターンA: x=True, y=True という「仮定」を置いて解いてみる（矛盾するはず）
# ---------------------------------------------------------
print("--- パターンA ---")
model.AddAssumptions([x, y])  # x == True かつ y == True を仮定

status = solver.Solve(model)
print(f"ステータス: {solver.StatusName(status)}") # INFEASIBLE (解なし)

# なぜ解がなかったのか、原因となった仮定（コア）を特定する
# ※注意: インクリメンタルソルバーのパラメータ設定が必要な場合があります
suff_assumptions = solver.SufficientAssumedLiterals()
print(f"矛盾の原因となった仮定: {suff_assumptions}") 


# ---------------------------------------------------------
# パターンB: 再度 Solve を呼ぶ（前の仮定は自動でクリアされる）
# ---------------------------------------------------------
print("\n--- パターンB ---")
model.AddAssumptions([x, y.Not()])  # x == True かつ y == False を仮定

status = solver.Solve(model)
print(f"ステータス: {solver.StatusName(status)}") # OPTIMAL または FEASIBLE
if status == cp_model.OPTIMAL or status == cp_model.FEASIBLE:
    print(f"x: {solver.Value(x)}, y: {solver.Value(y)}")
