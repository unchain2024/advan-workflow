"""シート脱却 + 得意先マスタ の自己完結テスト（pytest不要）

一時DBを使い、Google認証を必要としないパスを中心に検証する。

実行:
    venv/bin/python -m scripts.test_sheet_decoupling

確認内容:
  1. company_master CRUD（追加/一覧/編集/無効化/重複検知/ドメイン検証）
  2. canonical 配線がDB由来（追加した会社が list_canonicals / match に出る）
  3. シート読込API がDB由来で動く（/companies-and-months, /billing-table 等）
  4. シート比較/同期/書込API が「廃止」されている（ルート不在）
  5. 入金(消滅)がDBに保存される（/update-payment, /payments はシート非依存）
  6. compute_ledger の繰越計算（opening_balance からの積み上げ）
"""
from __future__ import annotations

import sys
import os
import tempfile
from pathlib import Path

# 一時DB（実DBを汚さない）。config 読み込み前に設定する。
os.environ["DATABASE_PATH"] = tempfile.mktemp(suffix=".db")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
BACKEND = PROJECT_ROOT / "backend-api"
for p in (str(PROJECT_ROOT), str(BACKEND)):
    if p not in sys.path:
        sys.path.insert(0, p)

from fastapi.testclient import TestClient  # noqa: E402
from main import app  # noqa: E402
from src.database import MonthlyItemsDB  # noqa: E402
from src.pdf_extractor import DeliveryNote, DeliveryItem  # noqa: E402
from src.canonical_companies import list_canonicals  # noqa: E402
from src.sheets_client import match_company_name  # noqa: E402

_PASS = 0
_FAIL = 0


def check(name: str, cond: bool, detail: str = ""):
    global _PASS, _FAIL
    if cond:
        _PASS += 1
        print(f"  ✅ {name}")
    else:
        _FAIL += 1
        print(f"  ❌ {name}  {detail}")


def section(title: str):
    print(f"\n=== {title} ===")


client = TestClient(app)
db = MonthlyItemsDB()


# ---------------------------------------------------------------------------
# 1. company_master CRUD
# ---------------------------------------------------------------------------
section("1. 得意先マスタ CRUD")

r = client.get("/api/company-master", params={"domain": "sales"})
check("GET sales 一覧 200", r.status_code == 200, str(r.status_code))
seed_count = len(r.json()["companies"])
check("シード済み(>=57件)", seed_count >= 57, f"count={seed_count}")

r = client.post("/api/company-master", json={
    "domain": "sales", "canonical_name": "テスト商事㈱",
    "postal_code": "100-0001", "address": "東京都千代田区1-1", "department": "営業部",
})
check("POST 追加 200", r.status_code == 200, str(r.status_code))
new_id = r.json().get("id")

r = client.post("/api/company-master", json={"domain": "sales", "canonical_name": "株式会社テスト商事"})
check("重複(表記ゆれ)を400で弾く", r.status_code == 400, str(r.status_code))

r = client.post("/api/company-master", json={"domain": "purchase", "canonical_name": "テスト仕入㈱", "taxable": False})
check("仕入 taxable=False で追加", r.status_code == 200 and r.json()["taxable"] is False)

r = client.patch(f"/api/company-master/{new_id}", json={"address": "更新後住所"})
check("PATCH 編集 200", r.status_code == 200 and r.json()["address"] == "更新後住所")

r = client.delete(f"/api/company-master/{new_id}")
check("DELETE 論理削除(is_active=False)", r.status_code == 200 and r.json()["is_active"] is False)

r = client.get("/api/company-master", params={"domain": "sales"})
active_names = [c["canonical_name"] for c in r.json()["companies"]]
check("無効化後は有効一覧に出ない", "テスト商事㈱" not in active_names)
r = client.get("/api/company-master", params={"domain": "sales", "include_inactive": True})
all_names = [c["canonical_name"] for c in r.json()["companies"]]
check("include_inactive では出る", "テスト商事㈱" in all_names)

r = client.get("/api/company-master", params={"domain": "foo"})
check("不正domainを400で弾く", r.status_code == 400, str(r.status_code))


# ---------------------------------------------------------------------------
# 2. canonical 配線がDB由来
# ---------------------------------------------------------------------------
section("2. canonical 配線がDB由来")

db.add_company("sales", "新規得意先テスト㈱")
sales_canon = list_canonicals("sales")
check("追加会社が list_canonicals に出る", "新規得意先テスト㈱" in sales_canon)
matched = match_company_name("新規得意先テスト", sales_canon)
check("敬称/法人格ゆれでマッチ", matched == "新規得意先テスト㈱", f"matched={matched}")


