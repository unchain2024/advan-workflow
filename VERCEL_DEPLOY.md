# Vercelデプロイガイド

このガイドでは、React + FastAPIアプリケーションをVercelにデプロイする手順を説明します。

## 前提条件

- GitHubアカウント
- Vercelアカウント
- このリポジトリがGitHubにプッシュされていること

## デプロイ手順

### 1. Vercelプロジェクトの作成

1. https://vercel.com にアクセスしてログイン
2. 「Add New」→「Project」をクリック
3. GitHubリポジトリを選択（`unchain2024/advan-workflow`）
4. 「Import」をクリック

### 2. プロジェクト設定

**Framework Preset**: 「Other」を選択

**Build & Development Settings**:
- Build Command: `cd frontend-react && npm install && npm run build`
- Output Directory: `frontend-react/dist`
- Install Command: `npm install` (デフォルト)

### 3. 環境変数の設定

「Environment Variables」セクションで以下を設定:

#### 必須の環境変数:
```
# Google Sheets API
COMPANY_MASTER_SPREADSHEET_ID=<スプレッドシートID>
BILLING_SPREADSHEET_ID=<スプレッドシートID>
DELIVERY_DB_SPREADSHEET_ID=<スプレッドシートID>

# API Keys
ANTHROPIC_API_KEY=<Claude APIキー>
GEMINI_API_KEY=<Gemini APIキー>

# OAuth認証
USE_OAUTH=true

# 自社情報（オプション、後で設定画面から変更可能）
OWN_COMPANY_NAME=株式会社サンプル
OWN_REGISTRATION_NUMBER=T0000000000000
OWN_POSTAL_CODE=000-0000
OWN_ADDRESS=東京都〇〇区〇〇1-2-3
OWN_PHONE=00-0000-0000
OWN_BANK_INFO=〇〇銀行 △△支店 普通 0000000
```

### 4. 認証ファイルのアップロード

**重要**: VercelのServerless Functionsでは、ローカルファイルシステムへの書き込みが制限されています。以下の対処が必要です:

#### Option A: 環境変数として設定（推奨）

`credentials.json`と`token.pickle`をBase64エンコードして環境変数に設定:

```bash
# credentials.jsonをBase64エンコード
cat credentials.json | base64 > credentials_base64.txt

# token.pickleをBase64エンコード
cat token.pickle | base64 > token_base64.txt
```

Vercelの環境変数に追加:
```
GOOGLE_CREDENTIALS_BASE64=<credentials_base64.txtの内容>
GOOGLE_TOKEN_BASE64=<token_base64.txtの内容>
```

その後、コードで環境変数から読み込むように修正が必要です。

#### Option B: Vercel Blobストレージ使用

Vercelの永続ストレージサービスを使用してファイルを保存。

### 5. デプロイ

「Deploy」ボタンをクリックすると、Vercelが自動的に:
1. リポジトリをクローン
2. 依存関係をインストール
3. フロントエンドをビルド
4. バックエンドをServerless Functionsとして設定
5. デプロイ

### 6. CI/CD設定

デプロイ後、以下が自動的に設定されます:
- **mainブランチ**: 自動的に本番環境にデプロイ
- **その他のブランチ**: プレビュー環境を自動作成
- **プルリクエスト**: 各PRごとにプレビューURLを生成

### 7. カスタムドメイン設定（オプション）

1. Vercelダッシュボードで「Settings」→「Domains」
2. カスタムドメインを追加
3. DNSレコードを設定

## 制限事項と注意点

### Vercel Serverless Functionsの制限:
- **実行時間**: 最大60秒（Hobby）、300秒（Pro）
- **メモリ**: 最大1024MB
- **ファイルシステム**: `/tmp`のみ書き込み可能（最大512MB）
- **コールドスタート**: 初回リクエストは遅延する可能性

### 推奨事項:
1. **PDF生成**: 60秒制限に注意。大きなPDFは時間がかかる
2. **Google Sheets API**: 複数行の読み書きは時間がかかる可能性
3. **Claude/Gemini API**: Vision APIは画像サイズに注意
4. **ファイル保存**: 生成したPDFは`/tmp`に保存され、リクエスト終了後に削除される

## トラブルシューティング

### デプロイエラー

**エラー**: `ModuleNotFoundError`
- 原因: 依存関係が不足
- 対処: `requirements.txt`に必要なパッケージを追加

**エラー**: `Function invocation timeout`
- 原因: 実行時間が60秒を超えた
- 対処: 処理を最適化するか、Pro プランにアップグレード

### OAuth認証エラー

**エラー**: `OAuth認証が必要です`
- 原因: `credentials.json`または`token.pickle`が見つからない
- 対処: 環境変数として正しく設定されているか確認

### CORS エラー

- Vercelでは自動的に処理されるため、通常は発生しない
- 発生した場合: `backend-api/main.py`のCORS設定を確認

## ログの確認

1. Vercelダッシュボードで「Deployments」タブ
2. デプロイを選択
3. 「Functions」タブでログを確認

## ロールバック

1. Vercelダッシュボードで「Deployments」タブ
2. 以前のデプロイを選択
3. 「Promote to Production」をクリック

## 参考リンク

- [Vercel Documentation](https://vercel.com/docs)
- [Vercel Serverless Functions](https://vercel.com/docs/functions)
- [FastAPI on Vercel](https://vercel.com/guides/using-fastapi-with-vercel)
