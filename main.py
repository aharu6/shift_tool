import calendar
import random
from optimizer.mode1.mode1 import Mode1Optimizer
from optimizer.shift_optimizer import ShiftOptimizer
from tkinter import filedialog
from ortools.sat.python import cp_model
from required_staff import RequiredStaff
import pandas as pd
pd.set_option('display.max_columns', None)
pd.set_option('display.max_rows', None)
pd.set_option('display.width', None)
pd.set_option('display.max_colwidth', None)
from config.sections import PRIMARY_SECTIONS
from config.concurrent_sections import CONCURRENT_SECTIONS
import jpholiday
from pathlib import Path
from mk_staff_column import MkStafflist
from requests.mk_requests import MkRequests
from staff_name_matching import (
    normalize_name_index,
    normalize_staff_name,
    validate_name_alignment,
)
from create_calender import CalendarCreator
import tkinter.filedialog
import os
from openpyxl import load_workbook
from openpyxl.styles import Border
from run_log import RunLog,TeeStream
from get_previous_data import GetPreviousData
from optimizer.mode2.mode2 import Mode2Optimizer

iDir = os.path.abspath(os.path.dirname(__file__))

_PREVIOUS_JANUARY_WORK_MARKERS = (
    "休", "休み", "指", "有", "夏",
    "慶", "慶弔", "育", "育休", "特",
)

def _print_fairness_summary(df_result: pd.DataFrame):
    """専属業務・当直の偏りサマリを表示する。"""
    print("\n===== 公平性サマリ =====")

    primary_df = df_result[df_result['専属業務'].isin(['休み', '明け']) == False]
    if primary_df.empty:
        print("専属業務: 対象データなし")
    else:
        primary_counts = primary_df.groupby(['専属業務', 'Name']).size().unstack(fill_value=0)
        for section_name, row in primary_counts.iterrows():
            max_count = int(row.max())
            min_count = int(row.min())
            diff = max_count - min_count
            print(f"専属業務[{section_name}] max={max_count} min={min_count} diff={diff}")

    oncall_series = df_result.groupby('Name')['当直'].apply(
        lambda values: sum(1 for val in values if ('当直担当' in val or '当直相方' in val))
    )
    if oncall_series.empty:
        print("当直: 対象データなし")
    else:
        oncall_max = int(oncall_series.max())
        oncall_min = int(oncall_series.min())
        oncall_diff = oncall_max - oncall_min
        print(f"当直回数 max={oncall_max} min={oncall_min} diff={oncall_diff}")

def create_shift_schedule():
    """
    ========================================
    1. データ読み込み
    ========================================
    """    
    # 初期ディレクトリをスクリプトのあるディレクトリに設定
    iDir = os.path.abspath(os.path.dirname(__file__))
    
    print("================================================================================")
    print("シフト作成を開始します。初回の当直・出勤有無を決める場合は1を。\n")
    print("調整後の週間配置を決める場合は2を選択してください")
    mode = int(input("モードを選択してください（1または2）: "))
    if mode not in [1,2]:
        raise ValueError("エラー: 1または2を入力してください。最初からやり直してください")
    else:
        print(f"選択されたモード: {mode}")
    
    if mode == 1:
        Mode1Optimizer.mode1_initial_shift()
        
    elif mode == 2:
        Mode2Optimizer.mode2_adjust_shift()

if __name__ == "__main__":
    RunLog._setup_run_log()
    create_shift_schedule()