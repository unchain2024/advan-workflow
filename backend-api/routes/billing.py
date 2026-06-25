"""請求管理関連のエンドポイント"""
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from typing import Optional

import re

from src.sheets_client import GoogleSheetsClient, PreviousBilling, _find_company_row, match_company_name, parse_amount
from src.pdf_extractor import DeliveryNote, DeliveryItem
from src.database import MonthlyItemsDB
from src.config import BILLING_SPREADSHEET_ID
from src.canonical_companies import list_canonicals


def _extract_year_from_year_month(year_month: str) -> int:
    """年月文字列から年を抽出（例: '2025年3月' → 2025）"""
    match = re.match(r'(\d{4})', year_month)
    if match:
        return int(match.group(1))
    from datetime import datetime
    return datetime.now().year


def _year_month_sort_key(year_month: str) -> tuple[int, int]:
    """'2026年3月' → (2026, 3) でソート用キー"""
    m = re.match(r'(\d{4})年(\d{1,2})月', year_month)
    if m:
        return (int(m.group(1)), int(m.group(2)))
    return (0, 0)

router = APIRouter()


class DeliveryItemRequest(BaseModel):
    slip_number: str
    product_code: str
    product_name: str
    quantity: int
    unit_price: int
    amount: int


class DeliveryNoteRequest(BaseModel):
    date: str
    company_name: str
    slip_number: str
    items: list[DeliveryItemRequest]
    subtotal: int
    tax: int
    total: int
    payment_received: int


class PreviousBillingRequest(BaseModel):
    previous_amount: int
    payment_received: int
    carried_over: int


class SaveBillingRequest(BaseModel):
    company_name: str
    year_month: str
    delivery_notes: list[DeliveryNoteRequest]
    previous_billing: PreviousBillingRequest
    sales_person: str = ""
    request_id: str = ""
    force_overwrite: bool = False


class UpdatePaymentRequest(BaseModel):
    company_name: str
    year_month: str
    payment_amount: int
    add_mode: bool


class UpdatePaymentResponse(BaseModel):
    success: bool
    message: str
    previous_value: int
    new_value: int


class CompaniesAndMonthsResponse(BaseModel):
    companies: list[str]
    year_months: list[str]


class BillingTableResponse(BaseModel):
    headers: list[str]
    data: list[list[str]]


