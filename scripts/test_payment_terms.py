"""締め日・支払日（支払条件）の自己完結テスト（pytest不要・LLM呼出なし）

実行:
    venv/bin/python -m scripts.test_payment_terms

確認内容:
  1. 締め日/支払日の正規化と不正形式の検出
  2. 計上月の計算（月末締め / N日締め / 年またぎ / 日付不明）
  3. 支払予定日の計算（翌月末 / 翌々月N日 / 月末丸め）
  4. マスタAPI: 締め日/支払日の保存・更新・不正値400・既存DBへの列追加（マイグレーション）
  5. /purchase-company-terms と /purchase-table の支払予定日列
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
from src.payment_terms import (  # noqa: E402
    PaymentTermsError,
    compute_payment_due_date,
    compute_target_year_month,
    normalize_closing_day,
    normalize_payment_day,
)

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


def raises(fn):
    try:
        fn()
        return False
    except PaymentTermsError:
        return True


# ---------------------------------------------------------------------------
section("1. 正規化")
check("月末系 → 月末", all(normalize_closing_day(x) == "月末" for x in ["月末", "末日", "末", "31", "31日"]))
check("20 / 20日 / ２０日 → 20日", all(normalize_closing_day(x) == "20日" for x in ["20", "20日", "２０日"]))
check("空は空のまま（未設定）", normalize_closing_day("") == "" and normalize_payment_day("") == "")
check("締め日の不正値は弾く", raises(lambda: normalize_closing_day("毎週")) and raises(lambda: normalize_closing_day("0日")))
check("翌月末日 → 翌月末", normalize_payment_day("翌月末日") == "翌月末")
check("翌々月 5 → 翌々月5日", normalize_payment_day("翌々月 5") == "翌々月5日")
check("支払日の不正値は弾く", raises(lambda: normalize_payment_day("来月10日")) and raises(lambda: normalize_payment_day("翌月32日")))

section("2. 計上月")
check("月末締め: 納品日の月", compute_target_year_month("2026/07/31", "月末") == "2026年7月")
check("未設定は月末扱い", compute_target_year_month("2026/07/31", "") == "2026年7月")
check("20日締め: 20日は当月", compute_target_year_month("2026/07/20", "20日") == "2026年7月")
check("20日締め: 21日は翌月", compute_target_year_month("2026/07/21", "20日") == "2026年8月")
check("20日締め: 12/25 は翌年1月", compute_target_year_month("2026/12/25", "20日") == "2027年1月")
check("YYYY-MM-DD も読める", compute_target_year_month("2026-07-23", "20日") == "2026年8月")
check("日付不明は空", compute_target_year_month("", "20日") == "" and compute_target_year_month("不明", "月末") == "")

section("3. 支払予定日")
check("2026年7月 + 翌月末 → 2026/08/31", compute_payment_due_date("2026年7月", "翌月末") == "2026/08/31")
check("2026年1月 + 翌月末 → 2026/02/28（うるう年でない）", compute_payment_due_date("2026年1月", "翌月末") == "2026/02/28")
check("2026年7月 + 翌々月10日 → 2026/09/10", compute_payment_due_date("2026年7月", "翌々月10日") == "2026/09/10")
check("2026年12月 + 翌月10日 → 2027/01/10", compute_payment_due_date("2026年12月", "翌月10日") == "2027/01/10")
check("30日指定で2月は末日に丸める", compute_payment_due_date("2026年1月", "翌月30日") == "2026/02/28")
check("'2026-07' 形式も読める", compute_payment_due_date("2026-07", "当月末") == "2026/07/31")
check("未設定は空", compute_payment_due_date("2026年7月", "") == "")

# ---------------------------------------------------------------------------
section("4. マスタAPI（締め日・支払日）")
client = TestClient(app)

r = client.get("/api/company-master", params={"domain": "purchase"})
check("既存シード行に closing_day/payment_day が空で付く（マイグレーション）",
      r.status_code == 200 and all(c["closing_day"] == "" and c["payment_day"] == "" for c in r.json()["companies"]))

r = client.post("/api/company-master", json={
    "domain": "purchase", "canonical_name": "テスト支払条件㈱",
    "closing_day": "20日", "payment_day": "翌月末", "taxable": True,
})
check("締め日/支払日付きで追加 200", r.status_code == 200, r.text[:200])
cid = r.json().get("id")
check("保存値が正規形", r.status_code == 200 and r.json()["closing_day"] == "20日" and r.json()["payment_day"] == "翌月末")

r = client.post("/api/company-master", json={
    "domain": "purchase", "canonical_name": "テスト不正㈱", "closing_day": "毎週",
})
check("不正な締め日は 400", r.status_code == 400, str(r.status_code))
r = client.post("/api/company-master", json={
    "domain": "purchase", "canonical_name": "テスト不正㈱", "payment_day": "来月末",
})
check("不正な支払日は 400", r.status_code == 400, str(r.status_code))

r = client.patch(f"/api/company-master/{cid}", json={"closing_day": "月末", "payment_day": "翌々月10日"})
check("PATCH で更新", r.status_code == 200 and r.json()["closing_day"] == "月末" and r.json()["payment_day"] == "翌々月10日", r.text[:200])
r = client.patch(f"/api/company-master/{cid}", json={"address": "住所だけ更新"})
check("他項目のPATCHで支払条件は保持", r.json()["closing_day"] == "月末" and r.json()["payment_day"] == "翌々月10日")
r = client.patch(f"/api/company-master/{cid}", json={"closing_day": "", "payment_day": ""})
check("空を渡すと未設定に戻る", r.json()["closing_day"] == "" and r.json()["payment_day"] == "")
client.patch(f"/api/company-master/{cid}", json={"closing_day": "20日", "payment_day": "翌月末"})

# ---------------------------------------------------------------------------
section("5. 仕入APIの支払条件")
r = client.get("/api/purchase-company-terms", params={"company_name": "テスト支払条件㈱"})
check("/purchase-company-terms: マスタの値を返す",
      r.status_code == 200 and r.json()["closing_day"] == "20日" and r.json()["closing_day_from_master"] is True
      and r.json()["payment_day"] == "翌月末", r.text[:200])
r = client.get("/api/purchase-company-terms", params={"company_name": "カイハラ㈱"})
check("未設定の仕入先は月末・マスタ由来でない",
      r.status_code == 200 and r.json()["closing_day"] == "月末" and r.json()["closing_day_from_master"] is False)

# 伝票を保存して purchase-table に支払予定日が出るか
r = client.post("/api/save-purchase", json={
    "company_name": "テスト支払条件㈱", "year_month": "2026-07",
    "purchase_notes": [{
        "date": "2026/07/23", "slip_number": "P-1",
        "items": [{"product_code": "", "product_name": "品", "quantity": 1, "unit_price": 1000, "amount": 1000}],
        "subtotal": 1000, "tax": 100, "total": 1100, "is_taxable": True,
    }],
    "sales_person": "テスト", "request_id": "terms-1", "force_overwrite": True,
})
check("保存 200", r.status_code == 200, r.text[:200])
r = client.get("/api/purchase-table")
j = r.json()
check("ヘッダに '支払予定日' 列がある", any(h.endswith("支払予定日") for h in j["headers"]), str(j["headers"][:8]))
row = next((x for x in j["data"] if x[0] == "テスト支払条件㈱"), None)
idx = j["headers"].index("2026年7月 支払予定日") if "2026年7月 支払予定日" in j["headers"] else -1
check("2026年7月分の支払予定日 = 2026/08/31（翌月末）", row is not None and idx >= 0 and row[idx] == "2026/08/31", str(row))
row_k = next((x for x in j["data"] if x[0] == "カイハラ㈱"), None)
check("支払日未設定の仕入先は空欄（または行なし）", row_k is None or all(not c for i, c in enumerate(row_k) if j["headers"][i].endswith("支払予定日")))

print(f"\n結果: PASS={PASS} FAIL={FAIL}")
sys.exit(1 if FAIL else 0)
