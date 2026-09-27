"""得意先/仕入先マスタ (company_master) の管理エンドポイント

P1: canonical 会社名の真値を Google Sheets / ハードコードから DB へ移行。
画面から得意先・仕入先を追加・編集・無効化できるようにする。
"""
from typing import Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from src.database import MonthlyItemsDB, SimilarCompanyError
from src.payment_terms import (
    PaymentTermsError,
    normalize_closing_day,
    normalize_payment_day,
)

router = APIRouter()

VALID_DOMAINS = ("sales", "purchase")


class CompanyMasterItem(BaseModel):
    id: int
    domain: str
    canonical_name: str
    postal_code: str
    address: str
    department: str
    taxable: Optional[bool]
    is_active: bool
    created_at: str
    updated_at: str
    # 支払条件: 締め日("月末"|"N日"|"")・支払日("翌月末"|"翌月N日"|...|"")
    closing_day: str = ""
    payment_day: str = ""


class CompanyMasterListResponse(BaseModel):
    companies: list[CompanyMasterItem]


class CreateCompanyRequest(BaseModel):
    domain: str
    canonical_name: str
    postal_code: str = ""
    address: str = ""
    department: str = ""
    taxable: Optional[bool] = None
    # 類似会社の警告（409）を確認済みで、それでも追加する場合 True
    force: bool = False
    closing_day: str = ""
    payment_day: str = ""


class SimilarCompanyItem(BaseModel):
    id: int
    canonical_name: str
    postal_code: str
    address: str
    reasons: list[str]


class UpdateCompanyRequest(BaseModel):
    postal_code: Optional[str] = None
    address: Optional[str] = None
    department: Optional[str] = None
    # taxable は NULL も有効値（曖昧）なので、変更したいときだけ set_taxable=True
    taxable: Optional[bool] = None
    set_taxable: bool = False
    is_active: Optional[bool] = None
    # None は変更なし、"" は未設定に戻す
    closing_day: Optional[str] = None
    payment_day: Optional[str] = None


def _normalize_terms(closing_day: Optional[str], payment_day: Optional[str]):
    """締め日/支払日を正規形にする。不正なら 400"""
    try:
        c = None if closing_day is None else normalize_closing_day(closing_day)
        pdy = None if payment_day is None else normalize_payment_day(payment_day)
        return c, pdy
    except PaymentTermsError as e:
        raise HTTPException(status_code=400, detail=str(e))


def _validate_domain(domain: str):
    if domain not in VALID_DOMAINS:
        raise HTTPException(
            status_code=400,
            detail=f"domain は {VALID_DOMAINS} のいずれかを指定してください",
        )


@router.get("/company-master", response_model=CompanyMasterListResponse)
async def list_company_master(domain: str, include_inactive: bool = False):
    """得意先/仕入先マスタ一覧を取得"""
    _validate_domain(domain)
    try:
        db = MonthlyItemsDB()
        companies = db.list_companies(domain, include_inactive=include_inactive)
        return CompanyMasterListResponse(
            companies=[CompanyMasterItem(**c) for c in companies]
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/company-master", response_model=CompanyMasterItem)
async def create_company_master(request: CreateCompanyRequest):
    """得意先/仕入先を追加（類似会社があれば 409 で警告、force=True で強行）"""
    _validate_domain(request.domain)
    closing_day, payment_day = _normalize_terms(request.closing_day, request.payment_day)
    try:
        db = MonthlyItemsDB()
        created = db.add_company(
            domain=request.domain,
            canonical_name=request.canonical_name,
            postal_code=request.postal_code,
            address=request.address,
            department=request.department,
            taxable=request.taxable,
            force=request.force,
            closing_day=closing_day or "",
            payment_day=payment_day or "",
        )
        return CompanyMasterItem(**created)
    except SimilarCompanyError as e:
        # 類似会社あり → 409 で候補を返す（フロントで警告 → force=True で再送）
        raise HTTPException(
            status_code=409,
            detail={
                "error": str(e),
                "similar": [
                    SimilarCompanyItem(
                        id=s["id"],
                        canonical_name=s["canonical_name"],
                        postal_code=s["postal_code"],
                        address=s["address"],
                        reasons=s["reasons"],
                    ).model_dump()
                    for s in e.similar
                ],
            },
        )
    except ValueError as e:
        # 重複・表記ゆれ・空名は 400（業務エラー）
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.patch("/company-master/{company_id}", response_model=CompanyMasterItem)
async def update_company_master(company_id: int, request: UpdateCompanyRequest):
    """得意先/仕入先を編集（住所・事業部・課税区分・有効/無効）"""
    closing_day, payment_day = _normalize_terms(request.closing_day, request.payment_day)
    try:
        db = MonthlyItemsDB()
        updated = db.update_company(
            company_id,
            postal_code=request.postal_code,
            address=request.address,
            department=request.department,
            taxable=request.taxable,
            set_taxable=request.set_taxable,
            is_active=request.is_active,
            closing_day=closing_day,
            payment_day=payment_day,
        )
        if updated is None:
            raise HTTPException(status_code=404, detail="対象が見つかりません")
        return CompanyMasterItem(**updated)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/company-master/{company_id}", response_model=CompanyMasterItem)
async def deactivate_company_master(company_id: int):
    """得意先/仕入先を無効化（論理削除・過去伝票は壊さない）"""
    try:
        db = MonthlyItemsDB()
        updated = db.deactivate_company(company_id)
        if updated is None:
            raise HTTPException(status_code=404, detail="対象が見つかりません")
        return CompanyMasterItem(**updated)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
