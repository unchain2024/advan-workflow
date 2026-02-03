# Render.com デプロイメントガイド

このプロジェクトは **Render.com** に統合デプロイ（バックエンド + フロントエンド）されます。

## アーキテクチャ

- **プラットフォーム**: Render.com（Web Service）
- **構成**: FastAPI（バックエンド）がReactアプリ（フロントエンド）を配信
- **認証**: サービスアカウント（USE_OAUTH=false）
- **リージョン**: Oregon または Singapore

---

## 1. デプロイ準備

### 1.1 サービスアカウント認証情報をBase64エンコード

```bash
# ローカルでcredentials.jsonをBase64エンコード
base64 -w 0 credentials.json
```

出力された文字列をコピーしておきます（後で環境変数に設定）。

### 1.2 スプレッドシートIDを確認

`.env`ファイルから以下のIDをコピー:
- `COMPANY_MASTER_SPREADSHEET_ID`
- `BILLING_SPREADSHEET_ID`
- `PURCHASE_SPREADSHEET_ID`
- `PURCHASE_TERMS_SPREADSHEET_ID`

---

## 2. Render.comでプロジェクト作成

### 2.1 GitHubリポジトリを接続

1. https://dashboard.render.com/ にログイン
2. **New +** → **Web Service** をクリック
3. GitHubリポジトリ `unchain2024/advan-workflow` を選択
4. **Connect** をクリック

### 2.2 自動設定の確認

`render.yaml` が検出され、以下が自動設定されます:
- **Name**: advan-workflow
- **Environment**: Python
- **Region**: Oregon
- **Build Command**: `pip install -r requirements.txt && cd frontend-react && npm ci && npm run build`
- **Start Command**: `cd backend-api && python -m uvicorn main:app --host 0.0.0.0 --port $PORT`

---

## 3. 環境変数の設定

Render Dashboard で以下の環境変数を設定してください（**Deploy** ボタンを押す前に）:

### 必須の環境変数

| Key | Value | 説明 |
|-----|-------|------|
| `GOOGLE_CREDENTIALS_BASE64` | `eyJ0eXBlIjoic2VydmljZV9hY2NvdW50...` | Base64エンコードしたcredentials.json |
| `ANTHROPIC_API_KEY` | `sk-ant-api03-xxxxx` | Claude API キー |
| `GEMINI_API_KEY` | `AIzaSyDxxxxx` | Gemini API キー |
| `COMPANY_MASTER_SPREADSHEET_ID` | `1l3GPdd2BoyPC_PIe5yktocAHJ30C1f2YpfCSOw6Tj9U` | 会社情報マスターID |
| `BILLING_SPREADSHEET_ID` | `1M1EAVui-og3jfCAqdn412gU_iSg9yV0iJasMPz0a_8E` | 売上集計表ID |
| `PURCHASE_SPREADSHEET_ID` | `1aTmDyQm8TEdJNZu5uimMwPeJVPwTZCH0WTvQHVoTwRQ` | 仕入れ管理表ID |
| `PURCHASE_TERMS_SPREADSHEET_ID` | `1jaRicb7xLD5vD0cNqkHTYzRcu20rv19MT5csqb4dSng` | 締め日マスターID |

その他の環境変数（デフォルト値があるので省略可）:
- `LLM_MODEL`: `claude-sonnet-4-20250514`（デフォルト）
- `GEMINI_MODEL`: `gemini-2.5-flash`（デフォルト）
- `COMPANY_MASTER_SHEET_NAME`: `マスター`（デフォルト）
- `BILLING_SHEET_NAME`: `1月-12月集計`（デフォルト）
- `PURCHASE_SHEET_NAME`: `1月-12月集計`（デフォルト）
- `PURCHASE_TERMS_SHEET_NAME`: `国内仕入先支払条件`（デフォルト）

---

## 4. デプロイ実行

1. 環境変数の設定が完了したら **Create Web Service** をクリック
2. ビルドが自動的に開始されます（5-10分程度）
3. デプロイ完了後、URLが表示されます（例: `https://advan-workflow.onrender.com`）

---

## 5. デプロイ後の確認

