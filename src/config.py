"""設定ファイル"""
import os
import json
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# パス設定
BASE_DIR = Path(__file__).parent.parent
INPUT_DIR = BASE_DIR / "input"
OUTPUT_DIR = BASE_DIR / "output"
CREDENTIALS_PATH = BASE_DIR / "credentials.json"
COMPANY_CONFIG_PATH = BASE_DIR / "company_config.json"

# Google Sheets設定
# 会社情報マスター（会社名、事業部、郵便番号、住所、ビル名）
COMPANY_MASTER_SPREADSHEET_ID = os.getenv("COMPANY_MASTER_SPREADSHEET_ID", "")
COMPANY_MASTER_SHEET_NAME = os.getenv("COMPANY_MASTER_SHEET_NAME", "マスター")

# 売上集計表（請求管理スプレッドシート）
BILLING_SPREADSHEET_ID = os.getenv("BILLING_SPREADSHEET_ID", "")
BILLING_SHEET_NAME = os.getenv("BILLING_SHEET_NAME", "請求管理")

# 仕入れ管理スプレッドシート
PURCHASE_SPREADSHEET_ID = os.getenv("PURCHASE_SPREADSHEET_ID", "")
PURCHASE_SHEET_NAME = os.getenv("PURCHASE_SHEET_NAME", "仕入れ管理")

# 締め日マスタースプレッドシート
PURCHASE_TERMS_SPREADSHEET_ID = os.getenv("PURCHASE_TERMS_SPREADSHEET_ID", "")
PURCHASE_TERMS_SHEET_NAME = os.getenv("PURCHASE_TERMS_SHEET_NAME", "締め日マスター")


# 自社情報（JSON管理）
def load_company_config() -> dict:
    """自社情報をJSONファイルから読み込む"""
    if COMPANY_CONFIG_PATH.exists():
        try:
            with open(COMPANY_CONFIG_PATH, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            print(f"警告: company_config.jsonの読み込みエラー: {e}")

    # JSONファイルが存在しない場合は、.envから初期値を作成
    default_config = {
        "registration_number": os.getenv("OWN_REGISTRATION_NUMBER", "T0000000000000"),
        "company_name": os.getenv("OWN_COMPANY_NAME", "株式会社サンプル"),
        "postal_code": os.getenv("OWN_POSTAL_CODE", "000-0000"),
        "address": os.getenv("OWN_ADDRESS", "東京都〇〇区〇〇1-2-3"),
        "phone": os.getenv("OWN_PHONE", "00-0000-0000"),
        "bank_info": os.getenv("OWN_BANK_INFO", "〇〇銀行 △△支店 普通 0000000"),
    }

    # JSONファイルに保存
    save_company_config(default_config)
    return default_config


def save_company_config(config: dict) -> bool:
    """自社情報をJSONファイルに保存"""
    try:
        with open(COMPANY_CONFIG_PATH, 'w', encoding='utf-8') as f:
            json.dump(config, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        print(f"エラー: company_config.jsonの保存エラー: {e}")
        return False


OWN_COMPANY = load_company_config()

# PDF設定（日本語フォント）
# デフォルト: プロジェクト内のIPAexゴシックフォントを使用
PDF_FONT_PATH = os.getenv("PDF_FONT_PATH", str(BASE_DIR / "fonts" / "ipaexg.ttf"))

# Gemini API設定
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")  # 構造化抽出用（最新）
