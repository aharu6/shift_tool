"""Objective function weights and fairness tolerances."""

# Existing objective weights
WEIGHT_ONCALL_NEXTDAY = 60#当直明けの次の日の休み
WEIGHT_SUNDAY_HOLIDAY = 5#日曜・祝日の出勤に関する重み
WEIGHT_CONSECUTIVE_WORK = 20#連続勤務に関する重み
WEIGHT_FIXED_MANAGER_MEETING = 15
WEIGHT_FIXED_GENERAL_MEETING = 2
WEIGHT_FIXED_YAKUSHIN_MEETING = 2
WEIGHT_FIXED_MEDICAL_SAFETY_WORKING_GROUP = 8
WEIGHT_PORIFA_FRIDAY = 2
WEIGHT_PORIFA_PAIR = 16 # 第W週金曜＋第W+1週火曜の連続開催推奨ボーナス/ペナルティ重み
WEIGHT_PORIFA_UNHELD = 50 # ポリファ未開催ペナルティ
WEIGHT_CHEMO_SATURDAY = 3
WEIGHT_PRIMARY_FAIRNESS = 20
WEIGHT_PREVIOUS_YEAR_DECEMBER_30_AVOIDANCE = 20#前年12月30日の勤務回避の重み
WEIGHT_PREVIOUS_DECEMBER_31_AVOIDANCE = 20#前年12月31日の勤務回避の重み
WEIGHT_PREVIOUS_JANUARY_1_AVOIDANCE = 20#前年1月1日の勤務回避の重み
WEIGHT_PREVIOUS_JANUARY_2_AVOIDANCE = 20#前年1月2日の勤務回避の重み
WEIGHT_PREVIOUS_JANUARY_3_AVOIDANCE = 20#前年1月3日の勤務回避の重み
WEIGHT_ONCALL_PREV_MONTH_BALANCE = 100000
WEIGHT_ONCALL_TWO_PER_MONTH_HISTORY = 100

# New fairness terms for consecut   ive work/off balance
WEIGHT_CONSECUTIVE_WORK_FAIRNESS = 6#連続勤務の公平性に関する重み
WEIGHT_CONSECUTIVE_OFF_FAIRNESS = 6#連続休暇の公平性に関する重み
WEIGHT_CONSECUTIVE_DAYOFF = 6#連続休暇に関する重み
# Allowable spread before fairness penalties kick in.
CONSECUTIVE_WORK_FAIRNESS_TOLERANCE = 2
CONSECUTIVE_OFF_FAIRNESS_TOLERANCE = 1000

# New objective weight for second Friday conference
#第二金曜日、病棟担当者カンファレンス参加のペナルティを追加
WEIGHT_SECOND_FRIDAY_CONFERENCE = 5


# New objective weight for manager shift requests
#DIかつ課長スタッフの16日から23日までの出勤希望をなるべく叶えるペナルティを追加
WEIGHT_MANAGER = 20

# 課長担当は、配置可能な人がいる日は優先するが必須にはしない
WEIGHT_KACHO_ASSIGNMENT = 3

# New objective weight for audit fairness
#監査の公平性をなるべく保つペナルティを追加
WEIGHT_AUDIT_FAIRNESS = 6
#心不全回診担当の公平性をなるべく保つペナルティを追加
WEIGHT_HEART_TEAM_FAIRNESS = 6
# 感染管理,ASTの公平性をなるべく保つペナルティを追加
WEIGHT_INFECTION_CONTROL_FAIRNESS = 6