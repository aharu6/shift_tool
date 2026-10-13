# shift_tool

薬剤部向けの月次シフト作成ツールです。スタッフ条件、希望一覧、前月シフト、過去の当直実績を読み込み、OR-Tools CP-SAT で当直を割り当てます。現在の有効な最適化モデルは当直制約に限定されており、専属業務・兼務業務の自動配置と週次Excel出力は無効です。

## 実行方法

Python 3.12 以降、[uv](https://docs.astral.sh/uv/) を前提としています。リポジトリのルートで依存関係を同期して起動してください。

```bash
uv sync
uv run main.py
```

通常起動では以下の順で入力します。

1. 対象年を入力
2. 対象月を入力（1〜12）
3. スタッフ条件ファイルを選択
4. 前月シフトを選択（月初の連携に使用）
5. 直近12か月分の当直表を含むフォルダを選択
6. 希望リストファイルを選択
7. 必要に応じて前年12月/1月の履歴やスタッフ条件ファイルを選択

入力確認後、当直の最適化が実行されます。探索時間は 300 秒、相対ギャップ上限は 3% で設定されています。

テスト用の固定入力で起動する場合は、次のコマンドを使います。

```bash
uv run -m shift_tool.tests.main_test
```

このテスト用スクリプトは対象年月を2026年10月に固定し、入力ファイルに開発環境固有の絶対パスを指定しています。別の環境ではスクリプト内のパスを変更してください。

## 実際の処理フロー

`main.py` の `create_shift_schedule()` では、以下の順で処理を行います。

- 年月の入力
- `jpholiday` による祝日取得
- スタッフ条件ファイルの読み込み
- 前月シフトの読み込みと当直履歴の抽出
- 直近12か月分の当直回数の集計
- 前年12月/1月の連携用履歴の読み込み
- 希望リストの読み込みと名前の正規化
- `ShiftOptimizer` による当直変数・当直制約の初期化
- CP-SAT による最適化
- 結果のCSV出力

現在、`ShiftOptimizer.apply_all_constraints()` が有効化しているのは当直制約のみです。専属業務・兼務業務の変数作成と制約適用は無効化されています。

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

現在有効な当直モデルでは、主に以下の要件を `CP-SAT` に設定します。

- 毎日1組の当直ペアを割り当て、同じスタッフが同日に複数のペアへ入らない
- 当直不可・休職・当直希望などを考慮した割り当て
- 当直間隔、月間回数の上限、前月回数を踏まえた回数調整
- ペアの条件や会議・回診前後の当直回避
- 当直回数の偏りを抑える目的関数

制約の詳細は `optimizer/night_shift/oncall_constraints.py` を参照してください。専属業務・兼務業務の割り当ては現在の実行モデルでは行われません。

## 出力ファイル

最適化に成功すると `result/` 配下に以下を出力します。

- `Shift_YYYY_MM.csv`  
  スタッフ・日付ごとの明細。当直結果を記録する。専属業務・兼務業務は現在自動配置されず、既定値のまま
- `Shift_wide_YYYY_MM.csv`  
  専属業務欄を日付横持ちにした表。現在は専属業務が最適化されないため、完成した勤務表としては使用できない
- `Shift_cleaned_YYYY_MM.csv`  
  転記形式に整形した表。現在は専属業務が最適化されないため、完成した勤務表としては使用できない
- `oncall_shift_long_YYYY_MM.csv`  
  当直の縦長データ
- `oncall_shift_wide_YYYY_MM.csv`  
  当直の横長表と当直回数
また、実行ログは `logs/shift_run_YYYYMMDD_HHMMSS.txt` に書き出されます。

週次予定表を作成する `mk_weekly_shift_schedule()` の呼び出しは現在無効化されています。`result/weekly/` は作成されますが、週次Excelは出力されません。

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
- 生成物は `result/` 配下に保存されます。`Shift_cleaned_YYYY_MM.csv` などは専属業務が未配置の状態なので、完成した勤務表として次月連携に使う前に内容を確認してください。
- テスト用スクリプトは固定の年月・入力パスを使います。通常の対話起動は `uv run main.py` を使用してください。
