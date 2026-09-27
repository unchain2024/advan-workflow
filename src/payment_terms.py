"""締め日・支払日（支払条件）の解釈と、計上月・支払予定日の計算

仕入先マスタ(company_master)に持つ文字列の形式:
  closing_day（締め日）:  "" (未設定=月末扱い) | "月末" | "N日"  (N=1..30)
  payment_day（支払日）:  "" (未設定) | "{当月|翌月|翌々月}{末|N日}"  例: "翌月末", "翌月10日", "翌々月5日"

計上月の考え方:
  納品日が締め日以前ならその月、締め日より後なら翌月に計上する（20日締め: 21日〜翌20日 → 翌月）。
  月末締めは納品日の月。
"""
from __future__ import annotations

import calendar
import re
import unicodedata
from datetime import datetime
from typing import Optional

DEFAULT_CLOSING_DAY = "月末"

_MONTH_OFFSET = {"当月": 0, "翌月": 1, "翌々月": 2}


class PaymentTermsError(ValueError):
    """締め日/支払日の形式が不正"""


def _nfkc(s: str) -> str:
    return unicodedata.normalize("NFKC", str(s or "")).strip()


def normalize_closing_day(value: str) -> str:
    """締め日文字列を正規形にする。空は "" のまま（=未設定・月末扱い）

    受け付ける例: "月末", "末日", "末", "31", "20", "20日", "２０日"
    Raises:
        PaymentTermsError: 解釈できない
    """
    s = _nfkc(value)
    if not s:
        return ""
    if s in ("月末", "末日", "末", "31", "31日"):
        return "月末"
    m = re.fullmatch(r"(\d{1,2})\s*日?", s)
    if m:
        n = int(m.group(1))
        if 1 <= n <= 30:
            return f"{n}日"
        if n == 31:
            return "月末"
    raise PaymentTermsError(f"締め日の形式が不正です: '{value}'（例: 月末, 20日）")


def normalize_payment_day(value: str) -> str:
    """支払日文字列を正規形にする。空は "" のまま（=未設定）

    受け付ける例: "翌月末", "翌月10日", "翌々月末", "当月25日", "翌月末日"
    Raises:
        PaymentTermsError: 解釈できない
    """
    s = _nfkc(value)
    if not s:
        return ""
    m = re.fullmatch(r"(当月|翌月|翌々月)\s*(末日|末|月末|\d{1,2}\s*日?)", s)
    if not m:
        raise PaymentTermsError(
            f"支払日の形式が不正です: '{value}'（例: 翌月末, 翌月10日, 翌々月5日）"
        )
    base, day = m.group(1), m.group(2)
    if day in ("末日", "末", "月末"):
        return f"{base}末"
    n = int(re.sub(r"\D", "", day))
    if n == 31:
        return f"{base}末"
    if not 1 <= n <= 30:
        raise PaymentTermsError(f"支払日の日付が不正です: '{value}'")
    return f"{base}{n}日"


def closing_day_number(closing_day: str) -> Optional[int]:
    """'20日' → 20、'月末'/'' → None（月末）"""
    c = normalize_closing_day(closing_day)
    if not c or c == "月末":
        return None
    return int(c.replace("日", ""))


def _parse_date(date_str: str) -> Optional[tuple[int, int, Optional[int]]]:
    """'YYYY/MM/DD' | 'YYYY-MM-DD' | 'YYYY/MM' → (year, month, day|None)"""
    s = _nfkc(date_str).replace("-", "/").replace(".", "/")
    m = re.match(r"^(\d{4})/(\d{1,2})(?:/(\d{1,2}))?", s)
    if not m:
        m2 = re.match(r"^(\d{4})年(\d{1,2})月(?:(\d{1,2})日)?", s)
        if not m2:
            return None
        m = m2
    y, mo = int(m.group(1)), int(m.group(2))
    d = int(m.group(3)) if m.group(3) else None
    if not 1 <= mo <= 12:
        return None
    return y, mo, d


def _shift_month(year: int, month: int, offset: int) -> tuple[int, int]:
    idx = (year * 12 + (month - 1)) + offset
    return idx // 12, idx % 12 + 1


def compute_target_year_month(delivery_date: str, closing_day: str = "") -> str:
    """納品日と締め日から計上月を返す（'YYYY年M月'）。日付が読めなければ ""

    - 月末締め（未設定含む）: 納品日の月
    - N日締め: 納品日 <= N → その月、納品日 > N → 翌月
    """
    parsed = _parse_date(delivery_date)
    if not parsed:
        return ""
    y, mo, d = parsed
    n = closing_day_number(closing_day)
    if n is not None and d is not None and d > n:
        y, mo = _shift_month(y, mo, 1)
    return f"{y}年{mo}月"


def compute_payment_due_date(year_month: str, payment_day: str) -> str:
    """計上月（'YYYY年M月' or 'YYYY-MM'）と支払日から支払予定日を返す（'YYYY/MM/DD'）。未設定なら ""

    例: 2026年7月 + 翌月末 → 2026/08/31、2026年7月 + 翌々月10日 → 2026/09/10
    """
    p = normalize_payment_day(payment_day)
    if not p:
        return ""
    parsed = _parse_date(year_month)
    if not parsed:
        return ""
    y, mo, _ = parsed
    m = re.fullmatch(r"(当月|翌月|翌々月)(末|(\d{1,2})日)", p)
    if not m:
        return ""
    y, mo = _shift_month(y, mo, _MONTH_OFFSET[m.group(1)])
    last = calendar.monthrange(y, mo)[1]
    day = last if m.group(2) == "末" else min(int(m.group(3)), last)
    return f"{y}/{mo:02d}/{day:02d}"


def describe_closing_day(closing_day: str) -> str:
    """表示用: '' → '月末'（未設定）"""
    c = normalize_closing_day(closing_day) if closing_day else ""
    return c or DEFAULT_CLOSING_DAY


def today_str() -> str:
    return datetime.now().strftime("%Y/%m/%d")
