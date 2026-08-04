"""Objective function weights and fairness tolerances."""

# Existing objective weights
WEIGHT_ONCALL_NEXTDAY = 10#当直明けの次の日の休み
WEIGHT_SUNDAY_HOLIDAY = 5#
WEIGHT_CONSECUTIVE_WORK = 20
WEIGHT_FIXED_MANAGER_MEETING = 15
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