### 5.1 ヘルスチェック

```bash
curl https://advan-workflow.onrender.com/health
# 期待される応答: {"status":"ok"}
```

### 5.2 フロントエンドアクセス

ブラウザで `https://advan-workflow.onrender.com` を開く

### 5.3 動作確認

1. 売上計上ページでPDFをアップロード
2. 仕入れページでPDFをアップロード
3. スプレッドシートに正しく記録されるか確認

---

## 6. 自動デプロイ設定

GitHubの`main`ブランチにプッシュすると、Renderが自動的に再デプロイします。

**設定の確認**:
- Dashboard → Settings → Build & Deploy
- **Auto-Deploy**: Yes（デフォルト）

---

## 7. トラブルシューティング

### エラー: Build failed

**原因**: Pythonまたはnpmの依存関係のインストール失敗

**解決方法**:
1. Render Dashboard → Logs を確認
2. `requirements.txt` と `frontend-react/package.json` を確認
3. ローカルで `pip install -r requirements.txt` と `npm ci` を実行して問題がないか確認

### エラー: 500 Internal Server Error

**原因**: 環境変数が正しく設定されていない

**解決方法**:
1. Dashboard → Environment で全ての必須環境変数が設定されているか確認
2. `GOOGLE_CREDENTIALS_BASE64` が正しくエンコードされているか確認
   ```bash
   # 再エンコード
   base64 -w 0 credentials.json
   ```
3. Renderを再デプロイ（Manual Deploy → Deploy latest commit）

### エラー: 403 SERVICE_DISABLED

**原因**: Google Cloud APIが有効化されていない

**解決方法**:
1. https://console.cloud.google.com/ でプロジェクト `advan-486218` を選択
2. 以下のAPIを有効化:
   - Cloud Vision API
   - Google Sheets API
   - Google Drive API
3. 請求先アカウントがリンクされているか確認

### エラー: フロントエンドが表示されない

**原因**: フロントエンドのビルドに失敗

**解決方法**:
1. Render Logs で `npm run build` の出力を確認
2. ローカルで `cd frontend-react && npm run build` を実行して問題がないか確認
3. `frontend-react/dist` ディレクトリが生成されることを確認

---

## 8. パフォーマンス最適化

### 8.1 リージョン変更

アジアからのアクセスが多い場合:
- Dashboard → Settings → Region を **Singapore** に変更

### 8.2 有料プランへのアップグレード

無料プランの制限:
- 15分間アクセスがないとスリープ（起動に30秒程度）
- 月750時間まで

頻繁に使用する場合は **Starter プラン（$7/月）** を検討:
- スリープなし
- より高速なCPU

---

## 9. セキュリティチェックリスト

- [x] `.env` ファイルをコミットしていない
- [x] `credentials.json` をコミットしていない
- [x] サービスアカウントキーをBase64エンコードして環境変数に設定
- [x] スプレッドシートにサービスアカウントを共有（編集者権限）
- [x] HTTPS通信（Renderはデフォルトで有効）
- [ ] 必要に応じてレート制限を設定
- [ ] エラーログ監視（Render Dashboard → Logs）

---

## 10. 更新手順

コードを更新してデプロイ:

```bash
# ローカルで変更をコミット
git add .
git commit -m "Update feature"
git push origin main

# Renderが自動的に再デプロイ（5-10分）
```

手動デプロイ:
1. Dashboard → Manual Deploy
2. **Deploy latest commit** をクリック

---

## 11. コスト見積もり

- **Render Free Plan**: $0/月（750時間、スリープあり）
- **Render Starter Plan**: $7/月（スリープなし）
- **Google Cloud**: Vision API月1000リクエストまで無料
- **Claude API**: 使用量に応じて課金
- **Gemini API**: 無料枠あり

**推奨**: 無料プランで開始し、必要に応じてアップグレード

---

## サポート

問題が発生した場合:
1. Render Dashboard → Logs を確認
2. `RENDER_DEPLOYMENT.md` のトラブルシューティングを参照
3. GitHubリポジトリのIssuesで質問

デプロイ成功をお祈りしています！🚀
