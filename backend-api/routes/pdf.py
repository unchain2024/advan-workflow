"""PDF処理関連のエンドポイント"""
import tempfile
import io
import base64
import shutil
import time
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, File, UploadFile, HTTPException
from fastapi.responses import StreamingResponse, FileResponse
from pydantic import BaseModel
from pdf2image import convert_from_path
from PIL import Image

from src.llm_extractor import LLMExtractor
from src.sheets_client import GoogleSheetsClient
from src.invoice_generator import InvoiceGenerator
from src.pdf_extractor import DeliveryNote, DeliveryItem

router = APIRouter()


class DeliveryItemResponse(BaseModel):
    slip_number: str
    product_code: str
    product_name: str
    quantity: int
    unit_price: int
    amount: int


class DeliveryNoteResponse(BaseModel):
    date: str
    company_name: str
    slip_number: str
    items: list[DeliveryItemResponse]
    subtotal: int
    tax: int
    total: int
    payment_received: int


class CompanyInfoResponse(BaseModel):
    company_name: str
    postal_code: str
    address: str
    department: str


class PreviousBillingResponse(BaseModel):
    previous_amount: int
    payment_received: int
    carried_over: int
    sales_amount: int = 0
    tax_amount: int = 0
    current_amount: int = 0


class ProcessPDFResponse(BaseModel):
    delivery_note: DeliveryNoteResponse
    company_info: Optional[CompanyInfoResponse]
    previous_billing: PreviousBillingResponse
    invoice_url: str
    delivery_pdf_url: str
    year_month: str


class RegenerateInvoiceRequest(BaseModel):
    delivery_note: DeliveryNoteResponse
    company_info: Optional[CompanyInfoResponse]
    previous_billing: PreviousBillingResponse


class RegenerateInvoiceResponse(BaseModel):
    invoice_url: str
    invoice_filename: str


def extract_year_month(date_str: str) -> str:
    """日付文字列からYYYY-MM形式の年月を抽出"""
    if date_str and '/' in date_str:
        parts = date_str.split('/')
        if len(parts) >= 2:
            return f"{parts[0]}-{parts[1]}"

    from datetime import datetime
    return datetime.now().strftime("%Y-%m")


