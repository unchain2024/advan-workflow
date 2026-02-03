# 本番環境デプロイメントガイド

## アーキテクチャ

- **フロントエンド**: Vercel（推奨）
- **バックエンド**: Railway / Render / Google Cloud Run（推奨）
- **認証**: サービスアカウント（USE_OAUTH=false）

---

## 1. 環境変数の設定

### バックエンド環境変数

本番環境で以下の環境変数を設定してください:

```bash
# Claude API（必須）
ANTHROPIC_API_KEY=sk-ant-api03-xxxxx
LLM_MODEL=claude-sonnet-4-20250514

# Gemini API（必須）
GEMINI_API_KEY=AIzaSyDxxxxx
GEMINI_MODEL=gemini-2.5-flash

# Google Sheets 認証
USE_OAUTH=false

# Google Sheets ID
COMPANY_MASTER_SPREADSHEET_ID=1l3GPdd2BoyPC_PIe5yktocAHJ30C1f2YpfCSOw6Tj9U
COMPANY_MASTER_SHEET_NAME=マスター
BILLING_SPREADSHEET_ID=1M1EAVui-og3jfCAqdn412gU_iSg9yV0iJasMPz0a_8E
BILLING_SHEET_NAME=1月-12月集計

# 仕入れ管理スプレッドシート
PURCHASE_SPREADSHEET_ID=1aTmDyQm8TEdJNZu5uimMwPeJVPwTZCH0WTvQHVoTwRQ
PURCHASE_SHEET_NAME=1月-12月集計

# 締め日マスタースプレッドシート
PURCHASE_TERMS_SPREADSHEET_ID=1jaRicb7xLD5vD0cNqkHTYzRcu20rv19MT5csqb4dSng
PURCHASE_TERMS_SHEET_NAME=国内仕入先支払条件
```

### サービスアカウント認証情報

#### 方法1: Base64エンコード（推奨）

```bash
# ローカルでBase64エンコード
base64 -w 0 credentials.json

# 出力された文字列を環境変数に設定
GOOGLE_CREDENTIALS_BASE64=eyJ0eXBlIjoic2VydmljZV9hY2NvdW50IiwicHJvamVjdF9pZCI6ImFkdmFuLTQ4NjIxOCIsInByaXZhdGVfa2V5X2lkIjoiYTQyODMxYz...
```

#### 方法2: JSONファイルとして配置（非推奨）

デプロイ先のファイルシステムに `credentials.json` を配置する場合:
- Railway: Secret Files機能を使用
- Render: 環境変数としてJSON全体を設定し、起動時にファイルに書き出す

---

## 2. フロントエンドのデプロイ（Vercel）

### 2.1 プロジェクト設定

```bash
cd frontend-react
```

### 2.2 Vercelにデプロイ

```bash
# Vercel CLIをインストール（初回のみ）
npm install -g vercel

# デプロイ
vercel --prod
```

### 2.3 環境変数設定（Vercel Dashboard）

Vercel Dashboardで以下を設定:

```bash
VITE_API_URL=https://your-backend-url.railway.app
```

### 2.4 ビルド設定（vercel.json）

プロジェクトルートに以下を作成:

```json
{
  "buildCommand": "cd frontend-react && npm run build",
  "outputDirectory": "frontend-react/dist",
  "devCommand": "cd frontend-react && npm run dev",
  "installCommand": "cd frontend-react && npm install"
}
```

---

## 3. バックエンドのデプロイ

### オプションA: Railway（推奨）

#### 3.1 Railway プロジェクト作成

1. https://railway.app でプロジェクト作成
2. GitHub リポジトリを接続
3. ルートディレクトリを `backend-api` に設定

#### 3.2 環境変数設定

Railway Dashboardで上記のすべての環境変数を設定

#### 3.3 ビルド設定

```bash
# Start Command
uvicorn main:app --host 0.0.0.0 --port $PORT

# Build Command（必要に応じて）
pip install -r ../requirements.txt
```

#### 3.4 Pythonバージョン指定

`runtime.txt` を作成:

```
python-3.11
```

---

### オプションB: Render

#### 3.1 Render プロジェクト作成

1. https://render.com でWeb Service作成
2. GitHub リポジトリを接続

#### 3.2 ビルド設定

