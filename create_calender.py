#カレンダー作成用のスクリプト
#mainから処理を分岐
#日付を横長に展開したcsvファイルを保存
#変形・整形・保存処理を担う
from pathlib import Path
from typing import List, Union
import calendar

import jpholiday
import pandas as pd

from optimizer.method.staff_name_matching import normalize_staff_name


def _pivot_staff_day_wide(
    df: pd.DataFrame,
    value_column: Union[str, List[str]],
    fill_value: str,
) -> pd.DataFrame:
    """スタッフの入力順を維持したまま日付横持ちに変換する。"""
    name_column = 'Name' if 'Name' in df.columns else 'スタッフ'
    if name_column not in df.columns:
        raise KeyError("Nameまたはスタッフ列が必要です")

    staff_order = pd.Index(df[name_column].drop_duplicates())
    wide = df.pivot_table(
        index=name_column,
        columns='日付',
        values=value_column,
        aggfunc='first',
        fill_value=fill_value,
        sort=False,
    )
    min_day = int(df['日付'].min())
    max_day = int(df['日付'].max())
    wide = wide.reindex(index=staff_order, columns=range(min_day, max_day + 1), fill_value=fill_value)
    wide.index.name = 'Name'
    return wide


def _add_calendar_header_rows(
    wide: pd.DataFrame,
    weekdays: pd.Series,
) -> pd.DataFrame:
    """日付行・曜日行をスタッフ行の前に追加する。"""
    weekday_row = weekdays.reindex(wide.columns)
    if weekday_row.isna().any():
        missing_days = weekday_row[weekday_row.isna()].index.tolist()
        raise ValueError(f"曜日が設定されていない日付があります: {missing_days}")

    staff_rows = wide.reset_index()
    header_rows = pd.DataFrame(
        [
            ['Name', *wide.columns.tolist()],
            ['曜日', *weekday_row.tolist()],
        ],
        columns=staff_rows.columns,
    )
    return pd.concat([header_rows, staff_rows], ignore_index=True)


