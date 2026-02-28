"""仕入れ処理関連のエンドポイント"""
import re
import tempfile
import shutil
import time
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, File, UploadFile, HTTPException, Query
from pydantic import BaseModel

from src.purchase_extractor import PurchaseExtractor, PurchaseInvoice, PurchaseItem
from src.sheets_client import GoogleSheetsClient, parse_amount, _find_company_row
from src.database import MonthlyItemsDB

router = APIRouter()


# --- レスポンス/リクエストモデル ---

class PurchaseItemResponse(BaseModel):
    product_code: str
    product_name: str
    quantity: int
    unit_price: int
    amount: int


class PurchaseInvoiceResponse(BaseModel):
    date: str
    supplier_name: str
    slip_number: str
    items: list[PurchaseItemResponse]
    subtotal: int
    tax: int
    total: int
    is_taxable: bool


class ProcessPurchasePDFResponse(BaseModel):
    purchase_invoices: list[PurchaseInvoiceResponse]
    records_count: int
    purchase_pdf_url: str


class PurchaseNoteRequest(BaseModel):
    date: str
    slip_number: str
    items: list[PurchaseItemResponse]
    subtotal: int
    tax: int
    total: int
    is_taxable: bool = True


class SavePurchaseRequest(BaseModel):
    company_name: str
    year_month: str
    purchase_notes: list[PurchaseNoteRequest]
    sales_person: str = ""
    request_id: str = ""
    force_overwrite: bool = False


class ExistingPurchaseNoteInfo(BaseModel):
    slip_number: str
    date: str
    subtotal: int
    tax: int
    total: int
    sales_person: str
    saved_at: str


class SavePurchaseResponse(BaseModel):
    success: bool
    message: str
    saved_count: int = 0
    duplicate_conflict: bool = False
    existing_notes: list[ExistingPurchaseNoteInfo] = []
    warning: str = ""


class UpdatePurchasePaymentRequest(BaseModel):
    company_name: str
    year_month: str
    payment_amount: int
    add_mode: bool


class UpdatePurchasePaymentResponse(BaseModel):
    success: bool
    message: str
    previous_value: int
    new_value: int


class PurchaseCompaniesAndMonthsResponse(BaseModel):
    companies: list[str]
    year_months: list[str]


class PurchaseTableResponse(BaseModel):
    headers: list[str]
    data: list[list[str]]


class PurchaseMonthlyItem(BaseModel):
    id: int
    slip_number: str
    date: str
    sales_person: str
    subtotal: int
    tax: int
    total: int
    is_taxable: bool
    items: list[PurchaseItemResponse]


class PurchaseDeliveryNoteOut(BaseModel):
    id: int
    slip_number: str
    date: str
    subtotal: int
    tax: int
    total: int
    is_taxable: bool


class UpdatePurchaseNoteRequest(BaseModel):
    subtotal: int
    tax: int
    total: int


# --- ヘルパー ---

def _extract_year_from_year_month(year_month: str) -> int:
    match = re.match(r'(\d{4})', year_month)
    if match:
        return int(match.group(1))
    from datetime import datetime
    return datetime.now().year


