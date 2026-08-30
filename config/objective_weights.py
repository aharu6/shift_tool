"""Objective function weights and fairness tolerances."""

# Existing objective weights
WEIGHT_ONCALL_NEXTDAY = 10#当直明けの次の日の休み
WEIGHT_SUNDAY_HOLIDAY = 5#
WEIGHT_CONSECUTIVE_WORK = 20
WEIGHT_FIXED_MANAGER_MEETING = 15
WEIGHT_FIXED_GENERAL_MEETING = 4
WEIGHT_FIXED_YAKUSHIN_MEETING = 4
WEIGHT_PORIFA_FRIDAY = 2
WEIGHT_CHEMO_SATURDAY = 3
WEIGHT_PRIMARY_FAIRNESS = 6

# New fairness terms for consecutive work/off balance
WEIGHT_CONSECUTIVE_WORK_FAIRNESS = 6
WEIGHT_CONSECUTIVE_OFF_FAIRNESS = 6

# Allowable spread before fairness penalties kick in.
CONSECUTIVE_WORK_FAIRNESS_TOLERANCE = 2
CONSECUTIVE_OFF_FAIRNESS_TOLERANCE = 2

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