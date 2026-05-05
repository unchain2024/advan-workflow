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
from src.canonical_companies import (
    list_canonicals,
    get_purchase_taxability_hint,
    resolve_purchase_taxability,
    PURCHASE_TAXABILITY_RULES,
)

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
    detected_indicators: list[str] = []
    # canonical 化結果。False なら UI 側で picker 表示
    company_matched: bool = True
    candidate_canonicals: list[str] = []


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
    # process-pdf 段階で LLM が検出したキーワード。save 時に Layer 3 再適用に使用
    detected_indicators: list[str] = []


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


class SyncPurchaseSheetsResponse(BaseModel):
    synced_count: int
    failed: list[str]
    message: str


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


def _convert_purchase_invoice(
    invoice: PurchaseInvoice,
    company_matched: bool = True,
    candidate_canonicals: Optional[list[str]] = None,
) -> PurchaseInvoiceResponse:
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
        detected_indicators=invoice.detected_indicators,
        company_matched=company_matched,
        candidate_canonicals=candidate_canonicals or [],
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

        # Phase 5a/5b: canonical 解決 + 課税/非課税 hint を適用
        # ファイル名ヒントで親/子を判別、PURCHASE_TAXABILITY 登録会社は LLM 抽出値を上書き
        # canonical 化結果を invoice ごとに記録して response に含める (Phase 5d': UI即時picker表示)
        sheets_client = GoogleSheetsClient()
        canonical_match_results: list[tuple[bool, list[str]]] = []  # (matched, candidates)
        for inv in invoices:
            raw_supplier = inv.supplier_name
            if not raw_supplier:
                # supplier_name 自体が空 → mismatch 扱い、全候補返す
                canonical_match_results.append((False, list_canonicals('purchase')))
                continue
            canonical = sheets_client.get_canonical_purchase_company_name(
                raw_supplier, filename=file.filename
            )
            if not canonical:
                # canonical 化失敗 → UI に picker を出してもらうために候補を返す
                print(f"  [仕入canonical不一致] '{raw_supplier}' → 候補返却")
                canonical_match_results.append((False, list_canonicals('purchase')))
                continue

            if canonical != raw_supplier:
                print(f"  [仕入正規化] '{raw_supplier}' → '{canonical}'")
            inv.supplier_name = canonical
            canonical_match_results.append((True, []))

            # Layer 2: シート分類が確定している会社は無条件で上書き
            hint = get_purchase_taxability_hint(canonical)
            if hint is not None:
                if hint != inv.is_taxable:
                    print(
                        f"  [課税区分上書き L2/シート固定] '{canonical}': "
                        f"LLM抽出 is_taxable={inv.is_taxable} → シート定義 {hint}"
                    )
                    inv.is_taxable = hint

            # Layer 3: 混在会社は detected_indicators + 税0 シグナルで動的判定
            if canonical in {
                '（株）ヴェスト', '（株）マテックス', '㈱有延商店',
                '日本マート㈱', '㈱フクイ', 'リーウェイジャパン㈱',
            }:
                final_taxable, reason = resolve_purchase_taxability(
                    canonical_name=canonical,
                    detected_indicators=inv.detected_indicators,
                    tax=inv.tax,
                    total=inv.total,
                    llm_is_taxable=inv.is_taxable,
                )
                if final_taxable != inv.is_taxable:
                    print(
                        f"  [課税区分上書き L3/動的ルール] '{canonical}': "
                        f"LLM抽出 is_taxable={inv.is_taxable} → ルール判定 {final_taxable} "
                        f"(理由: {reason}, indicators={inv.detected_indicators})"
                    )
                    inv.is_taxable = final_taxable
                else:
                    print(
                        f"  [課税区分確認 L3] '{canonical}': "
                        f"LLM抽出と一致 is_taxable={final_taxable} ({reason}, "
                        f"indicators={inv.detected_indicators})"
                    )

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
            purchase_invoices=[
                _convert_purchase_invoice(
                    inv,
                    company_matched=matched,
                    candidate_canonicals=candidates,
                )
                for inv, (matched, candidates) in zip(invoices, canonical_match_results)
            ],
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
            print(
                f"  [{i}] slip={note.slip_number}, subtotal={note.subtotal}, "
                f"tax={note.tax}, total={note.total}, "
                f"is_taxable={note.is_taxable}, detected_indicators={note.detected_indicators}"
            )

        db = MonthlyItemsDB()

        # 1. 冪等性チェック
        if request.request_id and db.check_request_id(request.request_id):
            return SavePurchaseResponse(
                success=True,
                message="この保存リクエストは既に処理済みです",
                saved_count=0,
            )

        # 2. 会社名正規化（Phase 1: canonical 不一致は 400 reject、auto-add 厳禁）
        sheets_client = GoogleSheetsClient()
        company_name = request.company_name
        target_year = _extract_year_from_year_month(request.year_month)
        canonical = sheets_client.get_canonical_purchase_company_name(
            company_name, year=target_year
        )
        if not canonical:
            raise HTTPException(
                status_code=400,
                detail={
                    "error": "company_not_matched",
                    "extracted_name": company_name,
                    "candidates": list_canonicals("purchase"),
                    "message": f"仕入先 '{company_name}' が canonical マスターに一致しませんでした。仕入先名を編集して再試行してください。",
                },
            )
        company_name = canonical

        # 3. 年月フォーマット変換
        year_month_str = request.year_month
        if '-' in year_month_str and '年' not in year_month_str:
            parts = year_month_str.split('-')
            year_month_str = f"{int(parts[0])}年{int(parts[1])}月"

        # 4. PurchaseInvoiceオブジェクトリストを構築
        # Phase 5d': save 時にも canonical 化済 company_name を使って Layer 2/3 を再適用する。
        # process-pdf 段階で canonical 化失敗してピッカー選択された invoice は、選択時点で
        # supplier_name は更新されたが is_taxable は LLM 判定のままなので、ここで補正する。
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

            # Layer 2: シート固定の hint があれば上書き
            is_taxable = note_req.is_taxable
            hint = get_purchase_taxability_hint(company_name)
            if hint is not None and hint != is_taxable:
                print(
                    f"  [save時 課税区分上書き L2] '{company_name}' slip={note_req.slip_number}: "
                    f"フロント送信 is_taxable={is_taxable} → シート定義 {hint}"
                )
                is_taxable = hint

            # Layer 3: 動的ルール (混在会社) を再適用
            if company_name in PURCHASE_TAXABILITY_RULES:
                final_taxable, reason = resolve_purchase_taxability(
                    canonical_name=company_name,
                    detected_indicators=note_req.detected_indicators,
                    tax=note_req.tax,
                    total=note_req.total,
                    llm_is_taxable=is_taxable,
                )
                if final_taxable != is_taxable:
                    print(
                        f"  [save時 課税区分上書き L3] '{company_name}' slip={note_req.slip_number}: "
                        f"{is_taxable} → ルール判定 {final_taxable} ({reason}, indicators={note_req.detected_indicators})"
                    )
                is_taxable = final_taxable

            purchase_invoices.append(PurchaseInvoice(
                date=note_req.date,
                supplier_name=company_name,
                slip_number=note_req.slip_number,
                items=items,
                subtotal=note_req.subtotal,
                tax=note_req.tax,
                total=note_req.total,
                is_taxable=is_taxable,
                detected_indicators=note_req.detected_indicators,
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

        # 6. Layer 1: DB一括保存（DB-as-truth: シート障害でもDBは保持）
        saved_count = db.save_purchase_batch(
            company_name=company_name,
            year_month=year_month_str,
            purchase_invoices=purchase_invoices,
            sales_person=request.sales_person,
            request_id=request.request_id,
        )

        # 7. Layer 2: シート書込（DB成功後にbest-effort、失敗しても DB は保持）
        # Phase 2: per-note 加算ではなく、DB集計値で「上書き」する（再保存で 2倍/3倍にならない）
        # 仕入シートは課税/非課税で別行 → 該当する側のみ 1 回ずつ書込
        sheet_errors: list[str] = []
        agg = db.get_purchase_amounts(company_name, year_month_str)

        if agg["taxable_subtotal"] > 0 or any(pi.is_taxable for pi in purchase_invoices):
            try:
                sheets_client.save_purchase_record(
                    supplier_name=company_name,
                    target_year_month=year_month_str,
                    subtotal=agg["taxable_subtotal"],
                    tax=agg["taxable_tax"],
                    is_taxable=True,
                )
            except Exception as sheet_err:
                sheet_errors.append(f"課税: {sheet_err}")
                print(f"    [SHEET_WRITE] 仕入シート（課税）上書きエラー（DB保持）: {sheet_err}")

        if agg["nontaxable_subtotal"] > 0 or any(not pi.is_taxable for pi in purchase_invoices):
            try:
                sheets_client.save_purchase_record(
                    supplier_name=company_name,
                    target_year_month=year_month_str,
                    subtotal=agg["nontaxable_subtotal"],
                    tax=agg["nontaxable_tax"],
                    is_taxable=False,
                )
            except Exception as sheet_err:
                sheet_errors.append(f"非課税: {sheet_err}")
                print(f"    [SHEET_WRITE] 仕入シート（非課税）上書きエラー（DB保持）: {sheet_err}")

        if sheet_errors:
            message = (
                f"DB保存成功（{saved_count}件）。"
                f"\n⚠️ 仕入シート書込で {len(sheet_errors)} 件のエラー（DB は正常）: "
                f"{'; '.join(sheet_errors)}"
            )
            warning = f"仕入シート書込エラー: {'; '.join(sheet_errors)}"
        else:
            message = f"DB保存成功（{saved_count}件）。仕入シートも更新しました ({company_name} {request.year_month})"
            warning = ""

        return SavePurchaseResponse(
            success=True,
            message=message,
            saved_count=saved_count,
            warning=warning,
        )

    except HTTPException:
        raise
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/update-purchase-payment", response_model=UpdatePurchasePaymentResponse)
async def update_purchase_payment(request: UpdatePurchasePaymentRequest):
    """仕入入金（消滅）を更新

    Phase 1: DB を source of truth として upsert 後、シート書込みを best-effort で実行。
    シート障害時は warning ログのみで 200 を返す（DB の確定値を維持）。
    """

    try:
        db = MonthlyItemsDB()

        # Layer 1: DB upsert（previous_value は upsert 前の DB 値、new_value は upsert 後の DB 値）
        prev = db.get_purchase_payment(request.company_name, request.year_month)
        previous_value = (prev or {}).get("payment_amount", 0)

        upserted = db.upsert_purchase_payment(
            company_name=request.company_name,
            year_month=request.year_month,
            payment_amount=request.payment_amount,
            add_mode=request.add_mode,
        )
        new_value = upserted["new_value"]

        # Layer 2: シート書込（best-effort、失敗しても DB は保持）
        sheet_warning = ""
        try:
            sheets_client = GoogleSheetsClient()
            sheets_client.update_purchase_payment(
                company_name=request.company_name,
                year_month=request.year_month,
                payment_amount=request.payment_amount,
                add_mode=request.add_mode,
            )
        except Exception as sheet_err:
            sheet_warning = f"シート書込エラー（DB は正常）: {sheet_err}"
            print(f"    [SHEET_WRITE] 仕入入金シート更新エラー（続行）: {sheet_err}")

        action = "加算" if request.add_mode else "更新"
        message = f"{action}完了: {request.company_name} の {request.year_month} 消滅"
        if sheet_warning:
            message += f"\n⚠️ {sheet_warning}"

        return UpdatePurchasePaymentResponse(
            success=True,
            message=message,
            previous_value=previous_value,
            new_value=new_value,
        )

    except HTTPException:
        raise
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))



