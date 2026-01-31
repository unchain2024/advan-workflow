"""請求管理関連のエンドポイント"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from src.sheets_client import GoogleSheetsClient, PreviousBilling, normalize_company_name
from src.pdf_extractor import DeliveryNote, DeliveryItem
from src.config import BILLING_SPREADSHEET_ID, BILLING_SHEET_NAME

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
    delivery_note: DeliveryNoteRequest
    previous_billing: PreviousBillingRequest


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

        # PreviousBillingオブジェクトを再構築
        previous_billing = PreviousBilling(
            previous_amount=request.previous_billing.previous_amount,
            payment_received=request.previous_billing.payment_received,
            carried_over=request.previous_billing.carried_over,
        )

        # Google Sheetsに保存
        sheets_client = GoogleSheetsClient()
        sheets_client.save_billing_record(
            company_name=request.company_name,
            previous_billing=previous_billing,
            delivery_note=delivery_note,
        )

        return {
            "success": True,
            "message": f"**売上集計表** の {request.company_name} ({request.year_month}) を更新しました",
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/update-payment", response_model=UpdatePaymentResponse)
async def update_payment(request: UpdatePaymentRequest):
    """入金額（消滅）を更新"""

    try:
        sheets_client = GoogleSheetsClient()
        sheet = sheets_client.client.open_by_key(BILLING_SPREADSHEET_ID).worksheet(
            BILLING_SHEET_NAME
        )

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

        # 会社の行を検索（正規化マッチング）
        col_a_values = sheet.col_values(1)
        normalized_search = normalize_company_name(request.company_name)

        company_row = None
        for i, cell_value in enumerate(col_a_values[2:], start=3):
            normalized_cell = normalize_company_name(str(cell_value))
            if normalized_search in normalized_cell or normalized_cell in normalized_search:
                company_row = i
                break

        if company_row is None:
            raise HTTPException(
                status_code=404,
                detail=f"会社 '{request.company_name}' が見つかりません",
            )

        # 消滅列（年月列 + 2）
        shoumetsu_col = month_col_index + 2

        # 現在の値を取得
        current_value_str = sheet.cell(company_row, shoumetsu_col).value or ""

        # 既存値をパース
        def parse_amount(value_str: str) -> int:
            if not value_str:
                return 0
            cleaned = str(value_str).replace(',', '').replace(' ', '').replace('¥', '').replace('円', '')
            try:
                return int(float(cleaned))
            except ValueError:
                return 0

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
    """会社リストと年月リストを取得"""

    try:
        sheets_client = GoogleSheetsClient()
        sheet = sheets_client.client.open_by_key(BILLING_SPREADSHEET_ID).worksheet(
            BILLING_SHEET_NAME
        )

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
    """売上集計表のデータを取得"""

    try:
        sheets_client = GoogleSheetsClient()
        sheet = sheets_client.client.open_by_key(BILLING_SPREADSHEET_ID).worksheet(
            BILLING_SHEET_NAME
        )

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