@router.post("/process-pdf", response_model=ProcessPDFResponse)
async def process_pdf(file: UploadFile = File(...)):
    """納品書PDFを処理して請求書を生成"""

    # ファイル形式チェック
    if not file.filename.endswith('.pdf'):
        raise HTTPException(status_code=400, detail="PDFファイルのみアップロード可能です")

    # 一時ファイルに保存
    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp_file:
        content = await file.read()
        tmp_file.write(content)
        tmp_path = Path(tmp_file.name)

    try:
        # 1. PDF抽出
        extractor = LLMExtractor()
        delivery_note = extractor.extract(tmp_path)

        # 2. 納品書PDFをoutputディレクトリに保存
        output_dir = Path(__file__).parent.parent.parent / "output"
        output_dir.mkdir(exist_ok=True)

        safe_company_name = delivery_note.company_name.replace("/", "_").replace("\\", "_")
        date_str = delivery_note.date.replace("/", "") if delivery_note.date else ""
        delivery_filename = f"delivery_{safe_company_name}_{date_str}.pdf"
        delivery_path = output_dir / delivery_filename

        # 納品書PDFをコピー
        shutil.copy(tmp_path, delivery_path)

        # 3. 会社情報取得
        sheets_client = GoogleSheetsClient()
        company_info = sheets_client.get_company_info(delivery_note.company_name)

        # 4. 前月の請求情報を取得
        year_month = extract_year_month(delivery_note.date)
        previous_billing = sheets_client.get_previous_billing(
            delivery_note.company_name, year_month
        )

        # 5. 請求書PDF生成
        invoice_generator = InvoiceGenerator()

        # 請求書PDFをoutputディレクトリに生成
        safe_company_name = delivery_note.company_name.replace("/", "_").replace("\\", "_")
        date_str = delivery_note.date.replace("/", "") if delivery_note.date else ""
        invoice_filename = f"invoice_{safe_company_name}_{date_str}.pdf"
        invoice_path = output_dir / invoice_filename

        invoice_generator.generate(
            delivery_note=delivery_note,
            company_info=company_info,
            previous_billing=previous_billing,
            output_path=invoice_path,
        )

        # 6. 月次明細DBに保存
        from src.database import MonthlyItemsDB
        from src.utils import parse_year_month

        year_month_str = parse_year_month(delivery_note.date)
        if year_month_str:
            db = MonthlyItemsDB()
            db.save_monthly_items(
                company_name=delivery_note.company_name,
                year_month=year_month_str,
                delivery_note=delivery_note,
            )

        # レスポンス作成（キャッシュバスティング用にタイムスタンプ追加）
        timestamp = int(time.time())
        invoice_url = f"/output/{invoice_filename}?t={timestamp}"
        delivery_pdf_url = f"/output/{delivery_filename}?t={timestamp}"

        return ProcessPDFResponse(
            delivery_note=DeliveryNoteResponse(
                date=delivery_note.date,
                company_name=delivery_note.company_name,
                slip_number=delivery_note.slip_number,
                items=[
                    DeliveryItemResponse(
                        slip_number=item.slip_number,
                        product_code=item.product_code,
                        product_name=item.product_name,
                        quantity=item.quantity,
                        unit_price=item.unit_price,
                        amount=item.amount,
                    )
                    for item in delivery_note.items
                ],
                subtotal=delivery_note.subtotal,
                tax=delivery_note.tax,
                total=delivery_note.total,
                payment_received=delivery_note.payment_received,
            ),
            company_info=(
                CompanyInfoResponse(
                    company_name=company_info.company_name,
                    postal_code=company_info.postal_code,
                    address=company_info.address,
                    department=company_info.department,
                )
                if company_info
                else None
            ),
            previous_billing=PreviousBillingResponse(
                previous_amount=previous_billing.previous_amount,
                payment_received=previous_billing.payment_received,
                carried_over=previous_billing.carried_over,
                sales_amount=previous_billing.sales_amount or 0,
                tax_amount=previous_billing.tax_amount or 0,
                current_amount=previous_billing.current_amount or 0,
            ),
            invoice_url=invoice_url,
            delivery_pdf_url=delivery_pdf_url,
            year_month=year_month,
        )

    except Exception as e:
        import traceback
        error_detail = {
            "error": str(e),
            "traceback": traceback.format_exc()
        }
        print(f"ERROR in process_pdf: {error_detail}")  # デバッグ用
        raise HTTPException(status_code=500, detail=error_detail)

    finally:
        # 一時ファイルを削除
        if tmp_path.exists():
            tmp_path.unlink()


