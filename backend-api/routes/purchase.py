"""仕入れ処理関連のエンドポイント"""
import tempfile
import shutil
import time
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, File, UploadFile, HTTPException
from pydantic import BaseModel

from src.purchase_extractor import PurchaseExtractor, PurchaseInvoice, PurchaseItem
from src.sheets_client import GoogleSheetsClient, PaymentTerms
from src.utils import calculate_target_month

router = APIRouter()


class PurchaseItemResponse(BaseModel):
    slip_number: str
    product_code: str
    product_name: str
    quantity: int
    unit_price: int
    amount: int


class PurchaseInvoiceResponse(BaseModel):
    date: str
    supplier_name: str
    supplier_address: str
    slip_number: str
    items: list[PurchaseItemResponse]
    subtotal: int
    tax: int
    total: int
    customs_duty: int
    is_overseas: bool


class PaymentTermsResponse(BaseModel):
    supplier_name: str
    closing_day: str
    payment_day: str
    payment_method: str


class ProcessPurchasePDFResponse(BaseModel):
    purchase_invoice: PurchaseInvoiceResponse
    payment_terms: Optional[PaymentTermsResponse]
    target_year_month: str
    is_overseas: bool
    records_count: int
    purchase_pdf_url: str


class SavePurchaseRecordRequest(BaseModel):
    supplier_name: str
    target_year_month: str
    purchase_invoice: PurchaseInvoiceResponse


class SavePurchaseRecordResponse(BaseModel):
    success: bool
    message: str


def _convert_purchase_invoice(invoice: PurchaseInvoice) -> PurchaseInvoiceResponse:
    """PurchaseInvoiceをレスポンス形式に変換"""
    return PurchaseInvoiceResponse(
        date=invoice.date,
        supplier_name=invoice.supplier_name,
        supplier_address=invoice.supplier_address,
        slip_number=invoice.slip_number,
        items=[
            PurchaseItemResponse(
                slip_number=item.slip_number,
                product_code=item.product_code,
                product_name=item.product_name,
                quantity=item.quantity,
                unit_price=item.unit_price,
                amount=item.amount,
            )
            for item in invoice.items
        ],
        subtotal=invoice.subtotal,
        tax=invoice.tax,
        total=invoice.total,
        customs_duty=invoice.customs_duty,
        is_overseas=invoice.is_overseas,
    )


def _convert_payment_terms(terms: PaymentTerms) -> PaymentTermsResponse:
    """PaymentTermsをレスポンス形式に変換"""
    return PaymentTermsResponse(
        supplier_name=terms.supplier_name,
        closing_day=terms.closing_day,
        payment_day=terms.payment_day,
        payment_method=terms.payment_method,
    )


@router.post("/process-purchase-pdf", response_model=ProcessPurchasePDFResponse)
async def process_purchase_pdf(file: UploadFile = File(...)):
    """仕入れ納品書PDFを処理して情報を抽出"""

    # ファイル形式チェック
    if not file.filename.endswith('.pdf'):
        raise HTTPException(status_code=400, detail="PDFファイルのみアップロード可能です")

    # 一時ファイルに保存
    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp_file:
        content = await file.read()
        tmp_file.write(content)
        tmp_path = Path(tmp_file.name)

    try:
        # 1. PDF抽出（Vision API + Gemini）
        extractor = PurchaseExtractor()
        purchase_invoice = extractor.extract_from_pdf(str(tmp_path))

        if not purchase_invoice:
            raise HTTPException(status_code=500, detail="PDFの抽出に失敗しました")

        # 2. 納品書PDFをoutputディレクトリに保存
        output_dir = Path(__file__).parent.parent.parent / "output"
        output_dir.mkdir(exist_ok=True)

        safe_supplier_name = purchase_invoice.supplier_name.replace("/", "_").replace("\\", "_")
        date_str = purchase_invoice.date.replace("/", "") if purchase_invoice.date else ""
        purchase_filename = f"purchase_{safe_supplier_name}_{date_str}.pdf"
        purchase_path = output_dir / purchase_filename

        # 納品書PDFをコピー
        shutil.copy(tmp_path, purchase_path)

        # 3. 締め日マスター取得
        sheets_client = GoogleSheetsClient()
        payment_terms = sheets_client.get_payment_terms(purchase_invoice.supplier_name)

        # 締め日がない場合はデフォルト「月末」
        closing_day = payment_terms.closing_day if payment_terms else "月末"

        # 4. 記入対象月を計算
        target_year_month = calculate_target_month(purchase_invoice.date, closing_day)

        # 5. レスポンス作成
        timestamp = int(time.time())
        purchase_pdf_url = f"/output/{purchase_filename}?t={timestamp}"

        records_count = 2 if purchase_invoice.is_overseas else 1

        return ProcessPurchasePDFResponse(
            purchase_invoice=_convert_purchase_invoice(purchase_invoice),
            payment_terms=_convert_payment_terms(payment_terms) if payment_terms else None,
            target_year_month=target_year_month,
            is_overseas=purchase_invoice.is_overseas,
            records_count=records_count,
            purchase_pdf_url=purchase_pdf_url,
        )

    except HTTPException:
        raise
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"処理エラー: {str(e)}")
    finally:
        # 一時ファイルを削除
        if tmp_path.exists():
            tmp_path.unlink()


@router.post("/save-purchase-record", response_model=SavePurchaseRecordResponse)
async def save_purchase_record(request: SavePurchaseRecordRequest):
    """仕入れスプレッドシートにデータを保存"""

    try:
        # リクエストをPurchaseInvoiceに変換
        purchase_invoice = PurchaseInvoice(
            date=request.purchase_invoice.date,
            supplier_name=request.purchase_invoice.supplier_name,
            supplier_address=request.purchase_invoice.supplier_address,
            slip_number=request.purchase_invoice.slip_number,
            items=[
                PurchaseItem(
                    slip_number=item.slip_number,
                    product_code=item.product_code,
                    product_name=item.product_name,
                    quantity=item.quantity,
                    unit_price=item.unit_price,
                    amount=item.amount,
                )
                for item in request.purchase_invoice.items
            ],
            subtotal=request.purchase_invoice.subtotal,
            tax=request.purchase_invoice.tax,
            total=request.purchase_invoice.total,
            customs_duty=request.purchase_invoice.customs_duty,
            is_overseas=request.purchase_invoice.is_overseas,
        )

        # スプレッドシートに保存
        sheets_client = GoogleSheetsClient()
        sheets_client.save_purchase_record(
            supplier_name=request.supplier_name,
            target_year_month=request.target_year_month,
            purchase_invoice=purchase_invoice,
        )

        return SavePurchaseRecordResponse(
            success=True,
            message=f"仕入れデータを '{request.target_year_month}' に保存しました",
        )

    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"保存エラー: {str(e)}")
