# 納品書→請求書 ワークフロー自動化

納品書PDFを画像として読み取り、Google Vision API + Gemini APIでOCR+構造化を行い、請求書PDFを自動生成するスクリプト。

## 処理フロー

```
[納品書PDF] → [画像変換] → [Google Vision API] → [OCR結果]
                                    ↓
                              [Gemini API] → [構造化データ]
                                    ↓
[会社マスター] ←──────────────────── [会社情報取得]
                                    ↓
[納品書DB] ←───────────────────────  [保存]
                                    ↓
[請求書PDF] ←──────────────────────  [PDF生成]
                                    ↓
[請求管理Sheet] ←──────────────────  [保存]
```

## 機能

1. **画像ベースのOCR**: PDFを画像として扱い、Google Vision APIで文字認識
2. **LLMによる構造化**: 抽出した文字列からGemini APIが項目ごとに分解・構造化（入金額も抽出）
3. **会社情報取得**: Google Sheetsの会社マスターから郵便番号・住所・事業部を取得
4. **納品書DB保存**: 納品書の内容をGoogle Sheetsに保存（入金額を含む）
5. **請求書PDF生成**: 日本式フォーマットの請求書PDFを自動生成
6. **請求管理記録**: 売上集計表に記録
7. **請求履歴管理**: 月次の請求履歴を管理（オプション）

## セットアップ

### 1. 依存パッケージのインストール

```bash
pip install -r requirements.txt
```

### 2. システム依存パッケージ（pdf2image用）

```bash
# Ubuntu/Debian
sudo apt-get install poppler-utils

# macOS
brew install poppler

# Arch Linux
sudo pacman -S poppler
```

### 3. 日本語フォント

プロジェクトには IPAex ゴシックフォント (`fonts/ipaexg.ttf`) が含まれているため、追加のインストールは不要です。

カスタムフォントを使用したい場合は、`.env` で `PDF_FONT_PATH` を設定してください。

### 4. Google Gemini API キーの取得

