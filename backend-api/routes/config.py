"""設定関連のエンドポイント"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from src.config import load_company_config, save_company_config

router = APIRouter()


class CompanyConfig(BaseModel):
    registration_number: str
    company_name: str
    postal_code: str
    address: str
    phone: str
    bank_info: str


@router.get("/company-config", response_model=CompanyConfig)
async def get_company_config():
    """自社情報を取得"""

    try:
        config = load_company_config()

        return CompanyConfig(
            registration_number=config.get("registration_number", ""),
            company_name=config.get("company_name", ""),
            postal_code=config.get("postal_code", ""),
            address=config.get("address", ""),
            phone=config.get("phone", ""),
            bank_info=config.get("bank_info", ""),
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/company-config")
async def save_company_config_endpoint(config: CompanyConfig):
    """自社情報を保存"""

    try:
        config_dict = {
            "registration_number": config.registration_number,
            "company_name": config.company_name,
            "postal_code": config.postal_code,
            "address": config.address,
            "phone": config.phone,
            "bank_info": config.bank_info,
        }

        success = save_company_config(config_dict)

        if not success:
            raise HTTPException(status_code=500, detail="保存に失敗しました")

        return {
            "success": True,
            "message": "自社情報を保存しました",
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
