"""Google Sheets連携モジュール"""
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional
import os
import re
import json
import base64

import gspread
from google.oauth2.service_account import Credentials as ServiceAccountCredentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
import pickle

# Streamlit対応
try:
    import streamlit as st
    HAS_STREAMLIT = True
except ImportError:
    HAS_STREAMLIT = False

from .config import (
    BILLING_SHEET_NAME,
    BILLING_SPREADSHEET_ID,
    COMPANY_MASTER_SHEET_NAME,
    COMPANY_MASTER_SPREADSHEET_ID,
    CREDENTIALS_PATH,
    PURCHASE_SPREADSHEET_ID,
    PURCHASE_SHEET_NAME,
    PURCHASE_TERMS_SPREADSHEET_ID,
    PURCHASE_TERMS_SHEET_NAME,
)
from .pdf_extractor import DeliveryNote


def normalize_company_name(name: str) -> str:
    """会社名を正規化（法人格・敬称・読み仮名を除去）

    例:
    - "株式会社SIM" → "SIM"
    - "（株）SIM 御中" → "SIM"
    - "株式会社SIM（シム）" → "SIM"
    """
    if not name:
        return ""

    # 法人格を除去
    name = re.sub(r'株式会社|有限会社|\(株\)|（株）|\(有\)|（有）', '', name)

    # 敬称を除去
    name = re.sub(r'御中|様|殿', '', name)

    # カッコ内の読み仮名を除去（例: （シム）, (シム), 【シム】など）
    name = re.sub(r'[（(【].*?[）)】]', '', name)

    # 空白文字を除去
    name = re.sub(r'\s+', '', name)

    return name.strip()


@dataclass
class CompanyInfo:
    """会社情報"""
    company_name: str
    postal_code: str
    address: str
    department: str  # 事業部名


@dataclass
class PreviousBilling:
    """前月の請求情報"""
    previous_amount: int  # 前回御請求額
    payment_received: int  # 御入金額
    carried_over: int  # 差引繰越残高
    sales_amount: int = 0  # 前月の売上額
    tax_amount: int = 0  # 前月の消費税額
    current_amount: int = 0  # 前月の今回御請求額


@dataclass
class PaymentTerms:
    """支払条件（締め日マスター）"""
    supplier_name: str  # 仕入先名
    closing_day: str  # 締め日（「月末」または「20日」など）
    payment_day: str  # 支払日（「翌月末」または「翌月10日」など）
    payment_method: str = ""  # 支払方法（任意）


