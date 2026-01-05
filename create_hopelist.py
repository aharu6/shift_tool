#曜日、日付により生じる今月の出勤・休み希望リストを作成する関数
#業務の都合によるもの、個人の希望とは別
import calendar
import datetime
import pandas as pd
import numpy as np
from openpyxl import Workbook
def create_hopelist(num_month):
    member_list = pd.read_excel("条件.xlsx",sheet_name="member_list",index_col=0,skiprows=1)
    print(member_list.head())
    #num_monthの月の日付を取得
    year = datetime.datetime.now().year
    num_days = calendar.monthrange(year,num_month)[1]

    #名前＿日付＿曜日の縦型データフレームを作成
    date_list = []
    for day in range(1,num_days+1):
        date = datetime.date(year,num_month,day)
        weekday = date.strftime("%a")
        for name in member_list.index:
            date_list.append([name,day,weekday])
    hopelist_df = pd.DataFrame(date_list,columns=["name","date","weekday"])
    
    hopelist_df["hope"] = 0
    # name == 6 は16日から22日は1とする
    for name in member_list.index:
        if name == 6:
            hopelist_df.loc[(hopelist_df["name"] == 6)&(hopelist_df["date"].between(16,22)),"hope"] = 1
    
    #条件.xlsxより読み出し、主任以上=trueの人は　第1、第3、第5月曜は役職者は役職者会議のため出勤
    #テストデータでは主任以上はnum:
    for name in member_list.index:
        if member_list.loc[name,'主任以上']==True:
            mondays = [day for day in range(1,num_days+1) if datetime.date(year,num_month,day).weekday()==0]
            for i,mon in enumerate(mondays):
                if i%2==0:
                    print(f"{mon}")
                    hopelist_df.loc[(hopelist_df["name"] == name) & (hopelist_df["date"] == mon), "hope"] = 1

    hopelist_df.to_excel(F"固定希望リスト_{num_month}月.xlsx",index=False)

    


if   __name__ == "__main__":
    input_month = int(input("希望リストを作成したい月を数字で入力してください（例：6月なら6と入力）: "))
    create_hopelist(input_month)