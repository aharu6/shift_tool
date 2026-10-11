# shift_tool

薬剤部向けの月次勤務表を自動生成するツールです。スタッフ条件と希望一覧、前月・前年の勤務履歴、当直実績を読み込み、OR-Tools CP-SAT で専属業務・兼務業務・当直を最適化し、週次の予定表もExcelとして出力します。

## 実行方法

Python 3.12 以降、[uv](https://docs.astral.sh/uv/) を前提としています。リポジトリのルートで依存関係を同期して起動してください。

```bash
uv sync
uv run main.py
```

起動すると以下の順で対話形式の入力が進みます。

1. 対象年を入力
2. 対象月を入力（1〜12）
3. スタッフ条件ファイルを選択
4. 前月シフトを選択（月初の連携に使用）
5. 直近12か月分の当直表を含むフォルダを選択
6. 希望リストファイルを選択
7. 必要に応じて前年12月/1月の履歴やスタッフ条件ファイルを選択

入力確認後、最適化が実行されます。探索時間は 300 秒、相対ギャップ上限は 3% で設定されています。

## 実際の処理フロー

`main.py` の `create_shift_schedule()` では、以下の順で処理を行います。

- 年月の入力
- `jpholiday` による祝日取得
- スタッフ条件ファイルの読み込み
- 前月シフトの読み込みと当直履歴の抽出
- 直近12か月分の当直回数の集計
- 前年12月/1月の連携用履歴の読み込み
- 希望リストの読み込みと名前の正規化
- `ShiftOptimizer` による制約・変数の初期化
- CP-SAT による最適化
- 結果のCSV出力
- 週次予定表のExcel出力

実行ログは `logs/shift_run_YYYYMMDD_HHMMSS.txt` に出力されます。

## 入力ファイル

### 1. スタッフ条件ファイル

- ファイル選択ダイアログで Excel を選択
- `member_list` シートを使う
- `skiprows=1` で先頭行を読み飛ばす
- `Name` 列と各スタッフの属性（Floor / Floor2 / Floor3 など）を正規化して利用する

### 2. 希望リスト

- Excel ファイルを選択
- `skiprows=[1]` で2行目を読み飛ばす
- 最初の列を `Name` に置き換える
- 1〜31 日までの列に絞って扱う
- 休み希望・当直不可・出勤希望・会議希望などを読み込む

### 3. 前月シフト

- 前月のシフト表 Excel を手動で選択
- `_load_previous_month_shift()` が読み込み、`-1`〜`-8` の過去8日間を変換して取り込む
- これにより、月初の当直可否・休み回避の制約に前月末の勤務が反映される

### 4. 直近12か月分の当直表フォルダ

- 当直表の Excel をまとめたフォルダを選択
- `*.xlsx` を自動取得して、スタッフごとの過去当直回数を集計する
- `result/oncall_shift_wide_{year}_{month}.csv` を参照するだけでなく、直近12か月分の履歴も利用する

### 5. 年末年始の履歴

- `result/Shift_cleaned_{year-1}_12.csv` または Excel
- `result/Shift_cleaned_{year}_01.csv` または Excel
- 12月30日・12月31日・1月1日〜3日の勤務継続や休職判定に利用する
- 履歴がない場合は適切に除外またはスキップする

## 主な制約と最適化内容

このツールのモデルは、以下のような要件を `CP-SAT` に落とし込みます。

- 専属業務の配置人数と候補条件
- 兼務業務の割り当て
- 当直ペアの割り当てと月間回数制限
- 休み・慶弔休暇・育休・研修・学会の希望反映
- 当直の前後日制約（明けの扱い、連続勤務の抑制）
- 年末年始・祝日の扱い
- 連続勤務日数や当直回数の偏りを抑える目的関数

実際のコードでは、`optimizer/` 配下の制約と `requests/` 配下の条件を読み込み、`apply_all_constraints()` で制約を入力してから `solver.Solve()` を実行します。

## 出力ファイル

最適化に成功すると `result/` 配下に以下を出力します。

- `Shift_YYYY_MM.csv`  
  スタッフ・日付ごとの明細。専属業務、兼務業務、当直が記録される
- `Shift_wide_YYYY_MM.csv`  
  専属業務を日付横持ちにした表。月初の引き継ぎでも使用する
- `Shift_cleaned_YYYY_MM.csv`  
  勤務表へ転記するために整形した専属業務表
- `oncall_shift_long_YYYY_MM.csv`  
  当直の縦長データ
- `oncall_shift_wide_YYYY_MM.csv`  
  当直の横長表と当直回数
- `result/weekly/Shift_week_YYYY_MM_weekN.xlsx`  
  週単位にまとめた予定表

また、実行ログは `logs/shift_run_YYYYMMDD_HHMMSS.txt` に書き出されます。

## 週次予定表の整形について

`mk_weekly_shift_schedule()` では、最終的な週次Excelを作る前に以下を行います。

- 日付を `MM/DD (曜日)` 形式に整形
- 表示名の置換
- 当直担当/相方には `◎` を付与
- 外来担当者の通常勤務名は非当直時に空欄化
- 専属業務が `休み` の場合、兼務業務も `休み` に揃える
- 週単位で `pivot_table` を作成して Excel へ保存

このため、週表では「専属業務が休みでも兼務業務が残らない」ように整理されています。

## フォルダ構成

```text
shift_tool/
├── main.py
├── optimizer/
│   ├── __init__.py
│   ├── assignment_constraints.py
│   ├── base_constraint.py
│   └── shift_optimizer.py
├── config/
│   ├── sections.py
│   ├── concurrent_sections.py
│   └── ...
├── requests/
│   ├── mk_requests.py
│   └── meeting_constraints.py
├── result/
│   ├── Shift_YYYY_MM.csv
│   ├── Shift_cleaned_YYYY_MM.csv
│   └── weekly/
├── logs/
├── pyproject.toml
├── README.md
└── ...
```

## 備考

- 実行時にファイル選択ダイアログが出るため、対話型で処理を進める前提です。
- 生成物は `result/` 配下に保存されるため、次月の連携ファイルとしてそのまま利用できます。
- 変更内容が多いため、`main.py` の変数名や処理順が README とズレることがあるので、最新の実装に合わせて上書き更新する前提で扱ってください。