```bash
# Build Command
pip install -r requirements.txt

# Start Command
cd backend-api && uvicorn main:app --host 0.0.0.0 --port $PORT
```

#### 3.3 環境変数設定

Render Dashboardで上記のすべての環境変数を設定

---

### オプションC: Google Cloud Run

#### 3.1 Dockerファイル作成

プロジェクトルートに `Dockerfile` を作成:

```dockerfile
FROM python:3.11-slim

WORKDIR /app

# 依存関係をインストール
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# アプリケーションコードをコピー
COPY . .

# フォントファイルをコピー
COPY fonts /app/fonts

# ポート設定
ENV PORT=8080

# アプリケーション起動
CMD cd backend-api && uvicorn main:app --host 0.0.0.0 --port $PORT
```

#### 3.2 デプロイ

```bash
# Google Cloud SDK認証
gcloud auth login

# プロジェクト設定
gcloud config set project advan-486218

# Cloud Runにデプロイ
gcloud run deploy advan-workflow \
  --source . \
  --region asia-northeast1 \
  --allow-unauthenticated \
  --set-env-vars ANTHROPIC_API_KEY=$ANTHROPIC_API_KEY,GEMINI_API_KEY=$GEMINI_API_KEY,...
```

---

## 4. CORS設定

バックエンドの `main.py` でCORSを設定済みですが、本番URLを確認:

```python
# backend-api/main.py
from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "https://your-vercel-app.vercel.app",  # ← 本番URLを追加
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

---

## 5. フロントエンドのAPI URL設定

### 開発環境と本番環境の切り替え

`frontend-react/src/api/client.ts` を更新:

```typescript
const API_BASE_URL = import.meta.env.VITE_API_URL || '/api';
```

- **開発環境**: `/api` → Viteプロキシ経由でlocalhost:8000
- **本番環境**: `https://your-backend-url.railway.app/api`

### Vercel環境変数

```bash
VITE_API_URL=https://your-backend-url.railway.app
```

---

## 6. セキュリティチェックリスト

### 必須

- [ ] `.env` ファイルをコミットしていない（`.gitignore`で除外）
- [ ] `credentials.json` をコミットしていない
- [ ] `advan-486218-a42831c08eca.json` をコミットしていない
- [ ] 本番環境でHTTPSを使用している
- [ ] APIキーを環境変数で管理している

### 推奨

- [ ] CORS設定で本番URLのみ許可
- [ ] レート制限の設定（必要に応じて）
- [ ] エラーログの監視（Sentry等）
- [ ] バックエンドのヘルスチェックエンドポイント設定

---

## 7. デプロイ後の確認

### バックエンド

```bash
# ヘルスチェック
curl https://your-backend-url.railway.app/

# APIテスト
curl https://your-backend-url.railway.app/api/config
```

### フロントエンド

1. https://your-vercel-app.vercel.app にアクセス
2. PDFアップロード機能をテスト
3. スプレッドシート保存機能をテスト

---

## 8. トラブルシューティング

### エラー: 403 SERVICE_DISABLED

- Google Cloud Console でAPIが有効化されているか確認
- プロジェクトID（advan-486218）が正しいか確認
- 請求先アカウントがリンクされているか確認

### エラー: 400 This operation is not supported

- スプレッドシートIDが正しいか確認（Excel形式でないか）
- サービスアカウントが共有されているか確認
- 権限が「編集者」になっているか確認

### エラー: 500 Internal Server Error

- バックエンドのログを確認
- 環境変数が正しく設定されているか確認
- `GOOGLE_CREDENTIALS_BASE64` が正しくエンコードされているか確認

---

## 9. コスト見積もり

### 無料枠内で運用可能

- **Vercel**: Hobby（無料） - 月100GB帯域幅
- **Railway**: $5/月の無料クレジット
- **Render**: Free tier（スリープあり）
- **Google Cloud**: Cloud Vision API - 月1000リクエストまで無料
- **Claude API**: 使用量に応じて課金
- **Gemini API**: 無料枠あり

---

## 10. 次のステップ

1. バックエンドをデプロイ（Railway/Render/Cloud Run）
2. 環境変数を設定
3. サービスアカウント認証情報を設定（Base64推奨）
4. フロントエンドをデプロイ（Vercel）
5. バックエンドURLをフロントエンドの環境変数に設定
6. 動作確認

何か質問があれば教えてください！
