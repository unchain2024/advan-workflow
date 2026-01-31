# 本番環境セットアップガイド

## 前提条件

- Google Cloud Consoleでプロジェクトを作成済み
- Google Sheets API、Google Drive API、Cloud Vision APIを有効化済み
- OAuth 2.0クライアントID（デスクトップアプリタイプ）を作成済み

## 1. ローカル環境での事前準備

### 1.1 OAuth認証トークンの生成

本番環境にデプロイする前に、ローカル環境でOAuth認証を完了させます。

```bash
# プロジェクトルートで実行
cd /path/to/advan-workflow

# 仮想環境をアクティベート
source venv/bin/activate

# OAuth認証を実行（ブラウザが開きます）
python oauth_setup.py
```

認証が成功すると、`token.pickle` ファイルが生成されます。

### 1.2 必要なファイルの確認

以下のファイルが揃っていることを確認してください：

```
advan-workflow/
├── credentials.json      # OAuth 2.0クライアントID（デスクトップアプリ）
├── token.pickle         # 生成された認証トークン（リフレッシュトークン含む）
├── company_config.json  # 自社情報設定
└── .env                # 環境変数設定
```

## 2. 本番環境へのデプロイ

### 2.1 環境変数の設定

本番環境で以下の環境変数を設定してください：

```bash
# 本番環境フラグ
ENVIRONMENT=production

# OAuth認証を使用
USE_OAUTH=true

# スプレッドシートID
COMPANY_MASTER_SPREADSHEET_ID=your_company_master_id
BILLING_SPREADSHEET_ID=your_billing_id
DELIVERY_DB_SPREADSHEET_ID=your_delivery_db_id

# API Keys
GEMINI_API_KEY=your_gemini_api_key
```

### 2.2 認証ファイルのデプロイ

**方法A: ファイルとしてデプロイ（推奨）**

`credentials.json` と `token.pickle` をアプリケーションルートに配置します。

**Docker使用例:**
```dockerfile
FROM python:3.11-slim

WORKDIR /app

# 認証ファイルをコピー（.dockerignoreで除外しないこと）
COPY credentials.json .
COPY token.pickle .
COPY company_config.json .

# アプリケーションファイル
COPY requirements.txt .
COPY src/ src/
COPY backend-api/ backend-api/
COPY frontend-react/dist/ frontend-react/dist/

RUN pip install -r requirements.txt

# 環境変数設定
ENV ENVIRONMENT=production
ENV USE_OAUTH=true

EXPOSE 8000

CMD ["uvicorn", "backend-api.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

**方法B: 環境変数としてデプロイ**

セキュリティ上の理由でファイルを含めたくない場合、環境変数として設定できます（追加実装が必要）。

### 2.3 デプロイ先での動作確認

```bash
# バックエンドサーバー起動
cd backend-api
ENVIRONMENT=production USE_OAUTH=true uvicorn main:app --host 0.0.0.0 --port 8000
```

初回起動時、既存の`token.pickle`からリフレッシュトークンを使って自動的に認証が更新されます。

## 3. トークンの更新

`token.pickle`に含まれるリフレッシュトークンは期限がありません（ユーザーが取り消さない限り）。アクセストークンは自動的に更新されます。

## 4. トラブルシューティング

### エラー: "OAuth認証が必要です"

**原因:** `token.pickle` が存在しないか無効です。

**対処:**
1. ローカル環境で `python oauth_setup.py` を実行
2. 生成された `token.pickle` を本番環境にデプロイ

### エラー: "OAuth認証トークンの更新に失敗しました"

**原因:** リフレッシュトークンが無効化されています。

**対処:**
1. Google Cloud Consoleで認証情報を確認
2. ローカル環境で `token.pickle` を削除
3. `python oauth_setup.py` を再実行
4. 新しい `token.pickle` を本番環境にデプロイ

## 5. セキュリティの注意事項

⚠️ **重要:**
- `credentials.json` と `token.pickle` は機密情報です
- Gitにコミットしないでください（`.gitignore`に追加済み）
- 本番環境では環境変数やシークレット管理サービスの使用を検討してください
- token.pickleには長期的なリフレッシュトークンが含まれるため、厳重に管理してください

## 6. 代替案: サービスアカウント認証

より本番環境に適したサービスアカウント認証への移行も検討できます：

1. Google Cloud Consoleでサービスアカウントを作成
2. JSONキーをダウンロード
3. スプレッドシートをサービスアカウントのメールアドレスと共有
4. `USE_OAUTH=false` で起動（デフォルト）

サービスアカウント認証の方がインタラクティブな認証が不要で、本番環境に適しています。
