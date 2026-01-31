"""FastAPI バックエンド - 納品書処理システム"""
import sys
from pathlib import Path

# プロジェクトルートを追加（既存のsrc/を使用するため）
sys.path.insert(0, str(Path(__file__).parent.parent))

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from routes import pdf, billing, config

app = FastAPI(
    title="納品書処理システム API",
    description="納品書PDFから請求書PDFを生成するAPI",
    version="1.0.0",
)

# CORS設定（開発時）
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:3001"],  # Reactの開発サーバー
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ルーター登録
app.include_router(pdf.router, prefix="/api", tags=["PDF処理"])
app.include_router(billing.router, prefix="/api", tags=["請求管理"])
app.include_router(config.router, prefix="/api", tags=["設定"])

# 静的ファイル（生成されたPDF）
output_dir = Path(__file__).parent.parent / "output"
output_dir.mkdir(exist_ok=True)
app.mount("/output", StaticFiles(directory=str(output_dir)), name="output")


@app.get("/")
async def root():
    return {
        "message": "納品書処理システム API",
        "version": "1.0.0",
        "docs": "/docs",
    }


@app.get("/health")
async def health():
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
