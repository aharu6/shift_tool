#曜日、日付により生じる今月の出勤・休み希望リストを作成する関数
#業務の都合によるもの、個人の希望とは別
import calendar
import datetime
import pandas as pd
import numpy as np
from openpyxl import Workbook
def create_hopelist(num_month):
    """
    固定の希望リストを構築、変更点を更新する
    毎月の日付・曜日等で出勤・休みが確定しているもの

    """
    member_list = pd.read_excel("条件.xlsx",sheet_name="member_list",index_col=0,skiprows=1)
    #num_monthの月の日付を取得
    year = datetime.datetime.now().year
    num_days = calendar.monthrange(year,num_month)[1]
    master_mentenance_staff = [name for name in member_list.loc[member_list['マスター管理']==True].index]
    
    #名前＿日付＿曜日の縦型データフレームを作成
    date_list = []
    for day in range(1,num_days+1):
        date = datetime.date(year,num_month,day)
        weekday = date.strftime("%a")
        for name in member_list.index:
            date_list.append([name,day,weekday])
    hopelist_df = pd.DataFrame(date_list,columns=["name","date","weekday"])
    
    hopelist_df["hope"] = 0
    
    #休職中の人は全日休みに設定
    for name in member_list.index:
        if member_list.loc[name,'休職']==True:
            hopelist_df.loc[hopelist_df["name"]==name,"hope"] = 0
            
    
    # name == 6 は16日から22日は8:DIとする
    for name in member_list.index:
        if name == 6:
            hopelist_df.loc[(hopelist_df["name"] == 6)&(hopelist_df["date"].between(16,22)),"hope"] = 8
    
    #name==6は火曜と金曜は認知症せん妄ラウンドのため出勤
    for name in member_list.index:
        if name == 6:
            for day in range(1,num_days+1):
                if datetime.date(year,num_month,day).weekday() in [1,4]:
                    hopelist_df.loc[(hopelist_df["name"] == 6)&(hopelist_df["date"] == day),"hope"] = 12
    #name==6は第二金曜は病棟担当者カンファレンスのため出勤,配置はDI
    for name in member_list.index:
        if name == 6:
            second_friday = [day for day in range(1,num_days+1) if datetime.date(year,num_month,day).weekday()==4][1]
            hopelist_df.loc[(hopelist_df["name"] == 6)&(hopelist_df["date"] == second_friday),"hope"] = 8
            
    #条件.xlsxより読み出し、主任以上=trueの人は　第1、第3、第5月曜は役職者は役職者会議のため出勤,回診など別業務がある場合にはそちらを優先 兼務？
    #テストデータでは主任以上はnum:
    for name in member_list.index:
        if member_list.loc[name,'主任以上']==True:
            mondays = [day for day in range(1,num_days+1) if datetime.date(year,num_month,day).weekday()==0]
            for i,mon in enumerate(mondays):
                if i%2==0:
                    print(f"{mon}")
                    hopelist_df.loc[(hopelist_df["name"] == name) & (hopelist_df["date"] == mon), "hope"] = 1
                    
    #役職者は偶数月の第一木曜日出勤（薬審:15）
    for name in member_list.index:
        if member_list.loc[name,'主任以上']==True:
            if num_month%2==0:
                first_thursday = [day for day in range(1,num_days+1) if datetime.date(year,num_month,day).weekday()==3][0]
                hopelist_df.loc[(hopelist_df['name']==name)&(hopelist_df['date']==first_thursday),'hope']=15
        
    #TODO:マスター管理者としてのシフトは午後に入れる
    
    #緩和回診スタッフ月曜　火曜　木曜出勤
    for name in member_list.index:
        if member_list.loc[name,'緩和回診']==True:
            for day in range(1,num_days+1):
                if datetime.date(year,num_month,day).weekday() in [0,1,3]:
                    hopelist_df.loc[(hopelist_df['name']==name)&(hopelist_df['date']==day),'hope']=1
                    
    #ポリファーマシーフタッフ　金曜午後　火曜出勤
    for name in member_list.index:
        if member_list.loc[name,'ポリファーマシーチーム']==True:
            for day in range(1,num_days+1):
                if datetime.date(year,num_month,day).weekday() ==4:
                    hopelist_df.loc[(hopelist_df['name']==name)&(hopelist_df['date']==day),'hope']=1
                if datetime.date(year,num_month,day).weekday() ==1:
                    hopelist_df.loc[(hopelist_df['name']==name)&(hopelist_df['date']==day),'hope']=1

    
    return hopelist_df.pivot(index='name',columns='date',values='hope')

    


if   __name__ == "__main__":
    input_month = int(input("希望リストを作成したい月を数字で入力してください（例：6月なら6と入力）: "))
    create_hopelist(input_month)