@router.post("/sync-purchase-sheets-from-db", response_model=SyncPurchaseSheetsResponse)
async def sync_purchase_sheets_from_db():
    """DB の集計値で仕入シートを上書き同期（Phase 2: DB-as-truth 強制再同期）

    purchase_invoices に存在する全 (仕入先, 年月) について、課税/非課税別の発生・消費税
    を仕入シートの該当セルに上書きする。
    """
    try:
        db = MonthlyItemsDB()
        sheets_client = GoogleSheetsClient()
        totals = db.get_all_purchase_monthly_totals()
        synced = 0
        failed: list[str] = []
        for item in totals:
            company = item["company_name"]
            ym = item["year_month"]
            if item["taxable_subtotal"] > 0:
                try:
                    sheets_client.save_purchase_record(
                        supplier_name=company,
                        target_year_month=ym,
                        subtotal=item["taxable_subtotal"],
                        tax=item["taxable_tax"],
                        is_taxable=True,
                    )
                    synced += 1
                except Exception as e:
                    failed.append(f"{company} {ym} (課税): {e}")
            if item["nontaxable_subtotal"] > 0:
                try:
                    sheets_client.save_purchase_record(
                        supplier_name=company,
                        target_year_month=ym,
                        subtotal=item["nontaxable_subtotal"],
                        tax=item["nontaxable_tax"],
                        is_taxable=False,
                    )
                    synced += 1
                except Exception as e:
                    failed.append(f"{company} {ym} (非課税): {e}")
        message = (
            f"仕入 DB → シート同期完了: 成功 {synced} 件" +
            (f"、失敗 {len(failed)} 件" if failed else "")
        )
        return SyncPurchaseSheetsResponse(synced_count=synced, failed=failed, message=message)
    except Exception as e:
        import traceback; traceback.print_exc()
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