def _convert_purchase_invoice(invoice: PurchaseInvoice) -> PurchaseInvoiceResponse:
    """PurchaseInvoiceをレスポンス形式に変換"""
    return PurchaseInvoiceResponse(
        date=invoice.date,
        supplier_name=invoice.supplier_name,
        slip_number=invoice.slip_number,
        items=[
            PurchaseItemResponse(
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
        is_taxable=invoice.is_taxable,
    )


# --- エンドポイント ---

@router.post("/process-purchase-pdf", response_model=ProcessPurchasePDFResponse)
async def process_purchase_pdf(file: UploadFile = File(...)):
    """仕入れ納品書PDFを処理して情報を抽出（配列で返却）"""

    if not file.filename.endswith('.pdf'):
        raise HTTPException(status_code=400, detail="PDFファイルのみアップロード可能です")

    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp_file:
        content = await file.read()
        tmp_file.write(content)
        tmp_path = Path(tmp_file.name)

    try:
        # 1. PDF抽出
        extractor = PurchaseExtractor()
        invoices = extractor.extract_from_pdf(str(tmp_path))

        if not invoices:
            raise HTTPException(status_code=500, detail="PDFの抽出に失敗しました")

        # 2. 納品書PDFをoutputディレクトリに保存
        output_dir = Path(__file__).parent.parent.parent / "output"
        output_dir.mkdir(exist_ok=True)

        safe_supplier_name = (invoices[0].supplier_name or "unknown").replace("/", "_").replace("\\", "_")
        date_str = (invoices[0].date or "").replace("/", "")
        purchase_filename = f"purchase_{safe_supplier_name}_{date_str}.pdf"
        purchase_path = output_dir / purchase_filename
        shutil.copy(tmp_path, purchase_path)

        # 3. レスポンス作成
        timestamp = int(time.time())
        purchase_pdf_url = f"/output/{purchase_filename}?t={timestamp}"

        return ProcessPurchasePDFResponse(
            purchase_invoices=[_convert_purchase_invoice(inv) for inv in invoices],
            records_count=len(invoices),
            purchase_pdf_url=purchase_pdf_url,
        )

    except HTTPException:
        raise
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"処理エラー: {str(e)}")
    finally:
        if tmp_path.exists():
            tmp_path.unlink()


@router.post("/save-purchase")
async def save_purchase(request: SavePurchaseRequest):
    """仕入れデータをDB+シートに保存（2層保存）"""

    try:
        print(f"[save-purchase] 受信: {len(request.purchase_notes)}件の納品書, 会社={request.company_name}, 年月={request.year_month}")
        for i, note in enumerate(request.purchase_notes):
            print(f"  [{i}] slip={note.slip_number}, subtotal={note.subtotal}, tax={note.tax}, total={note.total}")

        db = MonthlyItemsDB()

        # 1. 冪等性チェック
        if request.request_id and db.check_request_id(request.request_id):
            return SavePurchaseResponse(
                success=True,
                message="この保存リクエストは既に処理済みです",
                saved_count=0,
            )

        # 2. 会社名正規化
        sheets_client = GoogleSheetsClient()
        company_name = request.company_name
        target_year = _extract_year_from_year_month(request.year_month)
        canonical = sheets_client.get_canonical_purchase_company_name(
            company_name, year=target_year
        )
        if canonical:
            company_name = canonical

        # 3. 年月フォーマット変換
        year_month_str = request.year_month
        if '-' in year_month_str and '年' not in year_month_str:
            parts = year_month_str.split('-')
            year_month_str = f"{int(parts[0])}年{int(parts[1])}月"

        # 4. PurchaseInvoiceオブジェクトリストを構築
        purchase_invoices = []
        for note_req in request.purchase_notes:
            items = [
                PurchaseItem(
                    product_code=item.product_code,
                    product_name=item.product_name,
                    quantity=item.quantity,
                    unit_price=item.unit_price,
                    amount=item.amount,
                )
                for item in note_req.items
            ]

            purchase_invoices.append(PurchaseInvoice(
                date=note_req.date,
                supplier_name=company_name,
                slip_number=note_req.slip_number,
                items=items,
                subtotal=note_req.subtotal,
                tax=note_req.tax,
                total=note_req.total,
                is_taxable=note_req.is_taxable,
            ))

        # 5. 重複チェック
        if not request.force_overwrite:
            slip_numbers = [pi.slip_number for pi in purchase_invoices if pi.slip_number]
            existing = db.find_existing_purchase_slip_numbers(
                company_name=company_name,
                year_month=year_month_str,
                slip_numbers=slip_numbers,
            )
            if existing:
                return SavePurchaseResponse(
                    success=False,
                    duplicate_conflict=True,
                    existing_notes=[ExistingPurchaseNoteInfo(**e) for e in existing],
                    message="以下の伝票番号は既にDBに保存されています",
                )

        # 6. シート保存（先に実行 — 失敗したらDB保存しない）
        for pi in purchase_invoices:
            sheets_client.save_purchase_record(
                supplier_name=company_name,
                target_year_month=year_month_str,
                purchase_invoice=pi,
            )

        # 7. シート保存成功後にDB保存
        saved_count = db.save_purchase_batch(
            company_name=company_name,
            year_month=year_month_str,
            purchase_invoices=purchase_invoices,
            sales_person=request.sales_person,
            request_id=request.request_id,
        )

        message = f"仕入れデータを {company_name} ({request.year_month}) に保存しました（{saved_count}件）"

        return SavePurchaseResponse(
            success=True,
            message=message,
            saved_count=saved_count,
        )

    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/update-purchase-payment", response_model=UpdatePurchasePaymentResponse)
async def update_purchase_payment(request: UpdatePurchasePaymentRequest):
    """仕入れスプレッドシートの消滅列を更新"""

    try:
        sheets_client = GoogleSheetsClient()
        result = sheets_client.update_purchase_payment(
            company_name=request.company_name,
            year_month=request.year_month,
            payment_amount=request.payment_amount,
            add_mode=request.add_mode,
        )

        action = "加算" if request.add_mode else "更新"
        return UpdatePurchasePaymentResponse(
            success=True,
            message=f"{action}完了: {request.company_name} の {request.year_month} 消滅",
            previous_value=result["previous_value"],
            new_value=result["new_value"],
        )

    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))



