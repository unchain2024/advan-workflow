"""P2: 残高スナップショット取り込み (方式X) — シート → DB opening_balance

Sheet脱却 移行プラン P2。過去履歴を月別に取り込むのではなく、各得意先の
「cutover 月の前月末の残高」を opening_balance に1件だけ取り込む。
これで cutover 月以降の繰越・請求が DB だけで正しく計算できる。

前提・安全性:
- cutover 月は「シートをやめて DB だけにする切替月」。**未来の月**を推奨。
- compute_ledger の遡り計算は「データの無い月」で停止する (_compute_previous_balance)。
  cutover の前月に DB 請求が無ければ、既存の過去 DB データと二重計上しない。
  → シート運用中(=DB に当月分が無い)なら自然に満たされる。
- 冪等: 同じ cutover で再実行しても opening_balance を上書きするだけ。

使い方:
    # 差分確認（書き込みなし）
    venv/bin/python -m scripts.snapshot_opening_balances --cutover "2026年7月" --dry-run
    # 実行
    venv/bin/python -m scripts.snapshot_opening_balances --cutover "2026年7月"

注意: 実行前に cutover の前月に DB 請求が無いことを確認すること
      (audit_sheet_decoupling のカバレッジで確認できる)。
"""
from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.config import DATABASE_PATH
from src.database import MonthlyItemsDB
from src.sheets_client import (
    GoogleSheetsClient,
    normalize_company_name,
    match_company_name,
    parse_amount,
)

# シート Column A の会社以外の行
_SECTION_KEYWORDS = ("合計", "繰越", "相手方", "ライフスタイル", "課税事業者",
                     "非課税仕入", "非課税検品", "課税仕入")


def _is_section_label(name: str) -> bool:
    s = name.strip()
    if not s or s.startswith("【") or s.startswith("["):
        return True
    return any(kw in s for kw in _SECTION_KEYWORDS)


def _parse_year_month(ym: str) -> tuple[int, int]:
    """'2026年7月' -> (2026, 7)"""
    y = int(ym.split("年")[0])
    m = int(ym.split("年")[1].replace("月", ""))
    return y, m


def _prev_year_month(ym: str) -> str:
    y, m = _parse_year_month(ym)
    if m == 1:
        return f"{y - 1}年12月"
    return f"{y}年{m - 1}月"


def _get_arg(flag: str) -> str | None:
    if flag in sys.argv:
        i = sys.argv.index(flag)
        if i + 1 < len(sys.argv):
            return sys.argv[i + 1]
    return None


def main() -> int:
    cutover = _get_arg("--cutover")
    dry_run = "--dry-run" in sys.argv
    overwrite = "--overwrite" in sys.argv

    if not cutover:
        print("ERROR: --cutover \"2026年7月\" を指定してください", file=sys.stderr)
        return 1

    prev_ym = _prev_year_month(cutover)
    prev_year, _ = _parse_year_month(prev_ym)
    print(f"監査対象 DB: {DATABASE_PATH}")
    print(f"cutover: {cutover}  / 取り込む残高: {prev_ym} 末")
    print(f"モード: {'DRY-RUN' if dry_run else ('上書き' if overwrite else '空欄のみ')}")

    db = MonthlyItemsDB()

    # --- 二重計上ガード: cutover 前月に DB 請求が無いか確認 ---
    prev_has_data = [
        r for r in db.get_all_monthly_totals() if r["year_month"] == prev_ym
    ]
    if prev_has_data:
        print(f"\n⚠️ 警告: cutover 前月 {prev_ym} に DB 請求が {len(prev_has_data)}件あります。")
        print("   この状態だと opening_balance と二重計上します。")
        print("   cutover をさらに先の月にするか、前月データを確認してください。")
        if not dry_run:
            print("   中断します（--dry-run で確認のみ可能）。")
            return 1

    # --- シートから前月の残高列を読む ---
    gsc = GoogleSheetsClient()
    sheet = gsc._get_billing_sheet_by_year(prev_year)
    data = sheet.get_all_values()
    row1 = data[0]
    col_idx = None
    for i, v in enumerate(row1):
        if prev_ym in str(v):
            col_idx = i
            break
    if col_idx is None:
        print(f"ERROR: シート {prev_year} に {prev_ym} の列が見つかりません", file=sys.stderr)
        return 1
    zandaka_idx = col_idx + 3  # 発生/消費税/消滅/残高

    # --- DB の sales canonical ---
    sales_master = [c["canonical_name"] for c in db.list_companies("sales", include_inactive=True)]

    applied = 0
    skipped = 0
    unmatched = []
    for r in data[2:]:
        name = str(r[0]).strip() if r else ""
        if not name or _is_section_label(name):
            continue
        zandaka_raw = r[zandaka_idx] if zandaka_idx < len(r) else ""
        balance = parse_amount(zandaka_raw)
        if balance == 0:
            skipped += 1
            continue

        canonical = match_company_name(name, sales_master)
        if not canonical:
            unmatched.append(name)
            continue

        # 既存 opening_balance（上書き判定用）
        existing = db.get_payment(canonical, cutover) or {}
        cur_open = existing.get("opening_balance", 0)
        if cur_open and not overwrite:
            print(f"  [skip] {canonical} 既に opening_balance={cur_open:,} (--overwrite で上書き可)")
            skipped += 1
            continue

        print(f"  {canonical} ← opening_balance({cutover}) = {balance:,} (from {name} {prev_ym}残高)")
        if not dry_run:
            db.save_payment(
                company_name=canonical,
                year_month=cutover,
                payment_amount=existing.get("payment_amount", 0),
                opening_balance=balance,
            )
        applied += 1

    print(f"\n取り込み: {applied}件 / スキップ: {skipped}件")
    if unmatched:
        print(f"\n⚠️ canonical 未一致でスキップ ({len(unmatched)}件):")
        for n in unmatched:
            print(f"    - {n}")
    if dry_run:
        print("\n（DRY-RUN: 何も変更していません）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
