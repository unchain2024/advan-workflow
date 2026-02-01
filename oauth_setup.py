"""OAuth 2.0認証を事前に設定するスクリプト"""
import os
import pickle
from pathlib import Path
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request

def setup_oauth():
    """OAuth 2.0 認証を実行してtoken.pickleを生成"""
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
        "https://www.googleapis.com/auth/cloud-vision",
    ]

    credentials_path = Path("credentials.json")
    token_path = Path("token.pickle")

    if not credentials_path.exists():
        print("❌ エラー: credentials.json が見つかりません")
        print("Google Cloud Console で OAuth 2.0 クライアントID（デスクトップアプリ）を作成し、")
        print("認証情報JSONをダウンロードして credentials.json として保存してください。")
        return False

    credentials = None

    # 既存のトークンを確認
    if token_path.exists():
        print("既存の認証トークンが見つかりました。")
        with open(token_path, "rb") as token:
            credentials = pickle.load(token)

    # トークンが無効または存在しない場合は再認証
    if not credentials or not credentials.valid:
        if credentials and credentials.expired and credentials.refresh_token:
            print("トークンを更新中...")
            credentials.refresh(Request())
        else:
            print("OAuth 2.0 認証を開始します...")
            print("ブラウザが開きます。Googleアカウントでログインして、")
            print("アプリケーションにGoogle Sheetsへのアクセスを許可してください。")

            flow = InstalledAppFlow.from_client_secrets_file(
                str(credentials_path),
                scopes=scopes,
                # refresh_token を取得するために必須
                redirect_uri='http://localhost:8080'
            )

            # ポートを指定（環境変数で変更可能）
            port = int(os.getenv("OAUTH_PORT", "8080"))
            # access_type='offline' と prompt='consent' を指定して refresh_token を取得
            credentials = flow.run_local_server(
                port=port,
                access_type='offline',
                prompt='consent'
            )

        # トークンを保存
        with open(token_path, "wb") as token:
            pickle.dump(credentials, token)

        print("✅ 認証成功！token.pickle を生成しました。")
    else:
        print("✅ 既存の認証トークンは有効です。")

    return True

if __name__ == "__main__":
    print("=" * 60)
    print("Google Sheets API - OAuth 2.0 認証セットアップ")
    print("=" * 60)

    if setup_oauth():
        print("\n認証が完了しました。バックエンドサーバーを起動できます。")
        print("次のコマンドでサーバーを起動してください:")
        print("  cd backend-api")
        print("  USE_OAUTH=true uvicorn main:app --reload --port 8000")
    else:
        print("\n認証に失敗しました。")
