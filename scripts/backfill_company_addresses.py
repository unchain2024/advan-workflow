"""会社マスター(Google Sheets「マスター」) → company_master(DB) 住所バックフィル

P1 のコールドスタート用。一度きり実行すれば、既存得意先の住所・郵便番号・事業部が
DB に取り込まれ、以降ランタイムは Google Sheets に一切依存しなくなる。

マスターシートの想定フォーマット:
    | 会社名 | 事業部 | 郵便番号 | 住所 | ビル名 |

使い方:
    venv/bin/python -m scripts.backfill_company_addresses          # 空欄のみ埋める(既定)
    venv/bin/python -m scripts.backfill_company_addresses --overwrite  # 既存値も上書き
    venv/bin/python -m scripts.backfill_company_addresses --dry-run    # 変更せず差分表示
"""
from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.sheets_client import (
    GoogleSheetsClient,
    match_company_name,
    COMPANY_MASTER_SPREADSHEET_ID,
    COMPANY_MASTER_SHEET_NAME,
)
from src.database import MonthlyItemsDB


def main() -> int:
    overwrite = "--overwrite" in sys.argv
    dry_run = "--dry-run" in sys.argv

    if not COMPANY_MASTER_SPREADSHEET_ID:
        print("ERROR: COMPANY_MASTER_SPREADSHEET_ID が未設定です", file=sys.stderr)
        return 1

    print(f"モード: {'DRY-RUN' if dry_run else ('上書き' if overwrite else '空欄のみ補完')}")

    # 1. マスターシート読込
    client = GoogleSheetsClient()
    sheet = client.client.open_by_key(COMPANY_MASTER_SPREADSHEET_ID).worksheet(
        COMPANY_MASTER_SHEET_NAME
    )
    records = sheet.get_all_records()
    print(f"マスターシート: {len(records)}件 読込")

    # 2. DB の sales マスタ（無効含む）
    db = MonthlyItemsDB()
    companies = db.list_companies("sales", include_inactive=True)
    print(f"company_master(sales): {len(companies)}件")

    sheet_names = [str(r.get("会社名", "")) for r in records]

    updated = 0
    skipped = 0
    unmatched_db = []

    for c in companies:
        # DB の canonical 名にマッチするマスターシート行を探す
        matched = match_company_name(c["canonical_name"], sheet_names)
        if not matched:
            unmatched_db.append(c["canonical_name"])
            continue

        record = next((r for r in records if str(r.get("会社名", "")) == matched), None)
        if not record:
            unmatched_db.append(c["canonical_name"])
            continue

        postal = str(record.get("郵便番号", "")).strip()
        address = str(record.get("住所", "")).strip()
        building = str(record.get("ビル名", "")).strip()
        full_address = f"{address} {building}".strip()
        department = str(record.get("事業部", "")).strip()

        # 補完対象の判定（overwrite なら常に、そうでなければ DB が空のときだけ）
        new_postal = postal if (overwrite or not c["postal_code"]) else c["postal_code"]
        new_address = full_address if (overwrite or not c["address"]) else c["address"]
        new_dept = department if (overwrite or not c["department"]) else c["department"]

        if (new_postal, new_address, new_dept) == (
            c["postal_code"], c["address"], c["department"],
        ):
            skipped += 1
            continue

        print(f"  {c['canonical_name']} ← 〒{new_postal} / {new_address} / {new_dept}")
        if not dry_run:
            db.update_company(
                c["id"],
                postal_code=new_postal,
                address=new_address,
                department=new_dept,
            )
        updated += 1

    print(f"\n更新: {updated}件 / 変更なし: {skipped}件")
    if unmatched_db:
        print(f"\n⚠️ マスターシートに見つからなかった DB 会社 ({len(unmatched_db)}件):")
        for name in unmatched_db:
            print(f"    - {name}")
        print("  → これらは画面から手動で住所を入力してください")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