class CalendarCreator:
    def save_results(
        self,
        df_result: pd.DataFrame,
        hope_list: pd.DataFrame,
        optimizer,
        year: int,
        month: int,
    ) -> None:
        result_dir = Path("result")
        result_dir.mkdir(exist_ok=True)# 結果保存用ディレクトリを作成
        result_dir_degug = result_dir / "debug"
        result_dir_degug.mkdir(exist_ok=True)# デバッグ用ディレクトリを作成
        #縦長データを保存 デバッグフォルダに保存
        df_result.to_csv(
            result_dir_degug / f'Shift_{year}_{month:02d}.csv',
            index=False,
            encoding='utf-8-sig',
        )
        
        #日付を横長に展開　デバッグフォルダに保存
        df_result_long = _pivot_staff_day_wide(
            df_result,
            value_column='当直',
            fill_value=' ',
        )
        df_result_long.to_csv(
            result_dir_degug / f'Shift_wide_{year}_{month:02d}.csv',
            index=True,
            encoding='utf-8-sig',
        )
        
        #当直を◎に変換
        df_result_cleaned = df_result.copy()
        df_result_cleaned['当直'] = df_result_cleaned.apply(
            lambda row: '◎' if '当直' in row['当直'] else ' ',
            axis=1,
        )
        #当直翌日に明け（○）を付与
        df_result_cleaned['明け'] = (
            df_result_cleaned.groupby('Name')['当直']
            .shift(1)
            .apply(lambda value: '○' if value == '◎' else ' ')
        )
        #希望リストを縦長に変換
        #後に結合する用
        df_hope = hope_list.melt(
            id_vars=['Name'],
            var_name='日付',
            value_name='希望内容',
        )

        #シフト結果と希望リストを結合するためのキーを作成
        shift_for_merge = df_result_cleaned.copy()
        shift_for_merge["_name_key"] = shift_for_merge["Name"].map(normalize_staff_name)
        shift_for_merge["_day_key"] = pd.to_numeric(
            shift_for_merge["日付"], errors="coerce"
        ).astype("Int64")

        #希望リストにも同様のキーを作成
        df_hope["_name_key"] = df_hope["Name"].map(normalize_staff_name)
        df_hope["_day_key"] = pd.to_numeric(
            df_hope["日付"], errors="coerce"
        ).astype("Int64")

        #シフト結果と希望リストをキーで結合
        df_merged = shift_for_merge.merge(
            df_hope[["_name_key", "_day_key", "希望内容"]],
            how="left",
            on=["_name_key", "_day_key"],
            validate="one_to_one",
        ).drop(columns=["_name_key", "_day_key"])

        #希望リストの内容を許可されたものだけに制限
        allowed_hopes = [
            '指','AM指','PM指', '休み', '特', '有', 'AM有', 'PM有', 'AM夏', 'PM夏', '夏', '産', '育',
            '慶', '研修', '研', '学会', '学',
            'AM指PM有','AM有PM指'
        ]
        df_merged['希望内容'] = df_merged['希望内容'].apply(
            lambda value: value if value in allowed_hopes else ' '
        )

        #各フロア情報を結合
        for floor_column in ['Floor', 'Floor2', 'Floor3']:
            df_result_cleaned = df_result_cleaned.merge(
                optimizer.staff[[floor_column]],
                how='left',
                left_on='Name',
                right_index=True,
            )
        #外来に所属するかのキーを設定
        df_result_cleaned['外来有無'] = df_result_cleaned.apply(
            lambda row: 9 in [
                floor for floor in [row['Floor'], row['Floor2'], row['Floor3']]
                if pd.notna(floor)
            ],
            axis=1,
        )
        #外来所属者の当直を制限
        df_result_cleaned['当直'] = df_result_cleaned.apply(
            lambda row: (
                row['当直']
                if not row['外来有無'] or row['当直'] in ['◎']
                else ''
            ),
            axis=1,
        )
        #シフト結果と希望リストを結合して縦長形式にする
        df_long = df_result_cleaned.merge(
            df_merged[['Name', '日付', '希望内容']],
            how='left',
            on=['Name', '日付'],
        )

        if '勤務状態' in df_merged.columns:
            df_merged['統合結果'] = df_merged.apply(
                lambda row: (
                    '◎' if row['当直'] == '◎' else
                    '1' if row['勤務状態'] == '出勤' else
                    '0' if row['勤務状態'] == '非出勤' else
                    ''
                ),
                axis=1,
            )
        else:
            df_merged['統合結果'] = df_merged.apply(
                lambda row: (
                    '◎' if row['当直'] == '◎' else
                    '1' if row['専属業務'] == 1 else
                    '0'
                ),
                axis=1,
            )
        
        #縦長形式の当直結果を保存
        oncall_columns = [
            'Name', '日付', '統合結果', '当直', '明け', '希望内容'
        ]
        if '勤務状態' in df_merged.columns:
            oncall_columns.append('勤務状態')
        else:
            oncall_columns.extend(['専属業務', '兼務業務'])
        oncall_result = df_merged[oncall_columns]
        oncall_result.to_csv(
            result_dir_degug / f'oncall_shift_long_{year}_{month:02d}.csv',
            index=False,
            encoding='utf-8-sig',
        )

        def format_oncall_display(row):
            if str(row.get('当直', '')).strip() == '◎':
                return '◎'
            if str(row.get('明け', '')).strip() == '○':
                return '○'
            hope = str(row.get('希望内容', '')).strip()
            if hope in allowed_hopes:
                return hope
            if str(row.get('勤務状態', '')).strip() == '非出勤':
                return '指'
            return ''
        #縦長形式の当直結果を横長に変換して表示用に整形
        df_long['統合結果'] = df_long.apply(format_oncall_display, axis=1)
        on_call_result = _pivot_staff_day_wide(
            df_long[['Name', '日付', '統合結果']],
            value_column='統合結果',
            fill_value='',
        )
        #横長形式の当直結果に当直回数を追加
        on_call_result['当直回数'] = on_call_result.apply(
            lambda row: sum(1 for value in row if '◎' in str(value)),
            axis=1,
        )
        on_call_result.to_csv(
            result_dir_degug / f'oncall_shift_wide_{year}_{month:02d}.csv',
            index=True,
            encoding='utf-8-sig',
        )

        # 勤務状態の横長形式を作成して保存
        # 月間のシフト提出用
        #　当直、希望休、外来有無情報を反映
        #df_long columns['Name', '日付', '統合結果', '当直', '明け', '希望内容', '勤務状態']
        #曜日列を追加 月・火・水・木・金・土・日
        df_long['曜日'] = df_long['日付'].map(
            lambda day: pd.Timestamp(
                year=year,
                month=month,
                day=int(day),
            ).strftime('%a')
        )
        # 日本語の曜日に変換
        df_long['曜日'] = df_long['曜日'].map({
            'Mon': '月',
            'Tue': '火',
            'Wed': '水',
            'Thu': '木',
            'Fri': '金',
            'Sat': '土',
            'Sun': '日'
        })
        if '勤務状態' in df_long.columns:
            work_status_wide = _pivot_staff_day_wide(
                df_long,
                value_column='統合結果',
                fill_value='未判定',
            )
            # 曜日情報を抽出
            weekday = (
                df_long.drop_duplicates('日付')
                .set_index('日付')['曜日']
            )
            work_status_calendar = _add_calendar_header_rows(
                work_status_wide,
                weekday,
            )
        
            work_status_calendar.to_csv(
                result_dir_degug / f'work_status_wide_{year}_{month:02d}.csv',
                index=False,
                header=False,
                encoding='utf-8-sig',
            )
            work_status_wide_excel_path = result_dir / f'work_status_wide_{year}_{month:02d}.xlsx'
            with pd.ExcelWriter(work_status_wide_excel_path, engine='openpyxl') as writer:
                work_status_calendar.to_excel(
                    writer,
                    sheet_name='Sheet1',
                    index=False,
                    header=False,
                )

    def _cleanup_weekly_df(week_df: pd.DataFrame, staff_info=None,year:int=None,month:int=None,) -> pd.DataFrame:
        """週ごとのシフト結果を整形する。
        - 外来行は当直者のみ表示
        - 当直者名の末尾に◎を付与する
        - 兼務業務内容を反映する
        - 監査AMの記載があるスタッフは専属業務名を「監査AM」に変更する
        week_df:
            index: 専属業務
            columns: 日付（曜日）
            values: スタッフ名
        staff_info:Shiftoptimizer.staff
        week_df_original:改行編集前の元データ
        """
        source_df = week_df.copy()
        # 緩和回診のAM担当を「専属業務」列に反映する
        palliative_care_mask = source_df['兼務業務'].str.contains('緩和回診', na=False)
        dates = pd.to_datetime(
            source_df["日付"].map(
                lambda value: f"{year}-{month}-{str(value).split('/')[-1]}"
            ),
            format="%Y-%m-%d",
            errors="raise",
        )
        thursday = dates.dt.weekday == 3
        week_df.loc[palliative_care_mask, 'Name'] = (
            thursday.map({True: 'PM', False: 'AM'})[palliative_care_mask]
            + source_df.loc[palliative_care_mask, 'Name'].astype(str)
        )
        saturday_chemo = (
            (dates.dt.weekday == 5)
            & source_df['兼務業務'].str.contains('化療', na=False)
        )
        week_df.loc[saturday_chemo, 'Name'] = (
            'AM' + source_df.loc[saturday_chemo, 'Name'].astype(str)
        )
        chemo_rows = source_df.loc[saturday_chemo].copy()
        chemo_rows['専属業務'] = '化療'
        chemo_rows['Name'] = 'PM' + chemo_rows['Name'].astype(str)
        saturday_admission = (
            (dates.dt.weekday == 5)
            & ~dates.map(lambda value: jpholiday.is_holiday(value.date()))
            & (source_df['専属業務'] == '入退院センター')
        )
        week_df.loc[saturday_admission, 'Name'] = (
            'AM' + source_df.loc[saturday_admission, 'Name'].astype(str)
        )
        admission_rows = source_df.loc[saturday_admission].copy()
        admission_rows['専属業務'] = '調剤室'
        admission_rows['Name'] = 'PM' + admission_rows['Name'].astype(str)
        week_df = pd.concat([week_df, chemo_rows, admission_rows], ignore_index=True)
        
        #専属業務列に[休み、明け]を含むデータは除外する
        #監査があるスタッフを専属業務名に反映する
        audit_am_rows = source_df[source_df['兼務業務'].str.contains('監査_AM',na=False)].copy()
        audit_am_rows['専属業務'] = '監査_AM'
        week_df = pd.concat([week_df, audit_am_rows], ignore_index=True)
        audit_pm_rows = source_df[source_df['兼務業務'].str.contains('監査_PM',na=False)].copy()
        audit_pm_rows['専属業務'] = '監査_PM'
        week_df = pd.concat([week_df, audit_pm_rows], ignore_index=True)
        
        ###兼務業務名の反映
        #RI兼務業務があるスタッフは専属業務　RI行を追加作成、書き換えではなく、RI行を追加する
        ri_rows = source_df[source_df['兼務業務'].str.contains('RI',na=False)].copy()
        ri_rows['専属業務'] = 'RI'
        week_df = pd.concat([week_df, ri_rows], ignore_index=True)
        #心不全回診
        heart_team_rows = source_df[source_df['兼務業務'].str.contains('心不全回診',na=False)].copy()
        heart_team_rows['専属業務'] = '心不全回診'
        week_df = pd.concat([week_df, heart_team_rows], ignore_index=True)
        nst_rows = source_df[source_df['兼務業務'].str.contains('NST回診', na=False)].copy()
        nst_rows['専属業務'] = 'NST回診'
        week_df = pd.concat([week_df, nst_rows], ignore_index=True)
        ict_rows = source_df[source_df['兼務業務'].str.contains('ICT回診', na=False)].copy()
        ict_rows['専属業務'] = 'ICT回診'
        week_df = pd.concat([week_df, ict_rows], ignore_index=True)
        if 'マスター時間帯' in source_df.columns:
            for period in ('AM', 'PM'):
                master_rows = source_df[
                    source_df['マスター時間帯'].str.contains(period, na=False)
                ].copy()
                master_rows['専属業務'] = 'マスター管理'
                master_rows['Name'] = period + master_rows['Name'].astype(str)
                week_df = pd.concat([week_df, master_rows], ignore_index=True)
        yakushin_rows = source_df[source_df['兼務業務'].str.contains('薬審', na=False)].copy()
        yakushin_rows['専属業務'] = '薬審'
        week_df = pd.concat([week_df, yakushin_rows], ignore_index=True)
        #役職者会議
        exective_meeting_rows = source_df[source_df['兼務業務'].str.contains('役職者会議',na=False)].copy()
        exective_meeting_rows['専属業務'] = '役職者会議'
        week_df = pd.concat([week_df, exective_meeting_rows], ignore_index=True)
        #医薬品安全使用WG
        safety_wg_rows = source_df[source_df['兼務業務'].str.contains('医薬品安全使用WG',na=False)].copy()
        safety_wg_rows['専属業務'] = '医薬品安全使用WG'
        week_df = pd.concat([week_df, safety_wg_rows], ignore_index=True)
        
        #緩和回診の午後担当を「その他」表示用の行として追加
        palliative_care_rows = source_df.loc[palliative_care_mask].copy()
        palliative_care_rows['専属業務'] = '緩和回診'
        palliative_care_rows['兼務業務'] = '緩和回診'
        palliative_care_rows['Name'] = (
            thursday.map({True: 'AM', False: 'PM'})[palliative_care_mask]
            + palliative_care_rows['Name'].astype(str)
        )
        week_df = pd.concat([week_df, palliative_care_rows], ignore_index=True)
        
        
        #認知症せん妄ラウンド
        dementia_round_rows = source_df[source_df['兼務業務'].str.contains('認知症せん妄ラウンド',na=False)].copy()
        dementia_round_rows['専属業務'] = '認知症せん妄ラウンド'
        week_df = pd.concat([week_df, dementia_round_rows], ignore_index=True)
        #感染管理,AST
        infection_control_rows = source_df[source_df['兼務業務'].str.contains('感染管理,AST',na=False)].copy()
        infection_control_rows['専属業務'] = '感染管理,AST'
        week_df = pd.concat([week_df, infection_control_rows], ignore_index=True)
        #金曜日のポリファーマシー
        dates = pd.to_datetime(
        source_df["日付"].map(
                lambda value: f"{year}-{month}-{str(value).split('/')[-1]}"
            ),
            format="%Y-%m-%d",
            errors="coerce",
        )

        friday_rows = source_df[
            source_df["兼務業務"].str.contains("ポリファーマシー", na=False)
            & (dates.dt.weekday == 4)
        ].copy()
        friday_rows['専属業務'] = 'ポリファーマシーチーム'
        week_df = pd.concat([week_df, friday_rows], ignore_index=True)
        return week_df


    def _add_section_name(week_df:pd.DataFrame, section_name:str):
        """データフレームの特定の行にセクション名を追加する"""
        week_df.loc[section_name]=week_df.loc[section_name].apply(
            lambda cell:(
                f'{section_name}:\n{cell}'
                if pd.notna(cell) and str(cell).strip()
                else cell
            )
        )
        return week_df

    def change_porifa(df_result: pd.DataFrame, year: int,month: int):
        """ポリファーマシー（火曜日）を専任に変更する"""
        # ポリファーマシー（火曜日）は専任
        # 対象の火曜日日付を抽出,month,year情報から
        max_day = calendar.monthrange(year, month)[1]
        tuesday_days = [day for day in range(1,max_day+1) if pd.Timestamp(year=year, month=month, day=day).weekday() == 1]
        
        # 火曜日のポリファーマシーを専任にコピー
        for day in tuesday_days:
            df_result.loc[
                (df_result['日付'] == day) & (df_result['兼務業務'].str.contains('ポリファーマシー', na=False)),
                '専属業務'
            ] = 'ポリファーマシーチーム'
        return df_result


    def mk_weekly_shift_schedule(df_result: pd.DataFrame, year: int, month: int, weekly_dir: Path,staff_info=None):
        """週ごとのシフト結果をまとめたxlsxファイルを作成する。

        ``df_result`` の日付を表示用の ``MM/DD (曜日)`` 形式に整え、
        後続処理で週単位に集計・保存できる形に変換する。元のDataFrameを
        直接更新するため、この関数の呼び出し後は日付列が文字列になる点に注意する。
        """
        files = []
        
        # ポリファーマシー（火曜日）は専任にコピーする
        df_result = CalendarCreator.change_porifa(df_result, year, month)
        
        # 週ごとに分割して保存する前に、日付を日時型へ変換する。
        # 不正な値はエラーにせずNaTにすることで、他の日付の処理を継続する。
        #df_result['日付']には%dの情報しかないので、　yearとmonthを指定して、日付を作成する。
        #あとで日付型を日判定に使う場合もあるので、元の日時型を保持しておく場合はここでコピーしておく。
        df_result['日付_datetime'] = df_result['日付']
        df_result['日付'] = pd.to_datetime(df_result['日付'].apply(lambda x: f"{year}-{month}-{x}"), errors='coerce', format='%Y-%m-%d')
        # 日付から日本語の曜日名を作成し、Excelで見やすい表示用文字列を組み立てる。
        df_result['曜日'] = df_result['日付'].dt.weekday.map(
            {0: '月曜日', 1: '火曜日', 2: '水曜日', 3: '木曜日',
             4: '金曜日', 5: '土曜日', 6: '日曜日'}
        )
        df_result['日付'] = df_result['日付'].dt.strftime('%m/%d')
        df_result['日付_曜日'] = df_result['日付']
        df_result['日付_曜日'] = df_result['日付_曜日'] + ' (' + df_result['曜日'] + ')'
        
        # 名前を週間表示用の名前に変換する
        if staff_info is not None and '表示名' in staff_info.columns:
            display_names = staff_info['表示名'].to_dict()
            df_result['Name'] = df_result['Name'].map(
                lambda name: display_names.get(name)
                if pd.notna(display_names.get(name)) and str(display_names.get(name)).strip()
                else name
            )
        
        # 当直担当または当直相方の行だけ、表示名の末尾に二重丸を付加する。
        df_result['Name'] = df_result.apply(
            lambda row: (
                f"{row['Name']} ◎"
                if pd.notna(row['Name'])
                and str(row['Name']).strip()
                and any(role in str(row.get('当直', '')) for role in ('当直担当', '当直相方'))
                else row['Name']
            ),
            axis=1,
        )
        
        #「外来」部門は当直者だけ週間予定表に名前を記載するので、専属業務＝＝外来　& 当直担当または当直相方でない場合は名前を空にする。
        df_result.loc[
            (df_result['専属業務'] == '外来') &
            (~df_result['当直'].str.contains('当直担当|当直相方', na=False)),
            'Name'
        ] = ''

        # 専属業務が休みの場合は兼務業務も休みに統一し、週間表では休みのみが残るようにする。
        df_result['専属業務'] = df_result['専属業務'].fillna('').astype(str).str.strip()
        df_result['兼務業務'] = df_result.apply(
            lambda row: '休み' if str(row['専属業務']).strip() in {'休み', '休'} else row['兼務業務'],
            axis=1,
        )
        
        # 週ごとに分割して保存する　週間予定表の作成
        df_result['週番号']=df_result['日付'].apply(lambda x: pd.to_datetime(f"{year}-{month}-{x.split('/')[1]}").isocalendar()[1])
        for week_num, week_df in df_result.groupby('週番号'):
            week_df.drop(columns=['週番号'], inplace=True)
            # シフト表のクリーニングと整形
            week_df = CalendarCreator._cleanup_weekly_df(week_df = week_df,staff_info=staff_info,year=year,month=month)
            #書き出し用に整形する
            #　行：調剤室、監査AM、監査PM、化療AM、化療PM、1-2階、３階、４階、５階、入退院センター、RI、医療安全・感染管理、DI等
            # 列：日付（曜日）
            #　セル内：スタッフ名
            week_df = week_df.pivot_table(
                index='専属業務',
                columns='日付_曜日',
                values='Name',
                aggfunc=lambda x: '\n'.join(x)  # 同じ専属業務に複数のスタッフがいる場合は改行して表示,最後に編集したい
            )
            if '緩和回診(専任)' in week_df.index:
                week_df = CalendarCreator._add_section_name(week_df, '緩和回診(専任)')
            if 'ポリファーマシーチーム' in week_df.index:
                week_df = CalendarCreator._add_section_name(week_df, 'ポリファーマシーチーム')
            if '認知症せん妄ラウンド' in week_df.index:
                week_df = CalendarCreator._add_section_name(week_df, '認知症せん妄ラウンド')
            if '心不全回診' in week_df.index:
                week_df = CalendarCreator._add_section_name(week_df, '心不全回診')
            if 'NST回診' in week_df.index:
                week_df = CalendarCreator._add_section_name(week_df, 'NST回診')
            if 'ICT回診' in week_df.index:
                week_df = CalendarCreator._add_section_name(week_df, 'ICT回診')
            if '実習' in week_df.index:
                week_df = CalendarCreator._add_section_name(week_df, '実習')
            if 'マスター管理' in week_df.index:
                week_df = CalendarCreator._add_section_name(week_df, 'マスター管理')
            # 医薬品安全使用WGの行が存在する場合、セルの内容の先頭に「医薬品安全使用WG:」を付加する
            if '医薬品安全使用WG' in week_df.index:
                week_df = CalendarCreator._add_section_name(week_df, '医薬品安全使用WG')
            if '役職者会議' in week_df.index:
                week_df = CalendarCreator._add_section_name(week_df, '役職者会議')
            if '学会' in week_df.index:
                week_df = CalendarCreator._add_section_name(week_df, '学会')
            if '研修' in week_df.index:
                week_df = CalendarCreator._add_section_name(week_df, '研修')
            if '緩和回診' in week_df.index:
                week_df = CalendarCreator._add_section_name(week_df, '緩和回診')
            if '薬審' in week_df.index:
                week_df = CalendarCreator._add_section_name(week_df, '薬審')
            
            #その他」行を新規作成、『'緩和回診(専任)','ポリファーマシーチーム','認知症せん妄ラウンド','心不全回診','NST','実習','マスター管理','医薬品安全使用WG','役職者会議','学会','研修'}内のテキストは\nを挟んで全て並べて入れる
            #兼務業務のうち、「臨床薬剤課会議」は参加者多数のため表には表示しない、ohther_sectionsにも含めない
            other_sections = ['緩和回診','緩和回診(専任)','ポリファーマシーチーム','認知症せん妄ラウンド','心不全回診','NST回診','実習','マスター管理','医薬品安全使用WG','役職者会議','学会','研修','ICT回診','薬審']
            present_sections = [
                section for section in other_sections
                if section in week_df.index
            ]

            if present_sections:
                other_row = week_df.loc[present_sections].apply(
                    lambda cells: '\n\n'.join(
                        str(value)
                        for value in cells
                        if pd.notna(value) and str(value).strip()
                    ),
                    axis=0,
                )
            else:
                other_row = pd.Series('', index=week_df.columns)

            week_df.loc['その他'] = other_row

            #行の順番を固定
            #指定した行だけ出力されるので、「休み」や「明け」は出力されない
            week_df = week_df.reindex(
            ['調剤室','監査_AM','監査_PM','化療','1-2階','3階','4階','5階','入退院センター','RI','医療安全・感染管理','AST','DI','課長業務','課長','部長','感染管理,AST','外来','その他',
            ],
            )
            week_file = weekly_dir / f"Shift_week_{year}_{month:02d}_week{week_num}.xlsx"
            week_df.to_excel(week_file, index=True)
            files.append(week_file)
        return files
