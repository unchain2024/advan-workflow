"""請求管理関連のエンドポイント"""
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from typing import Optional

import re

from src.sheets_client import GoogleSheetsClient, PreviousBilling, _find_company_row, match_company_name, parse_amount
from src.pdf_extractor import DeliveryNote, DeliveryItem
from src.database import MonthlyItemsDB
from src.config import BILLING_SPREADSHEET_ID


def _extract_year_from_year_month(year_month: str) -> int:
    """年月文字列から年を抽出（例: '2025年3月' → 2025）"""
    match = re.match(r'(\d{4})', year_month)
    if match:
        return int(match.group(1))
    from datetime import datetime
    return datetime.now().year

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
        if canonical:
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

        # Layer 2: シート書込（DB成功後にbest-effort、失敗しても DB は保持）
        sheet_errors = []
        for delivery_note in delivery_notes:
            try:
                sheets_client.save_billing_record(
                    company_name=company_name,
                    previous_billing=previous_billing,
                    delivery_note=delivery_note,
                    target_year_month=year_month_str,
                )
            except Exception as sheet_err:
                sheet_errors.append(f"{delivery_note.slip_number}: {sheet_err}")
                print(f"    シート書込エラー（続行）: {sheet_err}")

        message = f"**売上集計表** の {company_name} ({request.year_month}) を更新しました（{saved_count}件）"
        if sheet_errors:
            message += f"\n⚠️ シート書込で {len(sheet_errors)} 件のエラー: {'; '.join(sheet_errors)}"

        return {
            "success": True,
            "message": message,
            "saved_count": saved_count,
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/update-payment", response_model=UpdatePaymentResponse)
async def update_payment(request: UpdatePaymentRequest):
    """入金額（消滅）を更新"""

    try:
        sheets_client = GoogleSheetsClient()
        year = _extract_year_from_year_month(request.year_month)
        sheet = sheets_client._get_billing_sheet_by_year(year)

        # 年月の列を検索
        row1_values = sheet.row_values(1)
        month_col_index = None
        for i, cell_value in enumerate(row1_values):
            if request.year_month in str(cell_value):
                month_col_index = i + 1
                break

        if month_col_index is None:
            raise HTTPException(
                status_code=404,
                detail=f"年月 '{request.year_month}' が見つかりません",
            )

        # 会社の行を検索（完全一致優先マッチング）
        col_a_values = sheet.col_values(1)
        company_row = _find_company_row(request.company_name, col_a_values, start_row=3)

        if company_row is None:
            raise HTTPException(
                status_code=404,
                detail=f"会社 '{request.company_name}' が見つかりません",
            )

        # 消滅列（年月列 + 2）
        shoumetsu_col = month_col_index + 2

        # 現在の値を取得（モジュールレベルの parse_amount を使用）
        current_value_str = sheet.cell(company_row, shoumetsu_col).value or ""
        current_value = parse_amount(current_value_str)

        # 新しい値を計算
        if request.add_mode:
            new_value = current_value + request.payment_amount
            action = "加算"
        else:
            new_value = request.payment_amount
            action = "更新"

        # 更新
        sheet.update_cell(company_row, shoumetsu_col, new_value)

        return UpdatePaymentResponse(
            success=True,
            message=f"{action}完了: {request.company_name} の {request.year_month} 消滅",
            previous_value=current_value,
            new_value=new_value,
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/companies-and-months", response_model=CompaniesAndMonthsResponse)
async def get_companies_and_months():
    """会社リストと年月リストを取得（現在の年のシートから）"""

    try:
        from datetime import datetime
        sheets_client = GoogleSheetsClient()
        current_year = datetime.now().year
        sheet = sheets_client._get_billing_sheet_by_year(current_year)

        # 会社リスト（A列）- 重複を除去
        col_a = sheet.col_values(1)
        companies_all = [c for c in col_a[2:] if c]  # ヘッダー除外

        # 順序を保ちながら重複を除去
        seen_companies = set()
        companies = []
        for c in companies_all:
            if c not in seen_companies:
                seen_companies.add(c)
                companies.append(c)

        # 年月リスト（1行目）- 重複を除去
        row1 = sheet.row_values(1)
        year_months_all = [ym for ym in row1 if "年" in ym and "月" in ym]

        # 順序を保ちながら重複を除去
        seen = set()
        year_months = []
        for ym in year_months_all:
            if ym not in seen:
                seen.add(ym)
                year_months.append(ym)

        return CompaniesAndMonthsResponse(
            companies=companies,
            year_months=year_months,
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/billing-table", response_model=BillingTableResponse)
async def get_billing_table():
    """売上集計表のデータを取得（現在の年のシートから）"""

    try:
        from datetime import datetime
        sheets_client = GoogleSheetsClient()
        current_year = datetime.now().year
        sheet = sheets_client._get_billing_sheet_by_year(current_year)

        # 全ての行を取得
        data = sheet.get_all_values()

        if not data or len(data) == 0:
            return BillingTableResponse(headers=[], data=[])

        headers = data[0]
        rows = data[1:]

        return BillingTableResponse(
            headers=headers,
            data=rows,
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# --- 乖離チェック＆修正エンドポイント ---

class DiscrepancyItem(BaseModel):
    company_name: str
    year_month: str
    db_subtotal: int
    db_tax: int
    sheet_subtotal: int
    sheet_tax: int


class CheckDiscrepancyResponse(BaseModel):
    discrepancies: list[DiscrepancyItem]


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


@router.get("/check-discrepancy", response_model=CheckDiscrepancyResponse)
async def check_discrepancy():
    """DB の月次合計とシートの金額を比較し、乖離がある項目を返す"""
    try:
        from datetime import datetime

        db = MonthlyItemsDB()
        sheets_client = GoogleSheetsClient()

        # DB の会社・月ごとの合計を取得
        db_totals = db.get_all_monthly_totals()

        if not db_totals:
            return CheckDiscrepancyResponse(discrepancies=[])

        # DB のデータから必要な年を特定
        years = set()
        for item in db_totals:
            match = re.match(r'(\d{4})', item["year_month"])
            if match:
                years.add(int(match.group(1)))

        if not years:
            years = {datetime.now().year}

        # シートの金額を全年分取得
        sheet_amounts: list[dict] = []
        for year in years:
            try:
                sheet_amounts.extend(sheets_client.get_billing_amounts(year))
            except Exception as e:
                print(f"    シート読み取りエラー (年={year}): {e}")

        # シート金額を year_month ごとに整理
        sheet_by_month: dict[str, list[dict]] = {}
        for item in sheet_amounts:
            ym = item["year_month"]
            if ym not in sheet_by_month:
                sheet_by_month[ym] = []
            sheet_by_month[ym].append(item)

        # DB月次合計とシートを突き合わせ
        discrepancies = []
        for db_item in db_totals:
            year_month = db_item["year_month"]

            sheet_data = None
            month_entries = sheet_by_month.get(year_month, [])
            if month_entries:
                sheet_names = [e["company_name"] for e in month_entries]
                matched = match_company_name(db_item["company_name"], sheet_names)
                if matched:
                    for e in month_entries:
                        if e["company_name"] == matched:
                            sheet_data = {"subtotal": e["subtotal"], "tax": e["tax"]}
                            break

            if sheet_data is None:
                sheet_data = {"subtotal": 0, "tax": 0}

            # 乖離があるもののみ返す
            if (db_item["subtotal"] != sheet_data["subtotal"]
                    or db_item["tax"] != sheet_data["tax"]):
                discrepancies.append(DiscrepancyItem(
                    company_name=db_item["company_name"],
                    year_month=year_month,
                    db_subtotal=db_item["subtotal"],
                    db_tax=db_item["tax"],
                    sheet_subtotal=sheet_data["subtotal"],
                    sheet_tax=sheet_data["tax"],
                ))

        return CheckDiscrepancyResponse(discrepancies=discrepancies)

    except Exception as e:
        print(f"乖離チェックエラー: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


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