@router.get("/purchase-companies-and-months", response_model=PurchaseCompaniesAndMonthsResponse)
async def get_purchase_companies_and_months():
    """仕入れスプレッドシートから会社リストと年月リストを取得"""
    try:
        sheets_client = GoogleSheetsClient()
        result = sheets_client.get_purchase_companies_and_months()
        return PurchaseCompaniesAndMonthsResponse(**result)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/purchase-db-companies")
async def get_purchase_db_companies():
    """仕入れDBの会社一覧を取得"""
    try:
        db = MonthlyItemsDB()
        companies = db.get_purchase_companies()
        return {"companies": companies}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/purchase-db-sales-persons")
async def get_purchase_db_sales_persons(company_name: str = ""):
    """仕入れDBの担当者一覧を取得"""
    try:
        db = MonthlyItemsDB()
        sales_persons = db.get_purchase_sales_persons(company_name)
        return {"sales_persons": sales_persons}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/purchase-monthly")
async def get_purchase_monthly(
    company_name: str = Query(""),
    year_month: str = Query(""),
    sales_person: str = Query(""),
):
    """仕入れ月次一覧データを取得"""
    try:
        db = MonthlyItemsDB()

        # year_month を "YYYY年M月" 形式に変換
        ym = year_month
        if '-' in ym and '年' not in ym:
            parts = ym.split('-')
            ym = f"{int(parts[0])}年{int(parts[1])}月"

        items = db.get_purchase_items(
            company_name=company_name,
            year_month=ym,
            sales_person=sales_person,
        )
        return {"items": items}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/purchase-table", response_model=PurchaseTableResponse)
async def get_purchase_table():
    """仕入れスプレッドシートの全データを取得"""
    try:
        sheets_client = GoogleSheetsClient()
        result = sheets_client.get_purchase_table()
        return PurchaseTableResponse(**result)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/purchase-delivery-notes")
async def get_purchase_delivery_notes(
    company_name: str = Query(...),
    year_month: str = Query(...),
):
    """仕入れDBの納品書一覧（ID付き）を取得"""
    try:
        db = MonthlyItemsDB()
        ym = year_month
        if '-' in ym and '年' not in ym:
            parts = ym.split('-')
            ym = f"{int(parts[0])}年{int(parts[1])}月"

        notes = db.get_purchase_notes_with_ids(company_name, ym)
        return {"notes": [PurchaseDeliveryNoteOut(**n) for n in notes]}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/purchase-delivery-notes/{note_id}")
async def update_purchase_delivery_note(note_id: int, request: UpdatePurchaseNoteRequest):
    """仕入れ納品書の金額を更新"""
    try:
        db = MonthlyItemsDB()
        db.update_purchase_note_amounts(
            note_id, request.subtotal, request.tax, request.total
        )
        return {"success": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
