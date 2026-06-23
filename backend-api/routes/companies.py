"""得意先/仕入先マスタ (company_master) の管理エンドポイント

P1: canonical 会社名の真値を Google Sheets / ハードコードから DB へ移行。
画面から得意先・仕入先を追加・編集・無効化できるようにする。
"""
from typing import Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from src.database import MonthlyItemsDB

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


class CompanyMasterListResponse(BaseModel):
    companies: list[CompanyMasterItem]


class CreateCompanyRequest(BaseModel):
    domain: str
    canonical_name: str
    postal_code: str = ""
    address: str = ""
    department: str = ""
    taxable: Optional[bool] = None


class UpdateCompanyRequest(BaseModel):
    postal_code: Optional[str] = None
    address: Optional[str] = None
    department: Optional[str] = None
    # taxable は NULL も有効値（曖昧）なので、変更したいときだけ set_taxable=True
    taxable: Optional[bool] = None
    set_taxable: bool = False
    is_active: Optional[bool] = None


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
    """得意先/仕入先を追加"""
    _validate_domain(request.domain)
    try:
        db = MonthlyItemsDB()
        created = db.add_company(
            domain=request.domain,
            canonical_name=request.canonical_name,
            postal_code=request.postal_code,
            address=request.address,
            department=request.department,
            taxable=request.taxable,
        )
        return CompanyMasterItem(**created)
    except ValueError as e:
        # 重複・表記ゆれ・空名は 400（業務エラー）
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.patch("/company-master/{company_id}", response_model=CompanyMasterItem)
async def update_company_master(company_id: int, request: UpdateCompanyRequest):
    """得意先/仕入先を編集（住所・事業部・課税区分・有効/無効）"""
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
