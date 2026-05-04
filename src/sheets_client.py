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

from .canonical_companies import PURCHASE_CANONICALS, SALES_CANONICALS
from .config import (
    BILLING_SHEET_NAME,
    BILLING_SPREADSHEET_ID,
    COMPANY_MASTER_SHEET_NAME,
    COMPANY_MASTER_SPREADSHEET_ID,
    CREDENTIALS_PATH,
    PURCHASE_SPREADSHEET_ID,
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

    # NFKC正規化（濁点の合成形/分解形の差異、半角/全角カタカナの差異を吸収）
    import unicodedata
    name = unicodedata.normalize('NFKC', name)

    # 法人格を除去（㈱ = U+3231, ㈲ = U+3232 も対応）
    name = re.sub(r'株式会社|有限会社|\(株\)|（株）|\(有\)|（有）|㈱|㈲', '', name)

    # 敬称を除去
    name = re.sub(r'御中|様|殿', '', name)

    # カッコ内の読み仮名を除去（例: （シム）, (シム), 【シム】など）
    name = re.sub(r'[（(【].*?[）)】]', '', name)

    # 空白文字を除去
    name = re.sub(r'\s+', '', name)

    return name.strip()


def _extra_signatures(extra: str) -> list[str]:
    """canonical 名の "親に対する追加部分" から、ファイル名で検索可能なトークンを抽出

    例:
    - 'HARE事業部' → ['HARE', '事業部']
    - 'ショッパー' → ['ショッパー']
    - '/サンプル' → ['サンプル']
    - 'YS/サンプル' → ['YS', 'サンプル']
    - '/非課税' → ['非課税']
    """
    import re
    if not extra:
        return []
    # 英数字 / カタカナ / 漢字 / ひらがな の連続をトークンとして抽出
    tokens = re.findall(
        r'[A-Za-z0-9]+|[゠-ヿー]+|[一-鿿]+|[぀-ゟ]+',
        extra,
    )
    # 1文字以上のトークンのみ（区切り記号は除外）
    return [t for t in tokens if len(t) >= 1]


def match_company_name_with_filename(
    search_name: str,
    candidates: list[str],
    filename: Optional[str] = None,
) -> Optional[str]:
    """ファイル名ヒントを使った canonical 解決

    動作:
    - 親 (exact match) と 子 (接頭辞共有 = sibling) が共存する場合:
      - ファイル名のトークン (例: 'HARE', 'ショッパー') で disambiguate
      - ヒットすれば該当する子を返す
      - ヒットしなければ親を返す（既存挙動と同じ）
      - ヒント無しで子しか存在しないなら None を返してピッカー強制

    例:
    - search='アダストリア', filename='0227アダストリアHARE_岡部.pdf'
      candidates に [親, HARE事業部, ショッパー] がある場合
      → 'HARE' トークンが filename にヒット → '（株）アダストリア　HARE事業部'
    - search='アダストリア', filename='0218アダストリア岡部.pdf'
      → 'HARE' / 'ショッパー' どちらも filename に無い → 親 '（株）アダストリア'
    - search='インス', filename='0201インス・佐藤.pdf'
      → 子 '/非課税' のトークン '非課税' が filename に無い → 親 '（株）インス'
    """
    normalized_search = normalize_company_name(search_name)
    if not normalized_search:
        return None

    # canonical を normalized 形でインデックス化
    canon_by_norm: dict[str, list[str]] = {}
    for c in candidates:
        if not c:
            continue
        n = normalize_company_name(str(c))
        if n:
            canon_by_norm.setdefault(n, []).append(str(c).strip())

    # 親 (exact) 候補
    exact = list(dict.fromkeys(canon_by_norm.get(normalized_search, [])))
    if len(exact) >= 2:
        return None  # 正規化後に同名の異なる会社 → 曖昧

    # 子 (sibling) 候補: normalized_search の prefix で始まる、より長い canonical
    siblings: list[str] = []
    for n, cs in canon_by_norm.items():
        if n != normalized_search and n.startswith(normalized_search):
            for c in cs:
                if c not in siblings:
                    siblings.append(c)

    # 親なし・子なし → 既存の partial-match ロジックにフォールバック
    if not exact and not siblings:
        return match_company_name(search_name, candidates)

    # 親のみ → そのまま返す（既存挙動）
    if exact and not siblings:
        return exact[0]

    # 子のみ単一 → そのまま返す（既存挙動）
    if not exact and len(siblings) == 1:
        return siblings[0]

    # ここから siblings あり: ファイル名で disambiguate を試みる
    normalized_filename = normalize_company_name(filename or "")

    if siblings and normalized_filename:
        scored: list[tuple[str, int]] = []
        for c in siblings:
            n = normalize_company_name(c)
            extra = n[len(normalized_search):]
            sigs = _extra_signatures(extra)
            score = sum(len(sig) for sig in sigs if sig and sig in normalized_filename)
            if score > 0:
                scored.append((c, score))
        if scored:
            scored.sort(key=lambda x: -x[1])
            top_score = scored[0][1]
            top = [c for c, s in scored if s == top_score]
            if len(top) == 1:
                return top[0]
            # 同点 → 曖昧 → ピッカー
            return None

    # ファイル名にヒント無し
    if exact:
        return exact[0]  # 親で確定（既存挙動・後方互換）
    # 子複数あって disambiguate できず → ピッカー
    return None


def match_company_name(search_name: str, candidates: list[str]) -> Optional[str]:
    """正規化した会社名で最適な候補を選択

    マッチング優先度:
    1. 正規化後の完全一致（1件のみ）
    2. 部分一致（1件のみ）

    完全一致・部分一致いずれも複数候補がある場合は曖昧と判断し
    None を返す（ユーザーに選択させる）。

    例:
    - "アダストリア" vs ["アダストリア", "アダストリアサンプル"]
      → "アダストリア"（完全一致1件）
    - "アダストリアサンプル" vs ["アダストリア", "アダストリアサンプル"]
      → "アダストリアサンプル"（完全一致1件）
    - "アダストリアサンプル" vs ["アダストリア"]（サンプルが未登録）
      → None（部分一致1件だが差が大きい → ユーザー選択）
    - "アダストリア" vs ["アダストリア", "アダストリア（サンプル）"]
      → None（正規化後に同名の候補が複数 → ユーザー選択）

    Args:
        search_name: 検索する会社名（正規化前）
        candidates: 候補の会社名リスト（正規化前）

    Returns:
        マッチした候補の元の文字列、見つからない場合は None
    """
    normalized_search = normalize_company_name(search_name)
    if not normalized_search:
        return None

    # 1. 完全一致を優先（複数マッチした場合は曖昧なので None）
    exact_matches = []
    for candidate in candidates:
        if not candidate:
            continue
        normalized_candidate = normalize_company_name(str(candidate))
        if normalized_candidate and normalized_search == normalized_candidate:
            exact_matches.append(str(candidate).strip())

    # 重複除去（同じ会社名が複数行にある場合）
    unique_exact = list(dict.fromkeys(exact_matches))
    if len(unique_exact) == 1:
        return unique_exact[0]
    elif len(unique_exact) >= 2:
        # 正規化後に同じ名前になる異なる会社が複数 → 曖昧なので None
        return None

    # 2. 部分一致フォールバック
    #    候補が複数ある場合は曖昧なので None を返し、ユーザーに選択させる
    partial_matches: list[tuple[str, int]] = []  # (元の候補名, 長さの差)

    for candidate in candidates:
        if not candidate:
            continue
        normalized_candidate = normalize_company_name(str(candidate))
        if not normalized_candidate:
            continue

        if normalized_search in normalized_candidate or normalized_candidate in normalized_search:
            diff = abs(len(normalized_search) - len(normalized_candidate))
            partial_matches.append((str(candidate).strip(), diff))

    if len(partial_matches) == 1:
        # 差が小さい場合のみ自動マッチ（例: "HARE" vs "HARE事業部" は OK、
        # "アダストリア" vs "アダストリアサンプル" は差が大きいので NG）
        if partial_matches[0][1] <= 2:
            return partial_matches[0][0]
        else:
            return None
    elif len(partial_matches) >= 2:
        # 複数の部分一致候補がある → 曖昧なので None（ユーザー選択へ）
        return None

    return None


def _find_company_row(
    company_name: str, col_a_values: list[str], start_row: int = 3
) -> Optional[int]:
    """Column A の会社名リストから最適な行番号を返す

    match_company_name() を使って完全一致優先・最短差フォールバックで検索。

    Args:
        company_name: 検索する会社名
        col_a_values: Column A のセル値リスト（0-indexed）
        start_row: データ開始行（1-indexed、デフォルト3 = Row 3）

    Returns:
        行番号（1-indexed）、見つからない場合は None
    """
    # start_row は 1-indexed、col_a_values は 0-indexed
    offset = start_row - 1  # Row 3 → index 2
    candidates = col_a_values[offset:]

    matched = match_company_name(company_name, candidates)
    if matched is None:
        return None

    # マッチした候補の行番号を特定
    for i, cell_value in enumerate(candidates):
        if str(cell_value).strip() == matched:
            return i + start_row

    return None


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


def parse_amount(value) -> int:
    """セル値を数値に変換（数値型はそのまま、文字列はパース）

    対応フォーマット:
    - 数値型（int, float）
    - カンマ区切り: 1,234
    - 通貨記号: ¥1,234 / ￥1,234 / 1,234円
    - 会計書式の括弧: (3,000) → -3000
    - 日本語マイナス記号: ▲3,000 / △3,000
    """
    if value is None or value == "":
        return 0
    if isinstance(value, (int, float)):
        return int(value)
    s = str(value)
    negative = False
    if s.startswith('(') and s.endswith(')'):
        s = s[1:-1]
        negative = True
    if s.startswith(('▲', '△')):
        s = s[1:]
        negative = True
    cleaned = s.replace(',', '').replace('，', '').replace(' ', '').replace('¥', '').replace('￥', '').replace('円', '')
    try:
        result = int(float(cleaned))
        return -result if negative else result
    except ValueError:
        return 0


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

    def get_canonical_company_name(
        self,
        company_name: str,
        year: Optional[int] = None,
        filename: Optional[str] = None,
    ) -> Optional[str]:
        """売上 canonical 会社名を取得（ハードコードリスト経由）

        Phase 1 で sheet 依存を撤廃。SALES_CANONICALS を唯一の真値として使用する。
        Phase 3 で filename ヒントを追加: 親と子（HARE 事業部 等）が canonical に
        共存する場合、ファイル名のトークンで子を判別する。

        Args:
            company_name: LLMが抽出した会社名
            year: （未使用・後方互換）
            filename: PDFファイル名（親/子の disambiguation に使用、任意）

        Returns:
            マッチした canonical 会社名、見つからない/曖昧な場合は None（ピッカー強制）
        """
        canonical = match_company_name_with_filename(
            company_name, list(SALES_CANONICALS), filename=filename
        )
        if canonical:
            print(f"    正規会社名取得: '{company_name}' → '{canonical}' (filename={filename!r})")
        return canonical

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

        # match_company_name で最適な候補を選択
        master_names = [str(r.get("会社名", "")) for r in records]
        matched = match_company_name(company_name, master_names)

        if matched:
            # マッチしたレコードを取得
            for record in records:
                if str(record.get("会社名", "")) == matched:
                    master_name = matched
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
        """前月の請求情報を DB から計算（Phase 2: シート読み廃止）

        DB-as-truth に従い、シートではなく DB の monthly_invoices / monthly_payments を集計する。
        シートが消えてもPDF印字で正しい前月情報が出る。

        Args:
            company_name: canonical 会社名
            current_year_month: 現在の年月（"YYYY-MM" or "YYYY年M月" or None=今月）

        Returns:
            PreviousBilling: 前月残高・当月入金・当月発生・当月消費税
        """
        try:
            # current_year_month を "YYYY年M月" 形式に正規化
            if current_year_month:
                if '-' in current_year_month and '年' not in current_year_month:
                    year, month = map(int, current_year_month.split('-'))
                else:
                    m = re.match(r'(\d+)年(\d+)月', current_year_month)
                    if m:
                        year, month = int(m.group(1)), int(m.group(2))
                    else:
                        today = datetime.now()
                        year, month = today.year, today.month
            else:
                today = datetime.now()
                year, month = today.year, today.month

            current_ym_jp = f"{year}年{month}月"

            # DB から ledger を計算
            from .database import MonthlyItemsDB
            db = MonthlyItemsDB()
            ledger = db.compute_ledger(company_name, current_ym_jp)

            previous_amount = ledger["previous_balance"]
            payment_received = ledger["payment_amount"]
            sales_amount = ledger["subtotal"]
            tax_amount = ledger["tax"]
            carried_over = previous_amount - payment_received

            print(f"    [DB] 前月残高: ¥{previous_amount:,}")
            print(f"    [DB] 当月({current_ym_jp})消滅（入金額）: ¥{payment_received:,}")
            print(f"    [DB] 差引繰越残高: ¥{carried_over:,}")
            print(f"    [DB] 当月発生: ¥{sales_amount:,}, 消費税: ¥{tax_amount:,}")

            return PreviousBilling(
                previous_amount=previous_amount,
                payment_received=payment_received,
                carried_over=carried_over,
                sales_amount=sales_amount,
                tax_amount=tax_amount,
                current_amount=0,
            )

        except Exception as e:
            print(f"    [DB] previous_billing 計算エラー: {e}")
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
        target_year_month: str,
        subtotal: int,
        tax: int,
        previous_billing: Optional[PreviousBilling] = None,  # 後方互換のため残置（未使用）
    ):
        """売上集計シートの (会社, 年月) 行に発生・消費税の絶対値を書き込む

        Phase 2 (DB-as-truth): 加算ではなく上書き。caller は DB 集計値を渡す。
        再保存で 2倍/3倍になる旧バグはこの関数では発生しない。

        スプレッドシート構造:
        - Row 1: 年月ヘッダー（2026年1月、2026年2月...）が4列ごとに配置
        - Row 2: カラムラベル（相手方、発生、消費税、消滅、残高）が繰り返し
        - Row 3+: 会社データ

        Args:
            company_name: canonical な会社名（既にシートに登録されているもの）
            target_year_month: 年月（"YYYY年M月"形式、必須）
            subtotal: DB 集計の当月発生合計（絶対値）
            tax: DB 集計の当月消費税合計（絶対値）
            previous_billing: 後方互換のため残置（未使用、Phase 2 完了後に削除予定）
        """
        if not target_year_month:
            raise ValueError("target_year_month は必須です")

        year_month = target_year_month
        year_match = re.match(r'(\d{4})', target_year_month)
        if not year_match:
            raise ValueError(f"target_year_month のパース失敗: {target_year_month}")
        target_year = int(year_match.group(1))

        sheet = self._get_billing_sheet_by_year(target_year)

        # 2. Row 1から年月の列を検索
        row1_values = sheet.row_values(1)
        month_col_index = None

        for i, cell_value in enumerate(row1_values):
            if year_month in str(cell_value):
                month_col_index = i + 1  # gspreadは1-indexed
                break

        if month_col_index is None:
            print(f"    エラー: シートに年月 '{year_month}' が見つかりません")
            print(f"    利用可能な年月: {[v for v in row1_values if v]}")
            return

        # 3. Row 2から各列の位置を特定
        # 構造: 年月の列が「発生」の列、その次が「消費税」「消滅」「残高」
        # 例: 列11=2025年3月/発生, 列12=消費税, 列13=消滅, 列14=残高
        row2_values = sheet.row_values(2)

        # 年月列の周辺のラベルを確認
        labels_around_month = row2_values[month_col_index-1:month_col_index+4] if month_col_index < len(row2_values) else []
        print(f"    年月 '{year_month}' 周辺のラベル: {labels_around_month}")

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

        # 4. Column Aから会社名の行を検索（完全一致優先マッチング）
        col_a_values = sheet.col_values(1)
        company_row = _find_company_row(company_name, col_a_values, start_row=3)

        if company_row is not None:
            print(f"    会社 '{company_name}' を行 {company_row} で発見")
        else:
            print(f"    エラー: 会社 '{company_name}' がシートに見つかりません")
            print(f"    検索した正規化名: '{normalize_company_name(company_name)}'")
            print(f"    利用可能な会社: {[normalize_company_name(v) for v in col_a_values[2:10]]}")
            return

        # 5. 絶対値（DB集計値）を書き込む（Phase 2: 加算撤廃）
        # 注意: 消滅（入金額）は手動入力、残高は数式で自動計算されるため更新しない
        print(f"    [SHEET_WRITE] 上書き: 行 {company_row}, 列 {hassei_col}(発生)={subtotal:,}, {tax_col}(消費税)={tax:,}")
        print(f"    ※ 消滅（列{shoumetsu_col}）は手動入力、残高（列{zandaka_col}）は数式で自動計算")
        sheet.update_cell(company_row, hassei_col, subtotal)
        sheet.update_cell(company_row, tax_col, tax)

    def get_billing_amounts(self, year: int) -> list[dict]:
        """指定年のシートから全会社・全月の「発生」「消費税」を一括読み取り

        Args:
            year: 対象年（例: 2026）

        Returns:
            list[dict]: [{company_name, year_month, subtotal, tax}, ...]
        """
        sheet = self._get_billing_sheet_by_year(year)
        all_values = sheet.get_all_values()

        if len(all_values) < 3:
            return []

        row1 = all_values[0]  # 年月ヘッダー行

        # 年月列の位置を特定（"YYYY年M月" を含むセル）
        month_columns: list[tuple[int, str]] = []  # (col_index, year_month_str)
        for i, cell_value in enumerate(row1):
            if "年" in str(cell_value) and "月" in str(cell_value):
                month_columns.append((i, str(cell_value).strip()))

        results = []
        # Row 3以降が会社データ
        for row in all_values[2:]:
            company_name = str(row[0]).strip() if row else ""
            if not company_name:
                continue

            for col_idx, year_month_str in month_columns:
                hassei_idx = col_idx      # 発生
                tax_idx = col_idx + 1     # 消費税

                hassei_val = row[hassei_idx] if hassei_idx < len(row) else ""
                tax_val = row[tax_idx] if tax_idx < len(row) else ""

                subtotal = parse_amount(hassei_val)
                tax = parse_amount(tax_val)

                # 0/0 のエントリもスキップしない（DBにデータがある可能性）
                results.append({
                    "company_name": company_name,
                    "year_month": year_month_str,
                    "subtotal": subtotal,
                    "tax": tax,
                })

        return results

    def _get_purchase_sheet_by_year(self, year: int):
        """年に基づいて仕入れスプレッドシートのシートを取得"""
        if not PURCHASE_SPREADSHEET_ID:
            raise ValueError("PURCHASE_SPREADSHEET_ID が設定されていません")
        sheet_name = str(year)
        return self.client.open_by_key(PURCHASE_SPREADSHEET_ID).worksheet(sheet_name)

    def _find_purchase_section_info(self, col_a_values: list, company_row: int) -> dict:
        """会社名が見つかった行がどのセクションに属するかを判定

        セクション構造:
        - Row 4-75: 課税仕入れ（2行/社: 上=非課税, 下=課税）
        - Row 76: 課税仕入れ合計
        - Row 78: 非課税仕入ヘッダー
        - Row 79-95: 非課税仕入（1行/社）
        - Row 96: 非課税合計金額
        - Row 99: 課税事業者ヘッダー
        - Row 100-173: 課税事業者（2行/社: 上=非課税, 下=課税）
        - Row 174: 課税外注合計
        - Row 176: 非課税検品ヘッダー
        - Row 177-181: 非課税検品（1行/社）
        - Row 182: 非課税合計金額

        Returns:
            dict: {"type": "2row" or "1row", "row": int}
        """
        # セクション境界を特定するためにColumn Aを走査
        section_boundaries = []
        for i, val in enumerate(col_a_values):
            row_num = i + 1  # 1-indexed
            val_str = str(val).strip()
            if "課税仕入れ合計" in val_str:
                section_boundaries.append({"row": row_num, "marker": "課税仕入れ合計", "type": "2row_end"})
            elif "非課税仕入" in val_str and "合計" not in val_str and "検品" not in val_str:
                section_boundaries.append({"row": row_num, "marker": "非課税仕入", "type": "1row_start"})
            elif "課税事業者" in val_str:
                section_boundaries.append({"row": row_num, "marker": "課税事業者", "type": "2row_start"})
            elif "課税外注合計" in val_str:
                section_boundaries.append({"row": row_num, "marker": "課税外注合計", "type": "2row_end"})
            elif "非課税検品" in val_str:
                section_boundaries.append({"row": row_num, "marker": "非課税検品", "type": "1row_start"})
            elif val_str == "非課税合計金額":
                section_boundaries.append({"row": row_num, "marker": "非課税合計金額", "type": "1row_end"})

        # company_rowがどのセクションに属するか判定
        # デフォルト: 最初のセクション（課税仕入れ = 2行）
        section_type = "2row"

        for boundary in sorted(section_boundaries, key=lambda b: b["row"]):
            if boundary["row"] > company_row:
                # この境界より前のセクションに属する
                break
            if boundary["type"] == "1row_start":
                section_type = "1row"
            elif boundary["type"] == "2row_start":
                section_type = "2row"
            elif boundary["type"] == "2row_end":
                section_type = "1row"  # 次のセクションへの遷移
            elif boundary["type"] == "1row_end":
                section_type = "2row"  # 次のセクションへの遷移

        return {"type": section_type, "row": company_row}

    def save_purchase_record(
        self,
        supplier_name: str,
        target_year_month: str,
        subtotal: int,
        tax: int,
        is_taxable: bool = True,
    ):
        """仕入シートの (仕入先, 年月) セルに発生・消費税・残高の絶対値を書き込む

        Phase 2 (DB-as-truth): 加算ではなく上書き。caller は DB 集計値を渡す。
        残高 = subtotal + tax（旧加算式と同じセマンティクス。入金は別途 消滅列で管理）

        セクション構造に基づいて書き込み先を判定:
        - 2行セクション（課税仕入れ / 課税事業者）:
          - is_taxable=False → 上の行（会社名行）
          - is_taxable=True  → 下の行（会社名行+1）
        - 1行セクション（非課税仕入 / 非課税検品）: 常に会社名行
        """
        if not PURCHASE_SPREADSHEET_ID:
            raise ValueError("PURCHASE_SPREADSHEET_ID が設定されていません")

        year_match = re.match(r'(\d{4})', target_year_month)
        target_year = int(year_match.group(1)) if year_match else datetime.now().year
        sheet = self._get_purchase_sheet_by_year(target_year)

        # 1. Row 2から年月列を検索
        row2_values = sheet.row_values(2)
        month_col = self._find_month_column_in_row(row2_values, target_year_month)

        if month_col is None:
            raise ValueError(f"年月 '{target_year_month}' が仕入れスプレッドシートに見つかりません")

        # 2. Column Aで会社名を検索
        col_a_values = sheet.col_values(1)
        company_row = _find_company_row(supplier_name, col_a_values, start_row=4)

        if company_row is None:
            raise ValueError(
                f"仕入先 '{supplier_name}' が仕入れスプレッドシートに見つかりません。"
                f"シートに仕入先名を事前登録してください。"
            )

        print(f"    仕入先 '{supplier_name}' を行 {company_row} で発見")

        # 3. セクション判定
        section_info = self._find_purchase_section_info(col_a_values, company_row)
        section_type = section_info["type"]
        print(f"    セクション: {section_type}")

        # 4. 書き込み行を決定
        hassei_col = month_col      # 発生
        tax_col = month_col + 1     # 消費税
        zandaka_col = month_col + 3 # 残高

        if section_type == "2row":
            target_row = company_row + 1 if is_taxable else company_row
            print(f"    {'課税' if is_taxable else '非課税'}仕入れ → 行{target_row}")
        else:
            target_row = company_row
            print(f"    1行セクション → 行{target_row}")

        # 5. 絶対値を書き込み（残高 = 当月発生 + 消費税）
        new_zandaka = subtotal + tax
        print(f"    [SHEET_WRITE] 上書き: 発生={subtotal:,}, 消費税={tax:,}, 残高={new_zandaka:,}")

        sheet.update_cell(target_row, hassei_col, subtotal)
        sheet.update_cell(target_row, tax_col, tax)
        sheet.update_cell(target_row, zandaka_col, new_zandaka)

    def update_purchase_payment(
        self,
        company_name: str,
        year_month: str,
        payment_amount: int,
        add_mode: bool = False,
    ) -> dict:
        """仕入れスプレッドシートの消滅列を更新"""
        year_match = re.match(r'(\d{4})', year_month)
        target_year = int(year_match.group(1)) if year_match else datetime.now().year
        sheet = self._get_purchase_sheet_by_year(target_year)

        # 年月列を検索
        row2_values = sheet.row_values(2)
        month_col = self._find_month_column_in_row(row2_values, year_month)
        if month_col is None:
            raise ValueError(f"年月 '{year_month}' が見つかりません")

        # 会社名の行を検索
        col_a_values = sheet.col_values(1)
        company_row = _find_company_row(company_name, col_a_values, start_row=4)
        if company_row is None:
            raise ValueError(f"仕入先 '{company_name}' が見つかりません")

        # 消滅列 = 年月列 + 2
        shoumetsu_col = month_col + 2

        current_value = parse_amount(sheet.cell(company_row, shoumetsu_col).value or "")

        if add_mode:
            new_value = current_value + payment_amount
        else:
            new_value = payment_amount

        sheet.update_cell(company_row, shoumetsu_col, new_value)

        return {
            "previous_value": current_value,
            "new_value": new_value,
        }

    def get_purchase_companies_and_months(self) -> dict:
        """仕入れスプレッドシートから会社リストと年月リストを取得"""
        target_year = datetime.now().year
        sheet = self._get_purchase_sheet_by_year(target_year)

        col_a = sheet.col_values(1)
        companies_all = [c for c in col_a[3:] if c]  # Row 4以降

        seen_companies = set()
        companies = []
        for c in companies_all:
            c_stripped = c.strip()
            if c_stripped and c_stripped not in seen_companies:
                # セクション区切りの行を除外
                skip_keywords = ["合計", "非課税仕入", "課税事業者", "非課税検品"]
                if not any(kw in c_stripped for kw in skip_keywords):
                    seen_companies.add(c_stripped)
                    companies.append(c_stripped)

        row2 = sheet.row_values(2)
        year_months_all = [ym for ym in row2 if "年" in str(ym) and "月" in str(ym)]

        seen = set()
        year_months = []
        for ym in year_months_all:
            if ym not in seen:
                seen.add(ym)
                year_months.append(ym)

        return {
            "companies": companies,
            "year_months": year_months,
        }

    def get_purchase_table(self) -> dict:
        """仕入れスプレッドシートの全データを取得"""
        target_year = datetime.now().year
        sheet = self._get_purchase_sheet_by_year(target_year)

        data = sheet.get_all_values()
        if not data or len(data) == 0:
            return {"headers": [], "data": []}

        headers = data[0]
        rows = data[1:]

        return {"headers": headers, "data": rows}

    def get_canonical_purchase_company_name(
        self,
        company_name: str,
        year: Optional[int] = None,
        filename: Optional[str] = None,
    ) -> Optional[str]:
        """仕入 canonical 会社名を取得（ハードコードリスト経由）

        Phase 1 で sheet 依存を撤廃。PURCHASE_CANONICALS を唯一の真値として使用する。
        Phase 3 で filename ヒント引数を追加（親/子 disambiguation 用）。
        """
        canonical = match_company_name_with_filename(
            company_name, list(PURCHASE_CANONICALS), filename=filename
        )
        if canonical:
            print(f"    仕入れ正規会社名取得: '{company_name}' → '{canonical}' (filename={filename!r})")
        return canonical

    def _find_month_column_in_row(self, row_values: list, target_year_month: str) -> Optional[int]:
        """行データから年月の列を検索"""
        for i, cell_value in enumerate(row_values):
            if target_year_month in str(cell_value):
                return i + 1  # gspreadは1-indexed
        return None

