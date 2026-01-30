# Streamlit Community Cloud デプロイ手順

## 1. GitHubにコードをプッシュ

```bash
git add .
git commit -m "Initial commit"
git push origin master
```

## 2. Streamlit Community Cloudにサインアップ

1. https://streamlit.io/cloud にアクセス
2. GitHubアカウントでサインイン
3. "New app" をクリック

## 3. アプリの設定

- **Repository**: `unchain2024/advan-workflow`
- **Branch**: `master`
- **Main file path**: `app.py`

## 4. 環境変数（Secrets）の設定

Streamlit Cloudのアプリ設定画面で "Secrets" セクションに以下を追加:

```toml
# Claude API（必須）
ANTHROPIC_API_KEY = "your_anthropic_api_key"
LLM_MODEL = "claude-sonnet-4-20250514"

# Google Sheets 認証
USE_OAUTH = "false"  # StreamlitではOAuthが使えないのでサービスアカウントを使用

# Google Sheets ID
COMPANY_MASTER_SPREADSHEET_ID = "your_company_master_spreadsheet_id"
COMPANY_MASTER_SHEET_NAME = "マスター"
DELIVERY_DB_SPREADSHEET_ID = "your_delivery_db_spreadsheet_id"
DELIVERY_DB_SHEET_NAME = "納品書DB"
BILLING_SPREADSHEET_ID = "your_billing_spreadsheet_id"
BILLING_SHEET_NAME = "請求管理"
BILLING_HISTORY_SPREADSHEET_ID = "your_billing_history_spreadsheet_id"
BILLING_HISTORY_SHEET_NAME = "請求履歴"

# 自社情報
OWN_REGISTRATION_NUMBER = "T1234567890123"
OWN_COMPANY_NAME = "株式会社サンプル"
OWN_POSTAL_CODE = "123-4567"
OWN_ADDRESS = "東京都千代田区〇〇1-2-3"
OWN_PHONE = "03-1234-5678"
OWN_BANK_INFO = "〇〇銀行 △△支店 普通 1234567"

# PDF設定（Streamlit Cloudの場合、Noto CJKフォントのパス）
PDF_FONT_PATH = "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"

# Google Service Account（credentials.jsonの内容をここに貼り付け）
[gcp_service_account]
type = "service_account"
project_id = "your-project-id"
private_key_id = "your-private-key-id"
private_key = "-----BEGIN PRIVATE KEY-----\n...\n-----END PRIVATE KEY-----\n"
client_email = "your-service-account@your-project.iam.gserviceaccount.com"
client_id = "your-client-id"
auth_uri = "https://accounts.google.com/o/oauth2/auth"
token_uri = "https://oauth2.googleapis.com/token"
auth_provider_x509_cert_url = "https://www.googleapis.com/oauth2/v1/certs"
client_x509_cert_url = "https://www.googleapis.com/robot/v1/metadata/x509/..."
```

## 5. サービスアカウントの準備

StreamlitではOAuth認証が使えないため、Google Cloud Consoleでサービスアカウントを作成:

1. Google Cloud Console → IAM → サービスアカウント
2. 新しいサービスアカウントを作成
3. JSON形式のキーをダウンロード
4. その内容を上記の `[gcp_service_account]` セクションにコピー

## 6. Google Sheetsの共有

サービスアカウントのメールアドレス（`xxx@xxx.iam.gserviceaccount.com`）に、使用するすべてのGoogle Sheetsへの編集権限を付与してください。

## 7. デプロイ

"Deploy!" ボタンをクリックすると、自動的にデプロイが開始されます。

## 注意事項

- 無料プランでは:
  - 1アプリあたり1GB RAM
  - CPU共有
  - 月間750時間まで（複数アプリ合計）
- 大きなPDFファイルの処理には時間がかかる場合があります
- 日本語フォントが見つからない場合は、PDF生成がエラーになる可能性があります（フォント設定の調整が必要）
