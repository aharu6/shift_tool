import datetime
import jpholiday

class RequiredStaff():
    #曜日、または日付ごとにより、各フロアの必要出勤人数を算出,
    #最終的に日付毎に各フロアの人数がわかるリストを作成する
    def __init__(self,year,month,date,section):
        self.year = year
        self.month = month
        self.date = date
        self.section = section
        self.required_number = {}
        
        
    def _get_weekday(self,day):
        weekday = datetime.date(self.year,self.month,day).weekday()
        return weekday
    
    def _is_hokiday(self,day):
        check_date =datetime.date(self.year,self.month,day)
        print(check_date)
        return jpholiday.is_holiday(check_date)
        
    #TODO:土日祝の判定
    
    #日毎にスタッフの最低必要人数を決定
    #フロア毎の最低必要人数リストも合わせて作成
        """
        1,2
        3
        4
        5
        DI
        入退院・調剤室
        緩和回診
        心不全回診
        
        """