"""仕入: 金額整合（課税で税0→10%、合計=小計+消費税）と 伝票番号検証 の自己完結テスト（pytest不要）

実行:
    venv/bin/python -m scripts.test_purchase_amounts

確認内容:
  1. PurchaseInvoice.normalize_amounts の補正ルール
  2. /api/save-purchase: 伝票番号が空・重複なら 400（DBキー衝突で上書きされるのを防ぐ）
  3. /api/save-purchase: 課税で税0 → 10% 補完、消費税だけ直した場合も合計が揃って保存される
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

os.environ["DATABASE_PATH"] = tempfile.mktemp(suffix=".db")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
BACKEND = PROJECT_ROOT / "backend-api"
for p in (str(PROJECT_ROOT), str(BACKEND)):
    if p not in sys.path:
        sys.path.insert(0, p)

from fastapi.testclient import TestClient  # noqa: E402

from main import app  # noqa: E402
from src.purchase_extractor import PurchaseInvoice, PurchaseItem  # noqa: E402

PASS = 0
FAIL = 0


def check(label: str, cond: bool, info: str = ""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ✓ {label}")
    else:
        FAIL += 1
        print(f"  ✗ {label}  {info}")


def section(title: str):
    print(f"\n=== {title} ===")


def inv(subtotal=0, tax=0, total=0, taxable=True, items=None):
    return PurchaseInvoice(
        date="2026/08/05", supplier_name="X", slip_number="1",
        items=items or [], subtotal=subtotal, tax=tax, total=total, is_taxable=taxable,
    )


# ---------------------------------------------------------------------------
section("1. normalize_amounts")

x = inv(subtotal=1191, tax=0, total=1191, taxable=True)
x.normalize_amounts()
check("課税で税0 → 10%補完 (1191 → tax 119)", x.tax == 119, str(x.tax))
check("合計 = 小計 + 消費税 (1310)", x.total == 1310, str(x.total))

x = inv(subtotal=1191, tax=119, total=1191, taxable=True)  # 東京吉岡: 消費税だけ手入力した状態
x.normalize_amounts()
check("消費税手入力後の合計ズレを補正 (1191 → 1310)", x.total == 1310, str(x.total))

x = inv(subtotal=3136, tax=0, total=3136, taxable=False)
x.normalize_amounts()
check("非課税は税0のまま", x.tax == 0 and x.total == 3136)

x = inv(subtotal=26880, tax=2688, total=29568, taxable=True)  # カネダ: 正常な伝票
applied = x.normalize_amounts()
check("整合している伝票は何も変えない", not applied and x.total == 29568, str(applied))

x = inv(subtotal=-125000, tax=0, total=-125000, taxable=True)  # 返品
x.normalize_amounts()
check("返品（負数）も10%を負で補完", x.tax == -12500 and x.total == -137500, f"{x.tax}/{x.total}")

x = inv(subtotal=0, tax=0, total=1100, taxable=True)
x.normalize_amounts()
check("小計0で合計のみ → 合計を小計として扱い税を補完", x.subtotal == 1100 and x.tax == 110 and x.total == 1210, f"{x.subtotal}/{x.tax}/{x.total}")

x = inv(subtotal=0, tax=0, total=0, taxable=True)
x.normalize_amounts()
check("全部0なら触らない", x.subtotal == 0 and x.tax == 0 and x.total == 0)


# ---------------------------------------------------------------------------
section("2-3. /api/save-purchase")

client = TestClient(app)
COMPANY = "カイハラ㈱"  # 仕入 canonical / 課税固定
YM = "2026-08"


def note(slip, subtotal, tax, total, taxable=True):
    return {
        "date": "2026/08/05", "slip_number": slip,
        "items": [{"product_code": "", "product_name": "品", "quantity": 1, "unit_price": subtotal, "amount": subtotal}],
        "subtotal": subtotal, "tax": tax, "total": total, "is_taxable": taxable,
    }


def save(notes, req_id):
    return client.post("/api/save-purchase", json={
        "company_name": COMPANY, "year_month": YM, "purchase_notes": notes,
        "sales_person": "テスト", "request_id": req_id, "force_overwrite": True,
    })


r = save([note("", 26880, 2688, 29568), note("", 1220, 122, 1342)], "r-empty")
check("伝票番号が空 → 400", r.status_code == 400, str(r.status_code))
d = r.json().get("detail", {}) if r.status_code == 400 else {}
check("error=invalid_slip_numbers / 空2件", d.get("error") == "invalid_slip_numbers" and d.get("empty_indexes") == [1, 2], str(d))

r = save([note("A-1", 100, 10, 110), note("A-1", 200, 20, 220)], "r-dup")
check("伝票番号が重複 → 400", r.status_code == 400 and "A-1" in (r.json().get("detail", {}).get("duplicate_slip_numbers") or []), str(r.status_code))

r = save([note("  ", 100, 10, 110)], "r-blank")
check("空白だけの伝票番号も空扱い → 400", r.status_code == 400, str(r.status_code))

r = save([note("K-1", 26880, 2688, 29568), note("K-2", 1220, 122, 1342)], "r-ok")
check("伝票番号が別なら 2件保存", r.status_code == 200 and r.json().get("saved_count") == 2, r.text[:200])
r = client.get("/api/purchase-delivery-notes", params={"company_name": COMPANY, "year_month": YM})
notes_db = r.json()["notes"]
check("DBに2件残る（上書きされない）", len(notes_db) == 2, str(notes_db))

# 課税で税0 → 10% 補完して保存
r = save([note("T-0", 3136, 0, 3136)], "r-tax0")
check("課税で税0 の伝票を保存 200", r.status_code == 200, r.text[:200])
r = client.get("/api/purchase-delivery-notes", params={"company_name": COMPANY, "year_month": YM})
t0 = next(n for n in r.json()["notes"] if n["slip_number"] == "T-0")
check("保存時に税10%補完 (3136 → 313)", t0["tax"] == 313, str(t0))
check("合計 = 小計+消費税 (3449)", t0["total"] == 3449, str(t0))

# 消費税だけ手入力（合計は古いまま）→ 合計が揃う
r = save([note("Y-1", 1191, 119, 1191)], "r-yoshioka")
r = client.get("/api/purchase-delivery-notes", params={"company_name": COMPANY, "year_month": YM})
y1 = next(n for n in r.json()["notes"] if n["slip_number"] == "Y-1")
check("消費税手入力の伝票: 合計が 1310 に揃う", y1["tax"] == 119 and y1["total"] == 1310, str(y1))

print(f"\n結果: PASS={PASS} FAIL={FAIL}")
sys.exit(1 if FAIL else 0)
