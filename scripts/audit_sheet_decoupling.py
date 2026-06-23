"""P0: Google Sheets 脱却 監査スクリプト（読み取り専用・変更なし）

シートを完全に捨てて DB を唯一の真値にできるかを、データで判定するための監査。
何も書き込まない。安全に何度でも実行できる。

監査項目:
  1. DB カバレッジ      … DB が持つ会社×年月の範囲（売上/仕入）
  2. canonical 未一致   … シート Column A の会社名のうち company_master に無いもの
  3. 売上 突合スイープ  … DB 集計 vs シート集計（発生・消費税）の差分
  4. cutover 分析       … シートにしか無い年月 / DB にしか無い年月

使い方:
    # ローカル dev DB に対して
    venv/bin/python -m scripts.audit_sheet_decoupling

    # 本番DBをダウンロードして監査する場合（推奨）
    DATABASE_PATH=/path/to/prod/monthly_items.db venv/bin/python -m scripts.audit_sheet_decoupling

注意: ローカル dev DB は本番と別物。意味のある突合には本番DBを指定すること。
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
)

SCAN_YEARS = (2024, 2025, 2026, 2027)

# シート Column A に現れる会社以外の行（セクション見出し・合計行）
_SECTION_KEYWORDS = ("合計", "繰越", "相手方", "ライフスタイル", "課税事業者",
                     "非課税仕入", "非課税検品", "課税仕入")


def _is_section_label(name: str) -> bool:
    """会社名ではないセクション見出し/合計行か"""
    s = name.strip()
    if not s:
        return True
    if s.startswith("【") or s.startswith("["):
        return True
    return any(kw in s for kw in _SECTION_KEYWORDS)


def _hr(title: str):
    print("\n" + "=" * 70)
    print(f"  {title}")
    print("=" * 70)


def _parse_year(year_month: str) -> int | None:
    """'2026年3月' → 2026"""
    try:
        return int(year_month.split("年")[0])
    except (ValueError, IndexError):
        return None


def audit_db_coverage(db: MonthlyItemsDB) -> dict:
    _hr("1. DB カバレッジ")
    sales = db.get_all_monthly_totals()
    purchase = db.get_all_purchase_monthly_totals()

    def _summ(rows, label):
        yms = sorted({r["year_month"] for r in rows})
        companies = sorted({r["company_name"] for r in rows})
        print(f"\n[{label}] レコード {len(rows)}件 / 会社 {len(companies)}社 / 年月 {len(yms)}種")
        if yms:
            print(f"    年月レンジ: {yms[0]} 〜 {yms[-1]}")
            print(f"    年月一覧: {', '.join(yms)}")
        return {"year_months": yms, "companies": companies, "rows": len(rows)}

    return {
        "sales": _summ(sales, "売上"),
        "purchase": _summ(purchase, "仕入"),
    }


def audit_canonical_mismatch(gsc: GoogleSheetsClient, db: MonthlyItemsDB) -> dict:
    _hr("2. canonical 未一致（シートにあるが company_master に無い会社）")
    result = {}

    # --- 売上 ---
    sales_master = [c["canonical_name"] for c in db.list_companies("sales", include_inactive=True)]
    sheet_sales_names: set[str] = set()
    for year in SCAN_YEARS:
        try:
            sheet = gsc._get_billing_sheet_by_year(year)
            col_a = [v.strip() for v in sheet.col_values(1)[2:] if v.strip()]
            sheet_sales_names.update(col_a)
        except Exception as e:
            print(f"  (売上シート {year} スキップ: {type(e).__name__})")
    # セクション見出し/合計行は除外
    sales_unmatched = []
    for name in sorted(sheet_sales_names):
        if _is_section_label(name):
            continue
        if not match_company_name(name, sales_master):
            sales_unmatched.append(name)
    print(f"\n[売上] シート会社名 {len(sheet_sales_names)}種 / master {len(sales_master)}件")
    if sales_unmatched:
        print(f"  ⚠️ 未一致 {len(sales_unmatched)}件:")
        for n in sales_unmatched:
            print(f"      - {n}")
    else:
        print("  ✓ シートの全会社が master にマッチ")
    result["sales_unmatched"] = sales_unmatched

    # --- 仕入 ---
    purchase_master = [c["canonical_name"] for c in db.list_companies("purchase", include_inactive=True)]
    try:
        pdata = gsc.get_purchase_companies_and_months()
        sheet_purchase_names = pdata["companies"]
    except Exception as e:
        print(f"\n  (仕入シート スキップ: {type(e).__name__})")
        sheet_purchase_names = []
    purchase_unmatched = [
        n for n in sheet_purchase_names if not match_company_name(n, purchase_master)
    ]
    print(f"\n[仕入] シート会社名 {len(sheet_purchase_names)}種 / master {len(purchase_master)}件")
    if purchase_unmatched:
        print(f"  ⚠️ 未一致 {len(purchase_unmatched)}件:")
        for n in purchase_unmatched:
            print(f"      - {n}")
    else:
        print("  ✓ シートの全会社が master にマッチ")
    result["purchase_unmatched"] = purchase_unmatched
    return result


def audit_sales_reconciliation(gsc: GoogleSheetsClient, db: MonthlyItemsDB) -> dict:
    _hr("3. 売上 突合スイープ（DB集計 vs シート集計）")
    db_rows = db.get_all_monthly_totals()
    # キー: (normalized company, year_month) → (subtotal, tax)
    db_map = {
        (normalize_company_name(r["company_name"]), r["year_month"]): (r["subtotal"], r["tax"])
        for r in db_rows
    }

    sheet_map: dict = {}
    db_years = {_parse_year(r["year_month"]) for r in db_rows} | set(SCAN_YEARS)
    for year in sorted(y for y in db_years if y):
        try:
            for s in gsc.get_billing_amounts(year):
                if _is_section_label(s["company_name"]):
                    continue  # 合計行・見出しは突合対象外
                key = (normalize_company_name(s["company_name"]), s["year_month"])
                sheet_map[key] = (s["subtotal"], s["tax"])
        except Exception as e:
            print(f"  (売上シート {year} スキップ: {type(e).__name__})")

    diffs = []
    db_only = []
    sheet_only_nonzero = []
    all_keys = set(db_map) | set(sheet_map)
    for key in sorted(all_keys):
        dv = db_map.get(key)
        sv = sheet_map.get(key)
        comp, ym = key
        if dv and sv:
            if dv != sv:
                diffs.append((comp, ym, dv, sv))
        elif dv and not sv:
            if dv != (0, 0):
                db_only.append((comp, ym, dv))
        elif sv and not dv:
            if sv != (0, 0):
                sheet_only_nonzero.append((comp, ym, sv))

    print(f"\n比較キー総数: {len(all_keys)}（DB:{len(db_map)} / シート:{len(sheet_map)}）")

    print(f"\n[A] 値が食い違う (DB≠シート, 両方非ゼロ): {len(diffs)}件")
    for comp, ym, dv, sv in diffs[:50]:
        print(f"    {comp} {ym}: DB(発生={dv[0]:,},税={dv[1]:,}) ≠ シート(発生={sv[0]:,},税={sv[1]:,})")

    print(f"\n[B] DBにあるがシートに無い（非ゼロ）: {len(db_only)}件")
    for comp, ym, dv in db_only[:30]:
        print(f"    {comp} {ym}: DB(発生={dv[0]:,},税={dv[1]:,})")

    print(f"\n[C] シートにあるがDBに無い（非ゼロ）= 取り込み未済の履歴: {len(sheet_only_nonzero)}件")
    for comp, ym, sv in sheet_only_nonzero[:60]:
        print(f"    {comp} {ym}: シート(発生={sv[0]:,},税={sv[1]:,})")
    if len(sheet_only_nonzero) > 60:
        print(f"    ... 他 {len(sheet_only_nonzero) - 60}件")

    return {
        "diffs": len(diffs),
        "db_only": len(db_only),
        "sheet_only_nonzero": len(sheet_only_nonzero),
    }


def audit_cutover(coverage: dict, gsc: GoogleSheetsClient) -> dict:
    _hr("4. cutover 分析（年月の DB / シート 突き合わせ）")
    db_yms = set(coverage["sales"]["year_months"])

    sheet_yms: set[str] = set()
    for year in SCAN_YEARS:
        try:
            sheet = gsc._get_billing_sheet_by_year(year)
            row1 = sheet.row_values(1)
            sheet_yms.update(ym for ym in row1 if "年" in str(ym) and "月" in str(ym))
        except Exception:
            pass

    only_sheet = sorted(sheet_yms - db_yms)
    only_db = sorted(db_yms - sheet_yms)
    both = sorted(db_yms & sheet_yms)
    print(f"\n両方にある年月: {len(both)}  {both}")
    print(f"シートのみ（DB未取り込み）: {len(only_sheet)}  {only_sheet}")
    print(f"DBのみ（シートに列なし）: {len(only_db)}  {only_db}")
    return {"only_sheet": only_sheet, "only_db": only_db, "both": both}


def main() -> int:
    print(f"監査対象 DB: {DATABASE_PATH}")
    print("（注: ローカル dev DB の場合、突合結果[C]は本番と異なる）")

    db = MonthlyItemsDB()
    gsc = GoogleSheetsClient()

    coverage = audit_db_coverage(db)
    canon = audit_canonical_mismatch(gsc, db)
    recon = audit_sales_reconciliation(gsc, db)
    cutover = audit_cutover(coverage, gsc)

    _hr("判定サマリ")
    issues = []
    if canon["sales_unmatched"]:
        issues.append(f"売上 canonical 未一致 {len(canon['sales_unmatched'])}件 → master に追加要")
    if canon["purchase_unmatched"]:
        issues.append(f"仕入 canonical 未一致 {len(canon['purchase_unmatched'])}件 → master に追加要")
    if recon["diffs"]:
        issues.append(f"売上 値食い違い {recon['diffs']}件 → 要調査（DB≠シート）")
    if recon["sheet_only_nonzero"]:
        issues.append(
            f"シートのみの履歴 {recon['sheet_only_nonzero']}件 → P2 残高取り込み or 要確認"
        )
    if cutover["only_sheet"]:
        issues.append(f"シートのみの年月 {len(cutover['only_sheet'])} → cutover 設計に反映")

    if issues:
        print("\n⚠️ 移行前に対処が必要な項目:")
        for i in issues:
            print(f"    - {i}")
    else:
        print("\n✓ 重大な差分なし。シート脱却に進める状態。")
    print("\n（このスクリプトは何も変更していません）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
