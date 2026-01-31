import sys
from pathlib import Path

# プロジェクトルートをPythonパスに追加
root_dir = Path(__file__).parent.parent
sys.path.insert(0, str(root_dir))
sys.path.insert(0, str(root_dir / "backend-api"))

# FastAPIアプリケーションをインポート
from main import app

# Vercel用のハンドラー
handler = app