# ---------------------------------------------------------------------------
# 3. シート読込API がDB由来
# ---------------------------------------------------------------------------
section("3. シート読込API がDB由来")

# データ投入（売上: 連続2ヶ月 + 入金/繰越）
COMP = "台帳テスト㈱"
db.add_company("sales", COMP)


def _note(slip, sub, tax, date):
    return DeliveryNote(
        date=date, company_name=COMP, slip_number=slip,
        items=[DeliveryItem(slip_number=slip, product_code="P", product_name="品",
                            quantity=1, unit_price=sub, amount=sub)],
        subtotal=sub, tax=tax, total=sub + tax, payment_received=0,
    )


db.save_monthly_items_batch(COMP, "2025年1月", [_note("S1", 10000, 1000, "2025/01/15")])
db.save_monthly_items_batch(COMP, "2025年2月", [_note("S2", 5000, 500, "2025/02/15")])
# 1月: opening_balance=1000, 2月: payment=2000
db.upsert_payment(COMP, "2025年1月", payment_amount=0, opening_balance=1000)
db.upsert_payment(COMP, "2025年2月", payment_amount=2000)

r = client.get("/api/companies-and-months")
check("/companies-and-months 200", r.status_code == 200)
j = r.json()
check("会社に master とテストデータ両方含む",
      COMP in j["companies"] and len(j["companies"]) >= 57)
check("年月にDBの月が出る", "2025年1月" in j["year_months"] and "2025年2月" in j["year_months"])

r = client.get("/api/billing-table")
check("/billing-table 200", r.status_code == 200)
j = r.json()
check("集計表ヘッダがDB形式(会社名+月別)", j["headers"] and j["headers"][0] == "会社名"
      and any("発生" in h for h in j["headers"]))
check("集計表に台帳テストの行がある", any(row and row[0] == COMP for row in j["data"]))

r = client.get("/api/purchase-companies-and-months")
check("/purchase-companies-and-months 200(masterで94+)", r.status_code == 200
      and len(r.json()["companies"]) >= 94)
r = client.get("/api/purchase-table")
check("/purchase-table 200", r.status_code == 200 and "headers" in r.json())


# ---------------------------------------------------------------------------
# 4. シート比較/同期/書込API が廃止されている
# ---------------------------------------------------------------------------
section("4. シート系API が廃止されている")

routes = {getattr(r, "path", "") for r in app.routes}
for gone in ["/api/check-discrepancy", "/api/sync-sheets-from-db",
             "/api/sync-purchase-sheets-from-db"]:
    check(f"{gone} ルート不在", gone not in routes)
for kept in ["/api/companies-and-months", "/api/billing-table",
             "/api/company-master", "/api/update-payment"]:
    check(f"{kept} ルート存在", kept in routes)


# ---------------------------------------------------------------------------
# 5. 入金がDBに保存される（シート非依存）
# ---------------------------------------------------------------------------
section("5. 入金(消滅)がDBに保存される")

r = client.post("/api/update-payment", json={
    "company_name": COMP, "year_month": "2025年2月",
    "payment_amount": 3000, "add_mode": False,
})
check("/update-payment 200(シート非依存)", r.status_code == 200, str(r.status_code))
pay = db.get_payment(COMP, "2025年2月")
check("DBに入金が反映", (pay or {}).get("payment_amount") == 3000,
      f"db={pay}")


# ---------------------------------------------------------------------------
# 6. compute_ledger 繰越計算
# ---------------------------------------------------------------------------
section("6. compute_ledger 繰越計算")

# update-payment で 2月 payment=3000 に変わった。改めて確定値で検証用に戻す
db.upsert_payment(COMP, "2025年2月", payment_amount=2000)

led1 = db.compute_ledger(COMP, "2025年1月")
# 1月: opening 1000 + 発生10000 + 税1000 - 入金0 = 12000
check("1月 繰越 = opening+発生+税", led1["carried_over"] == 12000,
      f"got={led1['carried_over']}")

led2 = db.compute_ledger(COMP, "2025年2月")
# 2月: 前月12000 + 発生5000 + 税500 - 入金2000 = 15500
check("2月 前月残高 = 1月繰越", led2["previous_balance"] == 12000,
      f"got={led2['previous_balance']}")
check("2月 繰越 = 前月+発生+税-入金", led2["carried_over"] == 15500,
      f"got={led2['carried_over']}")


# ---------------------------------------------------------------------------
# まとめ
# ---------------------------------------------------------------------------
print(f"\n{'=' * 50}")
print(f"  結果: {_PASS} PASS / {_FAIL} FAIL")
print(f"{'=' * 50}")

try:
    os.remove(os.environ["DATABASE_PATH"])
except OSError:
    pass

sys.exit(1 if _FAIL else 0)
