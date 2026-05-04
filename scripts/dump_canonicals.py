"""売上シート・仕入シートの会社名を全部ダンプ

取得した結果を src/canonical_companies.py にハードコードして、
シート読込みなしで canonical 会社マッチが動作するようにする。

使い方:
    venv/bin/python -m scripts.dump_canonicals > /tmp/canonicals.txt
    # 出力を見て section header 等を除外し、
    # src/canonical_companies.py にコピペする
"""
from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.sheets_client import GoogleSheetsClient


def dump_sales(client: GoogleSheetsClient, years=(2024, 2025, 2026, 2027)) -> dict[str, list[tuple[int, str]]]:
    """売上シートの会社名 (Column A, row 3+) を年別に取得"""
    result: dict[str, list[tuple[int, str]]] = {}
    for year in years:
        try:
            sheet = client._get_billing_sheet_by_year(year)
            col_a = sheet.col_values(1)
            rows = []
            for i, v in enumerate(col_a, start=1):
                if i < 3:  # row 1-2 はヘッダ
                    continue
                if v and str(v).strip():
                    rows.append((i, str(v).strip()))
            result[f"売上{year}"] = rows
        except Exception as e:
            print(f"# WARN: 売上シート {year} 取得失敗: {type(e).__name__}: {e}", file=sys.stderr)
    return result


def dump_purchase(client: GoogleSheetsClient, years=(2024, 2025, 2026, 2027)) -> dict[str, list[tuple[int, str]]]:
    """仕入シートの Column A 全行を取得 (section header 含む)"""
    result: dict[str, list[tuple[int, str]]] = {}
    for year in years:
        try:
            sheet = client._get_purchase_sheet_by_year(year)
            col_a = sheet.col_values(1)
            rows = []
            for i, v in enumerate(col_a, start=1):
                if v and str(v).strip():
                    rows.append((i, str(v).strip()))
            result[f"仕入{year}"] = rows
        except Exception as e:
            print(f"# WARN: 仕入シート {year} 取得失敗: {type(e).__name__}: {e}", file=sys.stderr)
    return result


def main() -> int:
    client = GoogleSheetsClient()

    print("=" * 80)
    print("売上シート (Column A, row 3+)")
    print("=" * 80)
    sales = dump_sales(client)
    sales_unique: set[str] = set()
    for year_label, rows in sales.items():
        print(f"\n## {year_label} ({len(rows)} 行)")
        for row_idx, name in rows:
            print(f"  行{row_idx:>3}: {name}")
            sales_unique.add(name)

    print()
    print("=" * 80)
    print(f"売上 ユニーク会社名 ({len(sales_unique)} 件)")
    print("=" * 80)
    for name in sorted(sales_unique):
        print(f"  {name!r},")

    print()
    print("=" * 80)
    print("仕入シート (Column A 全行 — section header含む)")
    print("=" * 80)
    purchase = dump_purchase(client)
    purchase_unique: set[str] = set()
    for year_label, rows in purchase.items():
        print(f"\n## {year_label} ({len(rows)} 行)")
        for row_idx, name in rows:
            print(f"  行{row_idx:>3}: {name}")
            purchase_unique.add(name)

    print()
    print("=" * 80)
    print(f"仕入 ユニーク値 ({len(purchase_unique)} 件) — 要レビュー（section header 等を除外）")
    print("=" * 80)
    for name in sorted(purchase_unique):
        print(f"  {name!r},")

    return 0


if __name__ == "__main__":
    sys.exit(main())
