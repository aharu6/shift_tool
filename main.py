from ortools.sat.python import cp_model
from openpyxl import Workbook
from openpyxl.styles import PatternFill,Font,Alignment
import pandas as pd
def create_shift_schedule():
    model = cp_model.CpModel()

    num_employees = 52
    num_days = 31
    num_shifts = 13

    read_xlsx_data = pd.read_excel()