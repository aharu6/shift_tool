#カレンダー作成用のスクリプト
#mainから処理を分岐
#日付を横長に展開したcsvファイルを保存
#変形・整形・保存処理を担う
from pathlib import Path
from typing import List, Union

import pandas as pd

from staff_name_matching import normalize_staff_name


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
            print(f"weekday{weekday}")
            input(f"enter to continue")
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