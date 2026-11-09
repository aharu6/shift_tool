import jpholiday
class Mode2Optimizer:
    def mode2_adjust_shift():
        """
        出勤有無調整後の週間配置を決めるモードの処理を行う関数
        """
        # ここに mode2 の処理を実装する
        print("出勤有無調整後の週間配置を決めるモードが選択されました。\n")
        print("このモードでは、既に決まっている出勤有無を考慮して、週間のシフト配置を調整します。\n")
        print("最初にすでに決まっている出勤日や当直情報の収集を行います。\n")
        year = int(input("対象年を入力してください（例：2026):"))
        month = int(input("対象月を入力してください(例:10):"))
        
        if month < 1 or month >12:
            raise ValueError("エラー:月は1から12の範囲で入力してください")
        
        #日曜祝日の取得
        hoidays = jpholiday.month
            