@router.post("/regenerate-invoice", response_model=RegenerateInvoiceResponse)
async def regenerate_invoice(request: RegenerateInvoiceRequest):
    """編集後の内容で請求書PDFを再生成"""

    try:
        # DeliveryNoteオブジェクトを再構築
        items = [
            DeliveryItem(
                slip_number=item.slip_number,
                product_code=item.product_code,
                product_name=item.product_name,
                quantity=item.quantity,
                unit_price=item.unit_price,
                amount=item.amount,
            )
            for item in request.delivery_note.items
        ]

        delivery_note = DeliveryNote(
            date=request.delivery_note.date,
            company_name=request.delivery_note.company_name,
            slip_number=request.delivery_note.slip_number,
            items=items,
            subtotal=request.delivery_note.subtotal,
            tax=request.delivery_note.tax,
            total=request.delivery_note.total,
            payment_received=request.delivery_note.payment_received,
        )

        # CompanyInfoオブジェクトを再構築
        from src.sheets_client import CompanyInfo, PreviousBilling as PrevBilling

        company_info = None
        if request.company_info:
            company_info = CompanyInfo(
                company_name=request.company_info.company_name,
                postal_code=request.company_info.postal_code,
                address=request.company_info.address,
                department=request.company_info.department,
            )

        # PreviousBillingオブジェクトを再構築
        previous_billing = PrevBilling(
            previous_amount=request.previous_billing.previous_amount,
            payment_received=request.previous_billing.payment_received,
            carried_over=request.previous_billing.carried_over,
        )

        # 請求書PDF生成
        invoice_generator = InvoiceGenerator()

        # outputディレクトリに保存
        output_dir = Path(__file__).parent.parent.parent / "output"
        output_dir.mkdir(exist_ok=True)

        safe_company_name = delivery_note.company_name.replace("/", "_").replace("\\", "_")
        date_str = delivery_note.date.replace("/", "") if delivery_note.date else ""
        invoice_filename = f"invoice_{safe_company_name}_{date_str}.pdf"
        invoice_path = output_dir / invoice_filename

        # 古いPDFファイルを削除（キャッシュ対策）
        if invoice_path.exists():
            invoice_path.unlink()

        invoice_generator.generate(
            delivery_note=delivery_note,
            company_info=company_info,
            previous_billing=previous_billing,
            output_path=invoice_path,
        )

        # キャッシュバスティング用にタイムスタンプを追加
        timestamp = int(time.time())
        invoice_url = f"/output/{invoice_filename}?t={timestamp}"

        return RegenerateInvoiceResponse(
            invoice_url=invoice_url,
            invoice_filename=invoice_path.name,
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/invoices/{filename}")
async def get_invoice(filename: str):
    """生成された請求書PDFをダウンロード"""
    output_dir = Path(__file__).parent.parent.parent / "output"
    file_path = output_dir / filename

    if not file_path.exists():
        raise HTTPException(status_code=404, detail="ファイルが見つかりません")

    return FileResponse(
        file_path,
        media_type="application/pdf",
        filename=filename,
    )


@router.get("/pdf-to-image/{filename}")
async def pdf_to_image(filename: str, page: int = 1):
    """PDFを画像（PNG）に変換して返す"""
    output_dir = Path(__file__).parent.parent.parent / "output"
    file_path = output_dir / filename

    if not file_path.exists():
        raise HTTPException(status_code=404, detail="ファイルが見つかりません")

    try:
        # PDFを画像に変換（指定ページのみ）
        images = convert_from_path(
            str(file_path),
            first_page=page,
            last_page=page,
            dpi=150,  # 解像度
        )

        if not images:
            raise HTTPException(status_code=404, detail="指定されたページが見つかりません")

        # 画像をバイトストリームに変換
        img_byte_arr = io.BytesIO()
        images[0].save(img_byte_arr, format='PNG')
        img_byte_arr.seek(0)

        return StreamingResponse(
            img_byte_arr,
            media_type="image/png",
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"画像変換エラー: {str(e)}")


class PDFToImagesResponse(BaseModel):
    images: list[str]  # base64エンコードされた画像のリスト
    num_pages: int


@router.get("/pdf-to-images/{filename}", response_model=PDFToImagesResponse)
async def pdf_to_images(filename: str):
    """PDFの全ページを画像（base64）に変換して返す"""
    output_dir = Path(__file__).parent.parent.parent / "output"
    file_path = output_dir / filename

    if not file_path.exists():
        raise HTTPException(status_code=404, detail="ファイルが見つかりません")

    try:
        # PDFを画像に変換（全ページ）
        images = convert_from_path(
            str(file_path),
            dpi=150,  # 解像度
        )

        # 各画像をbase64エンコード
        encoded_images = []
        for img in images:
            img_byte_arr = io.BytesIO()
            img.save(img_byte_arr, format='PNG')
            img_byte_arr.seek(0)
            encoded = base64.b64encode(img_byte_arr.getvalue()).decode('utf-8')
            encoded_images.append(f"data:image/png;base64,{encoded}")

        return PDFToImagesResponse(
            images=encoded_images,
            num_pages=len(images),
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"画像変換エラー: {str(e)}")


class GenerateMonthlyInvoiceRequest(BaseModel):
    company_name: str
    year_month: str  # 「YYYY年M月」形式


class GenerateMonthlyInvoiceResponse(BaseModel):
    invoice_url: str
    invoice_filename: str
    delivery_notes_count: int
    total_subtotal: int
    total_tax: int
    total_amount: int
    items_count: int
    delivery_notes: list[str]  # 伝票番号のリスト


@router.post("/generate-monthly-invoice", response_model=GenerateMonthlyInvoiceResponse)
async def generate_monthly_invoice(request: GenerateMonthlyInvoiceRequest):
    """月次請求書を生成

    指定した会社・年月の集約済みデータから月次請求書PDFを生成します。
    """
    try:
        # 1. 月次明細DBからデータ取得
        from src.database import MonthlyItemsDB

        db = MonthlyItemsDB()
        delivery_notes = db.get_monthly_items(
            company_name=request.company_name,
            year_month=request.year_month,
        )

        if not delivery_notes:
            raise HTTPException(
                status_code=404,
                detail=f"指定した会社・年月のデータが見つかりません: {request.company_name} ({request.year_month})"
            )

        # 2. 会社情報取得
        sheets_client = GoogleSheetsClient()
        company_info = sheets_client.get_company_info(request.company_name)

        # 3. 前月の請求情報を取得
        # 年月を "YYYY-MM" 形式に変換
        import re
        match = re.match(r'(\d+)年(\d+)月', request.year_month)
        if match:
            year = match.group(1)
            month = match.group(2)
            year_month_dash = f"{year}-{month.zfill(2)}"
        else:
            year_month_dash = ""

        previous_billing = sheets_client.get_previous_billing(
            request.company_name,
            year_month_dash,
        )

        # 4. 月次請求書PDF生成
        invoice_generator = InvoiceGenerator()

        # outputディレクトリに保存
        output_dir = Path(__file__).parent.parent.parent / "output"
        output_dir.mkdir(exist_ok=True)

        safe_company_name = request.company_name.replace("/", "_").replace("\\", "_")
        # "2025年3月" → "2025_03"
        year_month_safe = request.year_month.replace("年", "_").replace("月", "")
        invoice_filename = f"monthly_invoice_{safe_company_name}_{year_month_safe}.pdf"
        invoice_path = output_dir / invoice_filename

        # 古いPDFファイルを削除（キャッシュ対策）
        if invoice_path.exists():
            invoice_path.unlink()

        invoice_generator.generate_monthly(
            delivery_notes=delivery_notes,
            company_name=request.company_name,
            year_month=request.year_month,
            company_info=company_info,
            previous_billing=previous_billing,
            output_path=invoice_path,
        )

        # 5. レスポンス作成
        total_subtotal = sum(note.subtotal for note in delivery_notes)
        total_tax = sum(note.tax for note in delivery_notes)
        total_amount = total_subtotal + total_tax
        items_count = sum(len(note.items) for note in delivery_notes)
        slip_numbers = [note.slip_number for note in delivery_notes if note.slip_number]

        timestamp = int(time.time())
        invoice_url = f"/output/{invoice_filename}?t={timestamp}"

        return GenerateMonthlyInvoiceResponse(
            invoice_url=invoice_url,
            invoice_filename=invoice_filename,
            delivery_notes_count=len(delivery_notes),
            total_subtotal=total_subtotal,
            total_tax=total_tax,
            total_amount=total_amount,
            items_count=items_count,
            delivery_notes=slip_numbers,
        )

    except HTTPException:
        raise
    except Exception as e:
        import traceback
        error_detail = {
            "error": str(e),
            "traceback": traceback.format_exc()
        }
        print(f"ERROR in generate_monthly_invoice: {error_detail}")
        raise HTTPException(status_code=500, detail=error_detail)