@router.post("/save-billing")
async def save_billing(request: SaveBillingRequest):
    """スプレッドシートに請求情報を保存"""

    try:
        # 冪等性チェック
        db = MonthlyItemsDB()
        if request.request_id and db.check_request_id(request.request_id):
            return {
                "success": True,
                "message": "この保存リクエストは既に処理済みです",
                "saved_count": 0,
            }

        # 会社名をスプレッドシートの正規名に統一
        sheets_client = GoogleSheetsClient()
        company_name = request.company_name
        target_year = None
        if request.delivery_notes and request.delivery_notes[0].date:
            try:
                target_year = int(request.delivery_notes[0].date.split('/')[0])
            except (ValueError, IndexError):
                pass
        canonical = sheets_client.get_canonical_company_name(company_name, year=target_year)
        if not canonical:
            # Phase 1: canonical 不一致は 400 reject。auto-add 厳禁、フロントの会社ピッカーに戻す
            raise HTTPException(
                status_code=400,
                detail={
                    "error": "company_not_matched",
                    "extracted_name": company_name,
                    "candidates": list_canonicals("sales"),
                    "message": f"会社名 '{company_name}' が canonical マスターに一致しませんでした。候補から選択してください。",
                },
            )
        company_name = canonical

        # PreviousBillingオブジェクトを再構築
        previous_billing = PreviousBilling(
            previous_amount=request.previous_billing.previous_amount,
            payment_received=request.previous_billing.payment_received,
            carried_over=request.previous_billing.carried_over,
        )

        # year_month を "YYYY年M月" 形式に変換（DB用）
        year_month_str = request.year_month
        if '-' in year_month_str and '年' not in year_month_str:
            parts = year_month_str.split('-')
            year_month_str = f"{int(parts[0])}年{int(parts[1])}月"

        # DeliveryNote オブジェクトリストを構築
        delivery_notes = []
        for note_req in request.delivery_notes:
            items = [
                DeliveryItem(
                    slip_number=item.slip_number,
                    product_code=item.product_code,
                    product_name=item.product_name,
                    quantity=item.quantity,
                    unit_price=item.unit_price,
                    amount=item.amount,
                )
                for item in note_req.items
            ]

            delivery_notes.append(DeliveryNote(
                date=note_req.date,
                company_name=company_name,
                slip_number=note_req.slip_number,
                items=items,
                subtotal=note_req.subtotal,
                tax=note_req.tax,
                total=note_req.total,
                payment_received=note_req.payment_received,
            ))

        # 重複チェック（force_overwrite でない場合のみ）
        if not request.force_overwrite:
            slip_numbers = [dn.slip_number for dn in delivery_notes if dn.slip_number]
            existing = db.find_existing_slip_numbers(
                company_name=company_name,
                year_month=year_month_str,
                slip_numbers=slip_numbers,
            )
            if existing:
                return {
                    "success": False,
                    "duplicate_conflict": True,
                    "existing_notes": existing,
                    "message": "以下の伝票番号は既にDBに保存されています",
                }

        # Layer 1: DB一括保存（単一トランザクション — 全件成功 or 全件ロールバック）
        saved_count = db.save_monthly_items_batch(
            company_name=company_name,
            year_month=year_month_str,
            delivery_notes=delivery_notes,
            sales_person=request.sales_person,
            request_id=request.request_id,
        )

        # DB が唯一の真値（シート書込は廃止）
        message = (
            f"DB保存成功（{saved_count}件）。"
            f"\n{company_name} ({request.year_month}) を更新しました。"
        )

        return {
            "success": True,
            "message": message,
            "saved_count": saved_count,
            "sheet_errors": [],
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/update-payment", response_model=UpdatePaymentResponse)
async def update_payment(request: UpdatePaymentRequest):
    """入金額（消滅）を更新（Phase 2: DB-first + sheet best-effort）

    DEPRECATED: この経路は POST /payments と機能重複。Phase 2 で DB-first 化したが、
    将来は POST /payments に統一予定。新規実装は /payments を使用してください。
    """
    print(f"    [DEPRECATED] POST /update-payment は POST /payments と統合予定")

    try:
        db = MonthlyItemsDB()

        # 1. DB 上の現在値を取得（previous_value 用）
        prev_entry = db.get_payment(request.company_name, request.year_month)
        previous_value = (prev_entry or {}).get("payment_amount", 0)

        # 2. 新値を確定（add_mode で加算 or 上書き）
        if request.add_mode:
            new_value = previous_value + request.payment_amount
        else:
            new_value = request.payment_amount

        # 3. DB upsert（new_value を絶対値として書込）
        db.upsert_payment(
            company_name=request.company_name,
            year_month=request.year_month,
            payment_amount=new_value,
        )

        action = "加算" if request.add_mode else "更新"
        message = f"{action}完了: {request.company_name} の {request.year_month} 消滅"

        return UpdatePaymentResponse(
            success=True,
            message=message,
            previous_value=previous_value,
            new_value=new_value,
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/companies-and-months", response_model=CompaniesAndMonthsResponse)
async def get_companies_and_months():
    """会社リストと年月リストを取得（DB由来）

    会社 = 得意先マスタ(有効) ∪ 取引実績のある会社。
    年月 = 納品書または入金が存在する年月。
    """
    try:
        db = MonthlyItemsDB()

        # 会社: マスタ(挿入順)を基本に、取引実績にしか無い会社を後ろに追加
        master = [c["canonical_name"] for c in db.list_companies("sales")]
        seen = set(master)
        companies = list(master)
        for c in db.get_distinct_companies():
            if c not in seen:
                seen.add(c)
                companies.append(c)

        # 年月: 納品書 ∪ 入金
        ym_set = set(db.get_distinct_year_months())
        ym_set.update(p["year_month"] for p in db.list_payments())
        year_months = sorted(ym_set, key=_year_month_sort_key)

        return CompaniesAndMonthsResponse(
            companies=companies,
            year_months=year_months,
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/billing-table", response_model=BillingTableResponse)
async def get_billing_table():
    """売上集計表を DB から再構築（会社×月: 発生/消費税/消滅/残高）"""
    try:
        db = MonthlyItemsDB()

        # 対象の会社・年月（取引 or 入金があるもの）
        totals = db.get_all_monthly_totals()
        payments = db.list_payments()
        ym_set = {t["year_month"] for t in totals} | {p["year_month"] for p in payments}
        year_months = sorted(ym_set, key=_year_month_sort_key)
        company_set = {t["company_name"] for t in totals} | {p["company_name"] for p in payments}
        companies = sorted(company_set)

        if not year_months:
            return BillingTableResponse(headers=[], data=[])

        # ヘッダー: 会社名 + 各月(発生/消費税/消滅/残高)
        headers = ["会社名"]
        for ym in year_months:
            headers += [f"{ym} 発生", f"{ym} 消費税", f"{ym} 消滅", f"{ym} 残高"]

        def _fmt(n: int) -> str:
            return f"{n:,}" if n else ""

        rows: list[list[str]] = []
        for company in companies:
            row = [company]
            for ym in year_months:
                ledger = db.compute_ledger(company, ym)
                row += [
                    _fmt(ledger["subtotal"]),
                    _fmt(ledger["tax"]),
                    _fmt(ledger["payment_amount"]),
                    _fmt(ledger["carried_over"]),
                ]
            rows.append(row)

        return BillingTableResponse(headers=headers, data=rows)

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


class DeliveryNoteOut(BaseModel):
    id: int
    slip_number: str
    date: str
    subtotal: int
    tax: int
    total: int


class DeliveryNotesResponse(BaseModel):
    notes: list[DeliveryNoteOut]


class UpdateDeliveryNoteRequest(BaseModel):
    subtotal: int
    tax: int
    total: int


@router.get("/delivery-notes", response_model=DeliveryNotesResponse)
async def get_delivery_notes(
    company_name: str = Query(...),
    year_month: str = Query(...),
):
    """指定会社・年月の納品書一覧（ID付き）を取得"""
    try:
        db = MonthlyItemsDB()
        notes = db.get_delivery_notes_with_ids(company_name, year_month)
        return DeliveryNotesResponse(
            notes=[DeliveryNoteOut(**n) for n in notes]
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/delivery-notes/{note_id}")
async def update_delivery_note(note_id: int, request: UpdateDeliveryNoteRequest):
    """納品書の金額を更新"""
    try:
        db = MonthlyItemsDB()
        db.update_delivery_note_amounts(
            note_id, request.subtotal, request.tax, request.total
        )
        return {"success": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# --- 納品書 + 明細の取得・編集（業務側でLLM誤抽出を修正するため） ---

class DeliveryItemEdit(BaseModel):
    product_code: str = ""
    product_name: str
    quantity: int
    unit_price: int
    amount: int


class DeliveryNoteWithItems(BaseModel):
    id: int
    slip_number: str
    date: str
    subtotal: int
    tax: int
    total: int
    items: list[DeliveryItemEdit]


class DeliveryNotesWithItemsResponse(BaseModel):
    notes: list[DeliveryNoteWithItems]


class UpdateDeliveryNoteWithItemsRequest(BaseModel):
    """明細を真値として note + items を一括更新。
    subtotal/tax/total は明細から自動計算 (フロント計算値も検証用に受信可)。"""
    date: str
    items: list[DeliveryItemEdit]


@router.get("/delivery-notes-with-items", response_model=DeliveryNotesWithItemsResponse)
async def get_delivery_notes_with_items(
    company_name: str = Query(...),
    year_month: str = Query(...),
):
    """指定会社・年月の納品書一覧（明細付き、ID付き）を取得"""
    try:
        db = MonthlyItemsDB()
        # canonical 名に正規化
        sheets_client = GoogleSheetsClient()
        target_year = _extract_year_from_year_month(year_month)
        canonical = sheets_client.get_canonical_company_name(
            company_name, year=target_year
        )
        if canonical:
            company_name = canonical

        # ID付き納品書取得
        notes_with_id = db.get_delivery_notes_with_ids(company_name, year_month)
        # 明細取得（slip_numberでひもづけ）
        full_notes = db.get_monthly_items(company_name, year_month)
        items_by_slip = {n.slip_number: n.items for n in full_notes}

        result = []
        for n in notes_with_id:
            items = items_by_slip.get(n["slip_number"], [])
            result.append(
                DeliveryNoteWithItems(
                    id=n["id"],
                    slip_number=n["slip_number"],
                    date=n["date"],
                    subtotal=n["subtotal"],
                    tax=n["tax"],
                    total=n["total"],
                    items=[
                        DeliveryItemEdit(
                            product_code=item.product_code,
                            product_name=item.product_name,
                            quantity=item.quantity,
                            unit_price=item.unit_price,
                            amount=item.amount,
                        )
                        for item in items
                    ],
                )
            )
        return DeliveryNotesWithItemsResponse(notes=result)
    except Exception as e:
        import traceback; traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/delivery-notes/{note_id}/full")
async def update_delivery_note_with_items(
    note_id: int,
    request: UpdateDeliveryNoteWithItemsRequest,
):
    """納品書の明細を更新し、subtotal/tax/total を明細から自動計算

    明細を真値とするため、小計は items の amount 合計、消費税は subtotal × 10%、
    合計は subtotal + tax で算出する。frontend で計算ずれが起きても backend で
    正規化される。
    """
    try:
        db = MonthlyItemsDB()

        # 1. note_id から既存 note の情報取得 (company_name, year_month, slip_number)
        with db._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT dn.slip_number, dn.sales_person, mi.company_name, mi.year_month
                FROM delivery_notes dn
                JOIN monthly_invoices mi ON mi.id = dn.monthly_invoice_id
                WHERE dn.id = ?
            """, (note_id,))
            row = cursor.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="納品書が見つかりません")
            slip_number = row["slip_number"]
            sales_person = row["sales_person"] or ""
            company_name = row["company_name"]
            year_month = row["year_month"]

        # 2. 明細から subtotal/tax/total を計算
        subtotal = sum(item.amount for item in request.items)
        # 返品 (subtotal が負) でも +/-10% 同様に計算
        tax = int(subtotal * 0.1) if subtotal >= 0 else -int(abs(subtotal) * 0.1)
        total = subtotal + tax

        # 3. update_monthly_item は slip_number で識別して note+items を完全置換
        delivery_note = DeliveryNote(
            date=request.date,
            company_name=company_name,
            slip_number=slip_number,
            items=[
                DeliveryItem(
                    slip_number=slip_number,
                    product_code=item.product_code,
                    product_name=item.product_name,
                    quantity=item.quantity,
                    unit_price=item.unit_price,
                    amount=item.amount,
                )
                for item in request.items
            ],
            subtotal=subtotal,
            tax=tax,
            total=total,
        )
        db.update_monthly_item(
            company_name=company_name,
            year_month=year_month,
            delivery_note=delivery_note,
            sales_person=sales_person,
        )
        return {
            "success": True,
            "subtotal": subtotal,
            "tax": tax,
            "total": total,
        }
    except HTTPException:
        raise
    except Exception as e:
        import traceback; traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


# --- 売上入金管理 (消滅・繰越) エンドポイント ---


class PaymentRequest(BaseModel):
    company_name: str
    year_month: str  # "YYYY年M月"
    payment_amount: int
    opening_balance: Optional[int] = None
    note: Optional[str] = None
    sync_sheet: bool = True  # シートにもミラー書き込み


class PaymentResponse(BaseModel):
    id: int
    company_name: str
    year_month: str
    payment_amount: int
    opening_balance: int
    note: str
    sheet_synced: bool = False
    sheet_error: str = ""


class LedgerEntryResponse(BaseModel):
    year_month: str
    previous_balance: int
    opening_balance: int
    subtotal: int
    tax: int
    payment_amount: int
    carried_over: int
    notes_count: int


class CompanyLedgerResponse(BaseModel):
    company_name: str
    entries: list[LedgerEntryResponse]


@router.get("/payments")
async def get_payments(
    company_name: str = Query("", description="会社名（空=全件）"),
    year_month: str = Query("", description="年月（空=全件）"),
):
    """消滅（入金）エントリ一覧を取得"""
    try:
        db = MonthlyItemsDB()
        items = db.list_payments(
            company_name=company_name or None,
            year_month=year_month or None,
        )
        return {"payments": items}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/payments", response_model=PaymentResponse)
async def upsert_payment(request: PaymentRequest):
    """消滅を登録/更新（DB + シート dual-write）

    - DB: monthly_payments テーブルに upsert
    - シート: sync_sheet=true の場合、売上集計表の消滅セルに書き込み（best-effort）
    """
    try:
        db = MonthlyItemsDB()

        # 会社名を正規化（シート基準に合わせる）
        sheets_client = GoogleSheetsClient()
        target_year = _extract_year_from_year_month(request.year_month)
        canonical = sheets_client.get_canonical_company_name(
            request.company_name, year=target_year
        )
        company_name = canonical or request.company_name

        saved = db.upsert_payment(
            company_name=company_name,
            year_month=request.year_month,
            payment_amount=request.payment_amount,
            opening_balance=request.opening_balance,
            note=request.note,
        )
        entry = db.get_payment(company_name, request.year_month)

        return PaymentResponse(
            id=saved["id"],
            company_name=company_name,
            year_month=request.year_month,
            payment_amount=entry["payment_amount"],
            opening_balance=entry["opening_balance"],
            note=entry["note"],
            sheet_synced=False,
            sheet_error="",
        )
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/billing-ledger", response_model=CompanyLedgerResponse)
async def get_billing_ledger(
    company_name: str = Query(...),
    year: int = Query(..., ge=2020, le=2099),
):
    """指定会社・年の12ヶ月分の台帳をDBから計算して返す"""
    try:
        db = MonthlyItemsDB()
        entries = []
        for month in range(1, 13):
            ym = f"{year}年{month}月"
            ledger = db.compute_ledger(company_name, ym)
            entries.append(LedgerEntryResponse(**ledger))
        return CompanyLedgerResponse(company_name=company_name, entries=entries)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
