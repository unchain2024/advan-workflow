"""会社名の正規化・マッチング・DB由来の会社解決

旧 Google Sheets 連携モジュール。シート脱却済み(Task A/A-5)のため gspread 依存と
GoogleSheetsClient は撤去。会社名の正規化/マッチング関数と、DB(company_master/
monthly_*)を真値とする会社解決関数のみを提供する。
"""
from dataclasses import dataclass
from datetime import datetime
from typing import Optional
import re

from .canonical_companies import list_canonicals


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


# ===== DB由来の会社解決（シート非依存） =====

def get_canonical_company_name(
    company_name: str,
    year: Optional[int] = None,
    filename: Optional[str] = None,
) -> Optional[str]:
    """売上 canonical 会社名を取得（company_master/canonical 経由・シート非依存）

    year は後方互換のため受け取るが未使用。filename で親/子(HARE事業部等)を判別。
    マッチしない/曖昧な場合は None（フロントの会社ピッカーに戻す）。
    """
    canonical = match_company_name_with_filename(
        company_name, list_canonicals("sales"), filename=filename
    )
    if canonical:
        print(f"    正規会社名取得: '{company_name}' → '{canonical}' (filename={filename!r})")
    return canonical


def get_canonical_purchase_company_name(
    company_name: str,
    year: Optional[int] = None,
    filename: Optional[str] = None,
) -> Optional[str]:
    """仕入 canonical 会社名を取得（company_master/canonical 経由・シート非依存）"""
    canonical = match_company_name_with_filename(
        company_name, list_canonicals("purchase"), filename=filename
    )
    if canonical:
        print(f"    仕入れ正規会社名取得: '{company_name}' → '{canonical}' (filename={filename!r})")
    return canonical


def get_company_info(company_name: str) -> Optional[CompanyInfo]:
    """会社情報（郵便番号・住所・事業部）を company_master(DB) から取得

    法人格(株式会社/(株)等)と敬称(御中/様)を除去してマッチング。
    """
    from .database import MonthlyItemsDB
    db = MonthlyItemsDB()
    companies = db.list_companies("sales", include_inactive=True)
    master_names = [c["canonical_name"] for c in companies]
    matched = match_company_name(company_name, master_names)
    if not matched:
        return None
    for c in companies:
        if c["canonical_name"] == matched:
            return CompanyInfo(
                company_name=c["canonical_name"],
                postal_code=c["postal_code"],
                address=c["address"],
                department=c["department"],
            )
    return None


def get_previous_billing(
    company_name: str, current_year_month: Optional[str] = None
) -> PreviousBilling:
    """前月の請求情報を DB(compute_ledger) から計算（シート非依存）"""
    try:
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

        from .database import MonthlyItemsDB
        db = MonthlyItemsDB()
        ledger = db.compute_ledger(company_name, current_ym_jp)

        previous_amount = ledger["previous_balance"]
        payment_received = ledger["payment_amount"]
        carried_over = previous_amount - payment_received

        print(f"    [DB] 前月残高: ¥{previous_amount:,} / 当月消滅: ¥{payment_received:,}"
              f" / 差引繰越: ¥{carried_over:,}")

        return PreviousBilling(
            previous_amount=previous_amount,
            payment_received=payment_received,
            carried_over=carried_over,
            sales_amount=ledger["subtotal"],
            tax_amount=ledger["tax"],
            current_amount=0,
        )
    except Exception as e:
        print(f"    [DB] previous_billing 計算エラー: {e}")
        import traceback
        traceback.print_exc()
        return PreviousBilling(0, 0, 0, 0, 0, 0)