1. [Google AI Studio](https://aistudio.google.com/app/apikey) でAPIキーを生成
2. `.env` ファイルに設定

### 5. Google Cloud設定

**重要**: 組織ポリシーでサービスアカウントキーの作成がブロックされている場合は、**OAuth 2.0 認証**を使用してください。詳細は `OAUTH_SETUP.md` を参照。

#### オプション A: OAuth 2.0 認証（推奨）

1. [Google Cloud Console](https://console.cloud.google.com/)でプロジェクトを作成
2. Google Sheets API を有効化
3. OAuth クライアント ID を作成（デスクトップアプリ）
4. ダウンロードしたJSONを `credentials.json` としてプロジェクトルートに配置
5. `.env` で `USE_OAUTH=true` に設定
6. 使用するスプレッドシートに自分のGoogleアカウントの編集権限を付与

詳細: `OAUTH_SETUP.md` を参照

#### オプション B: サービスアカウント認証

1. [Google Cloud Console](https://console.cloud.google.com/)でプロジェクトを作成
2. Google Sheets API を有効化
3. サービスアカウントを作成し、JSONキーをダウンロード
4. ダウンロードしたJSONを `credentials.json` としてプロジェクトルートに配置
5. `.env` で `USE_OAUTH=false` に設定（またはオプションを省略）
6. 使用するスプレッドシートにサービスアカウントのメールアドレスを共有設定で追加

### 6. 環境変数の設定

```bash
cp .env.example .env
```

`.env` を編集:

```env
# Gemini API（必須）
GEMINI_API_KEY=your_gemini_api_key

# Google Sheets ID（URLの /d/XXXXX/edit の XXXXX 部分）
COMPANY_MASTER_SPREADSHEET_ID=your_spreadsheet_id
DELIVERY_DB_SPREADSHEET_ID=your_spreadsheet_id
BILLING_SPREADSHEET_ID=your_spreadsheet_id

# 自社情報
OWN_REGISTRATION_NUMBER=T1234567890123
OWN_COMPANY_NAME=株式会社サンプル
...
```

### 7. スプレッドシートの準備

#### 会社マスター（COMPANY_MASTER）
URL: https://docs.google.com/spreadsheets/d/1l3GPdd2BoyPC_PIe5yktocAHJ30C1f2YpfCSOw6Tj9U/edit

| 会社名 | 事業部 | 郵便番号 | 住所 | ビル名 |
|--------|--------|----------|------|--------|
| 株式会社ABC | 営業部 | 100-0001 | 東京都... | ABCビル3F |

#### 納品書DB（DELIVERY_DB）

| 日付 | 会社名 | 伝票番号 | 商品コード | 品名 | 数量 | 単価 | 金額 | 小計 | 消費税 | 合計 | 入金額 |
|------|--------|----------|------------|------|------|------|------|------|--------|------|--------|

#### 売上集計表（BILLING）
URL: https://docs.google.com/spreadsheets/d/1eBmP3GWRNE2QZ6I8e1n2tjR7J_pHsB9L/edit

| 相手方 | 先月残高 | 先月発生 | 先月消費税 | 先月消滅 | 残高 | 発生 | 消費税 | 消滅 | 残高 | 後半合計 |
|--------|----------|----------|------------|----------|------|------|--------|------|------|----------|

#### 請求履歴管理（BILLING_HISTORY）- オプション

| 年月 | 会社名 | 前回御請求額 | 御入金額 | 繰越残高 | 売上額 | 消費税額 | 今回御請求額 | 更新日時 |
|------|--------|-------------|----------|----------|--------|----------|-------------|----------|

## 使用方法

```bash
# inputディレクトリ内のPDFを全て処理
python -m src.main

# 特定のPDFを処理
python -m src.main input/delivery_note.pdf

# 複数のPDFを処理
python -m src.main input/note1.pdf input/note2.pdf

# DRY RUN（Google Sheetsへの書き込みをスキップ、PDF生成のみ）
python -m src.main --dry-run
```

## ディレクトリ構造

```
advan-workflow/
├── credentials.json      # Google API認証ファイル（要作成）
├── .env                  # 環境変数（要作成）
├── .env.example          # 環境変数サンプル
├── requirements.txt      # 依存パッケージ
├── input/                # 納品書PDF配置ディレクトリ
├── output/               # 生成された請求書PDF出力先
├── src/
│   ├── __init__.py
│   ├── config.py         # 設定
│   ├── pdf_extractor.py  # データ構造定義
│   ├── llm_extractor.py  # LLM抽出モジュール（Google Vision + Gemini API）
│   ├── sheets_client.py  # Google Sheets連携
│   ├── invoice_generator.py  # 請求書PDF生成
│   └── main.py           # メインスクリプト
└── README.md
```

## LLM抽出の仕組み

### 1. PDF → 画像変換

```python
from pdf2image import convert_from_path
images = convert_from_path(pdf_path, dpi=150)
```

### 2. Google Vision APIでOCR

```python
vision_image = vision.Image(content=content)
response = vision_client.document_text_detection(image=vision_image)
text = response.full_text_annotation.text
```

### 3. Gemini APIで構造化

```python
response = gemini_client.models.generate_content(
    model="gemini-2.5-flash",
    contents=f"{EXTRACTION_PROMPT}\n\n{text}"
)
```

### 4. プロンプトで構造化を指示

Gemini APIに以下の項目をJSON形式で抽出させる:
- date: 日付
- company_name: 会社名
- slip_number: 伝票番号
- subtotal: 小計
- tax: 消費税
- total: 合計
- payment_received: 御入金額（追加）
- items: 明細行（商品コード、品名、数量、単価、金額）

### 5. JSONをパースしてデータ構造に変換

```python
extracted = json.loads(response_text)
delivery_note = DeliveryNote(
    date=extracted["date"],
    company_name=extracted["company_name"],
    ...
)
```

## 注意事項

- Google Vision APIとGemini APIの利用には料金が発生します
- 画像解像度は150dpiに設定（APIコスト最適化のため）
- 複数ページPDFは各ページを個別に処理し、明細を結合
- 日本語フォント（IPAexゴシック）はプロジェクトに含まれています

## コスト見積もり

- Google Vision API: ドキュメントテキスト検出 $1.50/1,000ユニット（最初の1,000ユニット/月は無料）
- Gemini 2.5 Flash: 無料枠あり（制限内であれば無料）
- 1枚の納品書PDF: 概算 約$0.002〜0.01（Vision API主体）
