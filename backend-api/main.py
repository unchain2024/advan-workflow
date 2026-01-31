"""FastAPI バックエンド - 納品書処理システム"""
import os
import sys
from pathlib import Path

# プロジェクトルートを追加（既存のsrc/を使用するため）
sys.path.insert(0, str(Path(__file__).parent.parent))

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from routes import pdf, billing, config

app = FastAPI(
    title="納品書処理システム API",
    description="納品書PDFから請求書PDFを生成するAPI",
    version="1.0.0",
)

# CORS設定
allowed_origins = ["http://localhost:3000", "http://localhost:3001"]
# 本番環境のドメインも許可
if os.getenv("ENVIRONMENT") == "production":
    render_url = os.getenv("RENDER_EXTERNAL_URL")
    if render_url:
        allowed_origins.append(render_url)

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ルーター登録（APIは /api プレフィックス）
app.include_router(pdf.router, prefix="/api", tags=["PDF処理"])
app.include_router(billing.router, prefix="/api", tags=["請求管理"])
app.include_router(config.router, prefix="/api", tags=["設定"])

# 静的ファイル（生成されたPDF）
output_dir = Path(__file__).parent.parent / "output"
output_dir.mkdir(exist_ok=True)
app.mount("/output", StaticFiles(directory=str(output_dir)), name="output")

# React フロントエンド（ビルド済み）を配信
frontend_dist = Path(__file__).parent.parent / "frontend-react" / "dist"
if frontend_dist.exists():
    app.mount("/assets", StaticFiles(directory=str(frontend_dist / "assets")), name="assets")


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/api")
async def api_root():
    """API情報エンドポイント"""
    return {
        "message": "納品書処理システム API",
        "version": "1.0.0",
        "docs": "/docs",
    }


# React アプリのルートとSPAルーティング対応
@app.get("/{full_path:path}")
async def serve_react_app(full_path: str):
    """Reactアプリを配信（SPAルーティング対応）"""
    frontend_dist = Path(__file__).parent.parent / "frontend-react" / "dist"

    if not frontend_dist.exists():
        # フロントエンドがビルドされていない場合はAPI情報を返す
        return {
            "message": "納品書処理システム API",
            "version": "1.0.0",
            "docs": "/docs",
            "note": "フロントエンドはビルドされていません",
        }

    # 要求されたファイルが存在すればそれを返す
    file_path = frontend_dist / full_path
    if file_path.is_file():
        return FileResponse(file_path)

    # それ以外は index.html を返す（SPAルーティング）
    index_path = frontend_dist / "index.html"
    if index_path.exists():
        return FileResponse(index_path)

    return {"error": "Frontend not found"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