class GoogleSheetsClient:
    """Google Sheets操作クライアント"""

    def __init__(self, credentials_path: Optional[Path] = None, use_oauth: bool = False):
        """
        Args:
            credentials_path: 認証情報ファイルのパス
            use_oauth: True の場合 OAuth 2.0 を使用、False の場合サービスアカウントを使用
        """
        self.credentials_path = credentials_path or CREDENTIALS_PATH
        self.use_oauth = use_oauth or os.getenv("USE_OAUTH", "false").lower() == "true"
        self._client: Optional[gspread.Client] = None

    @property
    def client(self) -> gspread.Client:
        """gspreadクライアントを取得（遅延初期化）"""
        if self._client is None:
            scopes = [
                "https://www.googleapis.com/auth/spreadsheets",
                "https://www.googleapis.com/auth/drive",
                "https://www.googleapis.com/auth/cloud-vision",  # Vision API追加
            ]

            if self.use_oauth:
                # OAuth 2.0 ユーザー認証
                credentials = self._get_oauth_credentials(scopes)
            else:
                # サービスアカウント認証
                # Streamlit Cloudの場合はsecretsから読み込む
                streamlit_secrets_available = False
                if HAS_STREAMLIT:
                    try:
                        if hasattr(st, 'secrets') and 'gcp_service_account' in st.secrets:
                            credentials = ServiceAccountCredentials.from_service_account_info(
                                dict(st.secrets['gcp_service_account']), scopes=scopes
                            )
                            streamlit_secrets_available = True
                    except Exception:
                        # Streamlit が動作していない場合はスキップ
                        pass

                if not streamlit_secrets_available:
                    # 環境変数からBase64エンコードされたcredentialsを読み込む（Render対応）
                    credentials_base64 = os.getenv("GOOGLE_CREDENTIALS_BASE64")
                    if credentials_base64:
                        try:
                            credentials_data = base64.b64decode(credentials_base64)
                            credentials_info = json.loads(credentials_data)
                            credentials = ServiceAccountCredentials.from_service_account_info(
                                credentials_info, scopes=scopes
                            )
                            streamlit_secrets_available = True
                        except Exception as e:
                            print(f"環境変数からのcredentials読み込みエラー: {e}")

                    if not streamlit_secrets_available:
                        # ローカルではファイルから読み込む
                        credentials = ServiceAccountCredentials.from_service_account_file(
                            str(self.credentials_path), scopes=scopes
                        )

            self._client = gspread.authorize(credentials)
        return self._client

    def _get_oauth_credentials(self, scopes: list[str]):
        """OAuth 2.0 認証情報を取得（本番環境対応）"""
        credentials = None

        # 環境変数からBase64エンコードされたトークンを読み込む（Render対応）
        token_base64 = os.getenv("GOOGLE_TOKEN_BASE64")
        print(f"[DEBUG Sheets] GOOGLE_TOKEN_BASE64 exists: {token_base64 is not None}")
        print(f"[DEBUG Sheets] GOOGLE_TOKEN_BASE64 length: {len(token_base64) if token_base64 else 0}")

        if token_base64:
            try:
                print("[DEBUG Sheets] Attempting to decode Base64 token...")
                token_data = base64.b64decode(token_base64)
                print(f"[DEBUG Sheets] Decoded token size: {len(token_data)} bytes")

                print("[DEBUG Sheets] Attempting to unpickle credentials...")
                credentials = pickle.loads(token_data)
                print("[DEBUG Sheets] Successfully loaded credentials from environment variable")
            except Exception as e:
                print(f"❌ 環境変数からのトークン読み込みエラー: {type(e).__name__}: {e}")
                import traceback
                traceback.print_exc()

        # ファイルシステムからtoken.pickleを読み込む（ローカル環境）
        if not credentials:
            print("[DEBUG Sheets] Attempting to load from file system...")
            base_dir = Path(__file__).parent.parent
            token_path = base_dir / "token.pickle"
            if token_path.exists():
                print(f"[DEBUG Sheets] Found token.pickle at {token_path}")
                with open(token_path, "rb") as token:
                    credentials = pickle.load(token)
            else:
                print(f"[DEBUG Sheets] token.pickle not found at {token_path}")

        # トークンが無効または存在しない場合
        print(f"[DEBUG Sheets] Credentials loaded: {credentials is not None}")
        if credentials:
            print(f"[DEBUG Sheets] Credentials valid: {credentials.valid}")
            print(f"[DEBUG Sheets] Credentials expired: {credentials.expired if hasattr(credentials, 'expired') else 'N/A'}")
            print(f"[DEBUG Sheets] Has refresh_token: {credentials.refresh_token is not None if hasattr(credentials, 'refresh_token') else 'N/A'}")

        if not credentials or not credentials.valid:
            if credentials and credentials.expired and credentials.refresh_token:
                # リフレッシュトークンでトークンを更新（本番環境で使用）
                print("[DEBUG Sheets] Attempting to refresh expired token...")
                try:
                    credentials.refresh(Request())
                    print("[DEBUG Sheets] Token refresh successful!")

                    # 更新されたトークンを保存（可能な場合のみ）
                    base_dir = Path(__file__).parent.parent
                    token_path = base_dir / "token.pickle"
                    try:
                        with open(token_path, "wb") as token:
                            pickle.dump(credentials, token)
                        print(f"[DEBUG Sheets] Updated token saved to {token_path}")
                    except Exception as save_error:
                        print(f"[DEBUG Sheets] Could not save updated token (this is OK in production): {save_error}")

                    return credentials
                except Exception as e:
                    print(f"❌ トークンのリフレッシュに失敗: {type(e).__name__}: {e}")
                    import traceback
                    traceback.print_exc()
                    raise RuntimeError(
                        f"❌ OAuth認証トークンの更新に失敗しました: {e}\n"
                        f"本番環境では、事前に生成したtoken.pickleが必要です。\n"
                        f"ローカル環境で `python oauth_setup.py` を実行してtoken.pickleを生成し、\n"
                        f"本番環境にデプロイしてください。"
                    )
            else:
                # 本番環境ではインタラクティブ認証を実行しない
                is_production = os.getenv("ENVIRONMENT", "development") == "production"
                if is_production:
                    raise RuntimeError(
                        "❌ OAuth認証が必要です。\n"
                        "本番環境では、事前に生成したtoken.pickleが必要です。\n"
                        "ローカル環境で以下を実行してください:\n"
                        "  1. python oauth_setup.py\n"
                        "  2. 生成されたtoken.pickleを本番環境にデプロイ"
                    )

                # 開発環境のみインタラクティブ認証を実行
                if not self.credentials_path.exists():
                    raise RuntimeError(
                        f"❌ {self.credentials_path} が見つかりません。\n"
                        "Google Cloud ConsoleでOAuth 2.0クライアントID（デスクトップアプリ）を作成し、\n"
                        "credentials.jsonとして保存してください。"
                    )

                flow = InstalledAppFlow.from_client_secrets_file(
                    str(self.credentials_path), scopes
                )
                port = int(os.getenv("OAUTH_PORT", "8080"))
                credentials = flow.run_local_server(port=port)

                # トークンを保存
                with open(token_path, "wb") as token:
                    pickle.dump(credentials, token)

        return credentials

    def get_company_info(self, company_name: str) -> Optional[CompanyInfo]:
        """会社マスターから会社情報を取得

        マスターシートの想定フォーマット:
        | 会社名 | 事業部 | 郵便番号 | 住所 | ビル名 |

        会社名のマッチング:
        - 法人格（株式会社、(株)など）と敬称（御中、様）を除去して比較
        - 例: "（株）SIM 御中" と "株式会社SIM（シム）" がマッチ
        """
        sheet = self.client.open_by_key(COMPANY_MASTER_SPREADSHEET_ID).worksheet(
            COMPANY_MASTER_SHEET_NAME
        )
        records = sheet.get_all_records()

        # 検索する会社名を正規化
        normalized_search = normalize_company_name(company_name)

        for record in records:
            master_name = str(record.get("会社名", ""))
            # マスター側の会社名も正規化
            normalized_master = normalize_company_name(master_name)

            # 正規化した名前で部分一致検索
            if normalized_search in normalized_master or normalized_master in normalized_search:
                # 住所とビル名を結合
                address = str(record.get("住所", ""))
                building_name = str(record.get("ビル名", ""))
                full_address = f"{address} {building_name}".strip()

                return CompanyInfo(
                    company_name=master_name,
                    postal_code=str(record.get("郵便番号", "")),
                    address=full_address,
                    department=str(record.get("事業部", "")),
                )
        return None

    def save_delivery_note(self, delivery_note: DeliveryNote, company_info: Optional[CompanyInfo]):
        """納品書DBにデータを保存

        納品書DBシートの想定フォーマット:
        | 日付 | 会社名 | 伝票番号 | 商品コード | 品名 | 数量 | 単価 | 金額 | 小計 | 消費税 | 合計 | 入金額 |
        """
        sheet = self.client.open_by_key(DELIVERY_DB_SPREADSHEET_ID).worksheet(
            DELIVERY_DB_SHEET_NAME
        )

        rows = []
        for item in delivery_note.items:
            rows.append([
                delivery_note.date,
                delivery_note.company_name,
                item.slip_number,
                item.product_code,
                item.product_name,
                item.quantity,
                item.unit_price,
                item.amount,
                delivery_note.subtotal,
                delivery_note.tax,
                delivery_note.total,
                delivery_note.payment_received,  # 入金額を追加
            ])

        if rows:
            sheet.append_rows(rows, value_input_option="USER_ENTERED")

    def get_previous_billing(self, company_name: str, current_year_month: Optional[str] = None) -> PreviousBilling:
        """先月の請求情報を売上集計表から取得

        Args:
            company_name: 会社名
            current_year_month: 現在の年月（YYYY-MM形式）、Noneの場合は今月

        Returns:
            PreviousBilling: 前月の請求情報
        """
        try:
            # 前月を計算
            if current_year_month:
                year, month = map(int, current_year_month.split('-'))
            else:
                today = datetime.now()
                year, month = today.year, today.month

            if month == 1:
                prev_year, prev_month = year - 1, 12
            else:
                prev_year, prev_month = year, month - 1

            # 年月フォーマット
            prev_year_month = f"{prev_year}年{prev_month}月"
            current_year_month_str = f"{year}年{month}月"

            # 年に基づいてシートを取得
            current_sheet = self._get_billing_sheet_by_year(year)

            # 前月が前年の場合は別のシートを取得
            if prev_year != year:
                prev_sheet = self._get_billing_sheet_by_year(prev_year)
            else:
                prev_sheet = current_sheet

            # 1. 会社の行を検索（今月のシートで）
            col_a_values = current_sheet.col_values(1)
            normalized_search = normalize_company_name(company_name)

            company_row = None
            for i, cell_value in enumerate(col_a_values[2:], start=3):
                normalized_cell = normalize_company_name(str(cell_value))
                if normalized_search in normalized_cell or normalized_cell in normalized_search:
                    company_row = i
                    break

            if company_row is None:
                print(f"    会社 '{company_name}' が売上集計表に見つかりません")
                return PreviousBilling(0, 0, 0, 0, 0, 0)

            # 2. 前月の列を検索（前月のシートで）
            prev_row1_values = prev_sheet.row_values(1)
            prev_month_col = None
            for i, cell_value in enumerate(prev_row1_values):
                if prev_year_month in str(cell_value):
                    prev_month_col = i + 1
                    break

            # 前月が別シートの場合、会社の行を再検索
            prev_company_row = company_row
            if prev_year != year:
                prev_col_a = prev_sheet.col_values(1)
                prev_company_row = None
                for i, cell_value in enumerate(prev_col_a[2:], start=3):
                    normalized_cell = normalize_company_name(str(cell_value))
                    if normalized_search in normalized_cell or normalized_cell in normalized_search:
                        prev_company_row = i
                        break

            # 3. 今月の列を検索（今月のシートで）
            current_row1_values = current_sheet.row_values(1)
            current_month_col = None
            for i, cell_value in enumerate(current_row1_values):
                if current_year_month_str in str(cell_value):
                    current_month_col = i + 1
                    break

            # 4. 値を取得
            def parse_amount(value_str: str) -> int:
                """金額文字列を数値に変換"""
                if not value_str:
                    return 0
                cleaned = str(value_str).replace(',', '').replace(' ', '').replace('¥', '').replace('円', '')
                try:
                    return int(float(cleaned))
                except ValueError:
                    return 0

            # 前回御請求額 = 前月の残高
            previous_amount = 0
            if prev_month_col and prev_company_row:
                zandaka_col = prev_month_col + 3  # 残高は年月列+3
                prev_zandaka = prev_sheet.cell(prev_company_row, zandaka_col).value or ""
                previous_amount = parse_amount(prev_zandaka)

            # 御入金額 = 今月の消滅（入金額）
            payment_received = 0
            if current_month_col:
                shoumetsu_col = current_month_col + 2  # 消滅は年月列+2
                current_shoumetsu = current_sheet.cell(company_row, shoumetsu_col).value or ""
                payment_received = parse_amount(current_shoumetsu)

            # 差引繰越残高 = 前回御請求額 - 御入金額
            carried_over = previous_amount - payment_received

            print(f"    前月({prev_year_month})残高: ¥{previous_amount:,}")
            print(f"    今月({current_year_month_str})消滅（入金額）: ¥{payment_received:,}")
            print(f"    差引繰越残高: ¥{carried_over:,}")

            return PreviousBilling(
                previous_amount=previous_amount,
                payment_received=payment_received,
                carried_over=carried_over,
                sales_amount=0,  # 請求書には使わない
                tax_amount=0,    # 請求書には使わない
                current_amount=0,  # 請求書には使わない
            )

        except Exception as e:
            print(f"    売上集計表の読み取りエラー: {e}")
            import traceback
            traceback.print_exc()
            return PreviousBilling(0, 0, 0, 0, 0, 0)

    def _get_billing_sheet_by_year(self, year: int):
        """年に基づいて売上集計表のシートを取得

        Args:
            year: 年（例: 2025）

        Returns:
            gspread.Worksheet: 対応するシート
        """
        sheet_name = str(year)
        return self.client.open_by_key(BILLING_SPREADSHEET_ID).worksheet(sheet_name)

    def _parse_year_month(self, date_str: str) -> str:
        """日付文字列をYYYY年M月形式に変換

        Args:
            date_str: 日付文字列（YYYY/MM/DD形式）

        Returns:
            str: YYYY年M月形式の文字列（例: "2025/03/01" → "2025年3月"）
        """
        # "2025/03/01" -> "2025年3月"
        parts = date_str.split('/')
        if len(parts) >= 2:
            year = int(parts[0])
            month = int(parts[1])
            return f"{year}年{month}月"
        return ""

    def save_billing_record(
        self,
        company_name: str,
        previous_billing: PreviousBilling,
        delivery_note: DeliveryNote,
    ):
        """請求管理スプレッドシートの既存セルを更新

        スプレッドシート構造:
        - Row 1: 年月ヘッダー（2026年1月、2026年2月...）が4列ごとに配置
        - Row 2: カラムラベル（相手方、発生、消費税、消滅、残高）が繰り返し
        - Row 3+: 会社データ

        処理:
        1. 日付から年月を特定
        2. Row 1から該当する年月の列を検索
        3. Column Aから会社名（正規化して一致）の行を検索
        4. 「発生」と「消費税」のセルを更新
        """
        # 1. 日付から年月を取得
        target_year_month = self._parse_year_month(delivery_note.date)
        if not target_year_month:
            print(f"    エラー: 日付のパースに失敗しました: {delivery_note.date}")
            return

        # 日付から年を抽出してシートを選択
        target_year = int(delivery_note.date.split('/')[0])
        sheet = self._get_billing_sheet_by_year(target_year)

        # 2. Row 1から年月の列を検索
        row1_values = sheet.row_values(1)
        month_col_index = None

        for i, cell_value in enumerate(row1_values):
            if target_year_month in str(cell_value):
                month_col_index = i + 1  # gspreadは1-indexed
                break

        if month_col_index is None:
            print(f"    エラー: シートに年月 '{target_year_month}' が見つかりません")
            print(f"    利用可能な年月: {[v for v in row1_values if v]}")
            return

        # 3. Row 2から各列の位置を特定
        # 構造: 年月の列が「発生」の列、その次が「消費税」「消滅」「残高」
        # 例: 列11=2025年3月/発生, 列12=消費税, 列13=消滅, 列14=残高
        row2_values = sheet.row_values(2)

        # 年月列の周辺のラベルを確認
        labels_around_month = row2_values[month_col_index-1:month_col_index+4] if month_col_index < len(row2_values) else []
        print(f"    年月 '{target_year_month}' 周辺のラベル: {labels_around_month}")

        # 各列の位置
        hassei_col = month_col_index      # 発生
        tax_col = month_col_index + 1     # 消費税
        shoumetsu_col = month_col_index + 2  # 消滅
        zandaka_col = month_col_index + 3    # 残高

        # 念のため、正しいラベルか確認
        hassei_label = row2_values[hassei_col - 1] if hassei_col <= len(row2_values) else ""
        tax_label = row2_values[tax_col - 1] if tax_col <= len(row2_values) else ""
        shoumetsu_label = row2_values[shoumetsu_col - 1] if shoumetsu_col <= len(row2_values) else ""
        zandaka_label = row2_values[zandaka_col - 1] if zandaka_col <= len(row2_values) else ""

        print(f"    列構造: 発生({hassei_col})={hassei_label}, 消費税({tax_col})={tax_label}, 消滅({shoumetsu_col})={shoumetsu_label}, 残高({zandaka_col})={zandaka_label}")

        # 4. Column Aから会社名の行を検索（正規化マッチング）
        col_a_values = sheet.col_values(1)
        normalized_search = normalize_company_name(company_name)

        company_row = None
        for i, cell_value in enumerate(col_a_values[2:], start=3):  # Row 3から開始
            normalized_cell = normalize_company_name(str(cell_value))
            if normalized_search in normalized_cell or normalized_cell in normalized_search:
                company_row = i
                print(f"    会社 '{company_name}' を行 {company_row} で発見: '{cell_value}'")
                break

        if company_row is None:
            print(f"    エラー: 会社 '{company_name}' がシートに見つかりません")
            print(f"    検索した正規化名: '{normalized_search}'")
            print(f"    利用可能な会社: {[normalize_company_name(v) for v in col_a_values[2:10]]}")
            return

        # 5. 現在の値を読み取り、加算する
        # 注意: 消滅（入金額）は手動入力、残高は数式で自動計算されるため更新しない
        current_hassei_str = sheet.cell(company_row, hassei_col).value or ""
        current_tax_str = sheet.cell(company_row, tax_col).value or ""

        # 既存の値をパース（カンマや空白を除去して数値化）
        def parse_amount(value_str: str) -> int:
            """金額文字列を数値に変換"""
            if not value_str:
                return 0
            # カンマ、空白、円記号などを除去
            cleaned = str(value_str).replace(',', '').replace(' ', '').replace('¥', '').replace('円', '')
            try:
                return int(float(cleaned))
            except ValueError:
                return 0

        current_hassei = parse_amount(current_hassei_str)
        current_tax = parse_amount(current_tax_str)

        # 新しい値を加算
        new_hassei = current_hassei + delivery_note.subtotal
        new_tax = current_tax + delivery_note.tax

        print(f"    更新: 行 {company_row}, 列 {hassei_col}(発生), {tax_col}(消費税)")
        print(f"    既存: 発生 ¥{current_hassei:,}, 消費税 ¥{current_tax:,}")
        print(f"    追加: 発生 ¥{delivery_note.subtotal:,}, 消費税 ¥{delivery_note.tax:,}")
        print(f"    合計: 発生 ¥{new_hassei:,}, 消費税 ¥{new_tax:,}")
        print(f"    ※ 消滅（列{shoumetsu_col}）は手動入力、残高（列{zandaka_col}）は数式で自動計算")

        # セルを更新（発生と消費税のみ）
        sheet.update_cell(company_row, hassei_col, new_hassei)
        sheet.update_cell(company_row, tax_col, new_tax)

    def get_payment_terms(self, supplier_name: str) -> Optional[PaymentTerms]:
        """締め日マスターから支払条件を取得

        Args:
            supplier_name: 仕入先名

        Returns:
            PaymentTerms: 支払条件、見つからない場合はNone
        """
        if not PURCHASE_TERMS_SPREADSHEET_ID:
            print("    警告: PURCHASE_TERMS_SPREADSHEET_ID が設定されていません")
            return None

        try:
            sheet = self.client.open_by_key(PURCHASE_TERMS_SPREADSHEET_ID).worksheet(
                PURCHASE_TERMS_SHEET_NAME
            )

            # 手動でヘッダーとデータを読み取り（重複ヘッダー対策）
            all_values = sheet.get_all_values()

            if len(all_values) < 2:
                print("    警告: 締め日マスターにデータがありません")
                return None

            # ヘッダー行（Row 1）
            headers = all_values[0]

            # 各列のインデックスを特定
            supplier_col = None
            closing_col = None
            payment_col = None
            method_col = None

            for i, header in enumerate(headers):
                if "仕入先名" in str(header):
                    supplier_col = i
                elif "締め日" in str(header):
                    closing_col = i
                elif "支払日" in str(header):
                    payment_col = i
                elif "支払方法" in str(header):
                    method_col = i

            if supplier_col is None:
                print("    警告: 締め日マスターに「仕入先名」列が見つかりません")
                return None

            # 検索する会社名を正規化
            normalized_search = normalize_company_name(supplier_name)

            # データ行を検索（Row 2以降）
            for row in all_values[1:]:
                if len(row) <= supplier_col:
                    continue

                master_name = str(row[supplier_col])
                normalized_master = normalize_company_name(master_name)

                # 正規化した名前で部分一致検索
                if normalized_search in normalized_master or normalized_master in normalized_search:
                    return PaymentTerms(
                        supplier_name=master_name,
                        closing_day=str(row[closing_col]) if closing_col and len(row) > closing_col else "月末",
                        payment_day=str(row[payment_col]) if payment_col and len(row) > payment_col else "",
                        payment_method=str(row[method_col]) if method_col and len(row) > method_col else "",
                    )
            return None

        except Exception as e:
            print(f"    締め日マスター読み取りエラー: {e}")
            import traceback
            traceback.print_exc()
            return None

    def save_purchase_record(
        self,
        supplier_name: str,
        target_year_month: str,
        purchase_invoice,  # PurchaseInvoice型（循環importを避けるため型ヒントなし）
    ):
        """仕入れスプレッドシートにデータを書き込み

        Args:
            supplier_name: 仕入先名
            target_year_month: 記入対象年月（YYYY年M月形式）
            purchase_invoice: 仕入れ納品書データ（PurchaseInvoice）
        """
        if not PURCHASE_SPREADSHEET_ID:
            raise ValueError("PURCHASE_SPREADSHEET_ID が設定されていません")

        sheet = self.client.open_by_key(PURCHASE_SPREADSHEET_ID).worksheet(
            PURCHASE_SHEET_NAME
        )

        # 1. Row 2から年月列を検索
        row2_values = sheet.row_values(2)
        month_col = self._find_month_column_in_row(row2_values, target_year_month)

        if month_col is None:
            raise ValueError(f"年月 '{target_year_month}' がスプレッドシートに見つかりません")

        # 2. 会社名の行を検索（なければ追加）
        company_row = self._find_or_create_company_row(sheet, supplier_name)

        # 3. 各列の位置を計算
        hassei_col = month_col  # 発生
        tax_col = month_col + 1  # 消費税
        shoumetsu_col = month_col + 2  # 消滅
        zandaka_col = month_col + 3  # 残高

        # 既存値をパース
        def parse_amount(value_str: str) -> int:
            if not value_str:
                return 0
            cleaned = str(value_str).replace(',', '').replace(' ', '').replace('¥', '').replace('円', '')
            try:
                return int(float(cleaned))
            except ValueError:
                return 0

        # 4. 海外輸入の場合は2行使用
        if purchase_invoice.is_overseas:
            print(f"    海外輸入: 2行に記録します")

            # 1行目: 関税なし（税抜金額）
            amount_no_duty = purchase_invoice.subtotal
            tax_no_duty = int(amount_no_duty * 0.10)

            # 2行目: 関税あり（税抜金額 + 関税）
            amount_with_duty = purchase_invoice.subtotal + purchase_invoice.customs_duty
            tax_with_duty = int(amount_with_duty * 0.10)

            # 1行目を更新
            current_hassei_1 = parse_amount(sheet.cell(company_row, hassei_col).value or "")
            current_tax_1 = parse_amount(sheet.cell(company_row, tax_col).value or "")
            new_hassei_1 = current_hassei_1 + amount_no_duty
            new_tax_1 = current_tax_1 + tax_no_duty

            sheet.update_cell(company_row, hassei_col, new_hassei_1)
            sheet.update_cell(company_row, tax_col, new_tax_1)

            print(f"    1行目（行{company_row}）: 発生 ¥{new_hassei_1:,}, 消費税 ¥{new_tax_1:,}")

            # 2行目を更新（次の行）
            company_row_2 = company_row + 1

            # 2行目のA列（会社名）に同じ会社名を記入
            current_company_name = sheet.cell(company_row_2, 1).value or ""
            if not current_company_name or normalize_company_name(current_company_name) != normalize_company_name(supplier_name):
                sheet.update_cell(company_row_2, 1, supplier_name)

            current_hassei_2 = parse_amount(sheet.cell(company_row_2, hassei_col).value or "")
            current_tax_2 = parse_amount(sheet.cell(company_row_2, tax_col).value or "")
            new_hassei_2 = current_hassei_2 + amount_with_duty
            new_tax_2 = current_tax_2 + tax_with_duty

            sheet.update_cell(company_row_2, hassei_col, new_hassei_2)
            sheet.update_cell(company_row_2, tax_col, new_tax_2)

            print(f"    2行目（行{company_row_2}）: 発生 ¥{new_hassei_2:,}, 消費税 ¥{new_tax_2:,}")

        else:
            # 国内仕入れ: 1行のみ
            print(f"    国内仕入れ: 1行に記録します")

            current_hassei = parse_amount(sheet.cell(company_row, hassei_col).value or "")
            current_tax = parse_amount(sheet.cell(company_row, tax_col).value or "")

            new_hassei = current_hassei + purchase_invoice.subtotal
            new_tax = current_tax + purchase_invoice.tax

            sheet.update_cell(company_row, hassei_col, new_hassei)
            sheet.update_cell(company_row, tax_col, new_tax)

            print(f"    更新（行{company_row}）: 発生 ¥{new_hassei:,}, 消費税 ¥{new_tax:,}")

    def _find_month_column_in_row(self, row_values: list, target_year_month: str) -> Optional[int]:
        """行データから年月の列を検索

        Args:
            row_values: 行のセル値リスト
            target_year_month: 検索する年月（YYYY年M月形式）

        Returns:
            int: 列番号（1-indexed）、見つからない場合はNone
        """
        for i, cell_value in enumerate(row_values):
            if target_year_month in str(cell_value):
                return i + 1  # gspreadは1-indexed
        return None

    def _find_or_create_company_row(self, sheet, company_name: str) -> int:
        """会社名の行を検索、なければ追加

        Args:
            sheet: gspreadのWorksheetオブジェクト
            company_name: 会社名

        Returns:
            int: 会社名の行番号（1-indexed）
        """
        col_a_values = sheet.col_values(1)
        normalized_search = normalize_company_name(company_name)

        # Row 4以降から検索（Row 1-3はヘッダー）
        for i, cell_value in enumerate(col_a_values[3:], start=4):
            normalized_cell = normalize_company_name(str(cell_value))
            if normalized_search in normalized_cell or normalized_cell in normalized_search:
                print(f"    会社 '{company_name}' を行 {i} で発見")
                return i

        # 見つからない場合は新規行を追加
        new_row = len(col_a_values) + 1
        sheet.update_cell(new_row, 1, company_name)
        print(f"    会社 '{company_name}' を行 {new_row} に追加しました")
        return new_row

