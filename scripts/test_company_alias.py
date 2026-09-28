"""伝票上の別名（company_master.aliases）の自己完結テスト（pytest不要・LLM呼出なし）

実行:
    venv/bin/python -m scripts.test_company_alias

確認内容:
  1. DB: 別名の保存・重複除去・他社との衝突検証・マイグレーション
  2. 照合: 別名で正式名に解決される（CO.,LTD / 末尾ピリオド / 同一会社の複数別名 / 曖昧なら None）
  3. 会社名候補スコアリングが別名一致をマスタ一致として扱う（CLANE → gf.A㈱）
  4. API: 追加/更新/別名追加エンドポイント、衝突は 400、無効化済み会社の別名は無視
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
from src import sheets_client  # noqa: E402
from src.company_resolver import resolve_company_name  # noqa: E402
from src.database import MonthlyItemsDB  # noqa: E402

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


db = MonthlyItemsDB()
client = TestClient(app)

# ---------------------------------------------------------------------------
section("1. DB: 別名の保存と検証")
gfa = db.get_company("sales", "gf.A㈱")
check("シード行に aliases が空配列で付く（マイグレーション）", gfa is not None and gfa["aliases"] == [])

u = db.update_company(gfa["id"], aliases=["CLANE DESIGN CO.,LTD", " CLANE ", "clane design co.,ltd", ""])
check("空・重複（正規化後）を除いて保存", u["aliases"] == ["CLANE DESIGN CO.,LTD", "CLANE"], str(u["aliases"]))

try:
    db.update_company(db.get_company("sales", "㈱SIM")["id"], aliases=["CLANE"])
    check("他社の別名と同じ別名は拒否", False)
except ValueError:
    check("他社の別名と同じ別名は拒否", True)
try:
    db.update_company(db.get_company("sales", "㈱SIM")["id"], aliases=["株式会社ジュン"])
    check("他社の正式名と同じ別名は拒否", False)
except ValueError:
    check("他社の正式名と同じ別名は拒否", True)

# ---------------------------------------------------------------------------
section("2. 照合: 別名 → 正式名")
check("完全一致", sheets_client.get_canonical_company_name("CLANE DESIGN CO.,LTD") == "gf.A㈱")
check("末尾ピリオド/空白ゆれ", sheets_client.get_canonical_company_name("CLANE DESIGN CO., LTD.") == "gf.A㈱")
check("短い別名 (CLANE)", sheets_client.get_canonical_company_name("CLANE") == "gf.A㈱")
check("同一会社の複数別名に当たっても曖昧扱いしない", sheets_client.get_canonical_company_name("CLANE DESIGN") == "gf.A㈱")
check("別名に無関係な名前は従来どおり", sheets_client.get_canonical_company_name("㈱ジュン") == "㈱ジュン")
check("別名にも正式名にも無ければ None", sheets_client.get_canonical_company_name("存在しない商事") is None)

# 別名の方が正式名より優先される（別名と同名の正式名が他社に有効であれば登録時に弾かれるため、
# 無効化済みの正式名と別名が重なるケースを確認）
sim = db.get_company("sales", "㈱SIM")
db.deactivate_company(sim["id"])
db.update_company(gfa["id"], aliases=["CLANE DESIGN CO.,LTD", "CLANE", "SIM"])
check("無効化済み会社の正式名と同じ別名は登録できる", "SIM" in db.get_company_by_id(gfa["id"])["aliases"])
check("その表記は別名の会社に解決される", sheets_client.get_canonical_company_name("株式会社SIM") == "gf.A㈱")
db.update_company(gfa["id"], aliases=["CLANE DESIGN CO.,LTD", "CLANE"])
db.update_company(sim["id"], is_active=True)

# 2社が同じ表記を部分一致で持つと曖昧 → None
jun = db.get_company("sales", "㈱ジュン")
db.update_company(jun["id"], aliases=["DESIGN STUDIO"])
check("複数の会社に部分一致すれば None（ピッカーへ）", sheets_client.get_canonical_company_name("DESIGN") is None)
db.update_company(jun["id"], aliases=[])

# 仕入側も同じ
kai = db.get_company("purchase", "カイハラ㈱")
db.update_company(kai["id"], aliases=["KAIHARA DENIM"])
check("仕入側の別名も解決される", sheets_client.get_canonical_purchase_company_name("KAIHARA DENIM CO., LTD.") == "カイハラ㈱")

# ---------------------------------------------------------------------------
section("3. 候補スコアリングで別名がマスタ一致になる")
raw = {
    "company_name": "アドバンパートナーズ株式会社",
    "company_candidates": [
        {"name": "アドバンパートナーズ株式会社", "role": "仕入先欄", "confidence": 0.3},
        {"name": "CLANE DESIGN CO.,LTD", "role": "発行元", "confidence": 0.8},
        {"name": "CLANE", "role": "ブランド", "confidence": 0.5},
    ],
}
name, cands = resolve_company_name(raw, domain="sales")
chosen = next(c for c in cands if c.name == name)
check("CLANE DESIGN が選ばれ、マスタ一致先が gf.A㈱", name == "CLANE DESIGN CO.,LTD" and chosen.master_match == "gf.A㈱", f"{name} / {chosen.master_match}")
check("取込ルートと同じ正規化で gf.A㈱ になる", sheets_client.get_canonical_company_name(name, filename="0828CLANE_原田7.pdf") == "gf.A㈱")

# ---------------------------------------------------------------------------
section("4. API")
r = client.get("/api/company-master", params={"domain": "sales"})
row = next(c for c in r.json()["companies"] if c["canonical_name"] == "gf.A㈱")
check("一覧に aliases が出る", row["aliases"] == ["CLANE DESIGN CO.,LTD", "CLANE"], str(row["aliases"]))

r = client.post("/api/company-master/alias", json={"domain": "sales", "canonical_name": "gf.A㈱", "alias": "CLANE DESIGN"})
check("正規化後に既存別名と同じ表記は追加されない（CLANE DESIGN ≡ CLANE DESIGN CO.,LTD）",
      r.status_code == 200 and "CLANE DESIGN" not in r.json()["aliases"], str(r.json().get("aliases")))
r = client.post("/api/company-master/alias", json={"domain": "sales", "canonical_name": "gf.A㈱", "alias": "クラネ"})
check("別名追加エンドポイント 200", r.status_code == 200 and "クラネ" in r.json()["aliases"], r.text[:200])
r = client.post("/api/company-master/alias", json={"domain": "sales", "canonical_name": "gf.A㈱", "alias": "クラネ"})
check("同じ別名の再登録は冪等", r.status_code == 200 and r.json()["aliases"].count("クラネ") == 1)
r = client.post("/api/company-master/alias", json={"domain": "sales", "canonical_name": "gf.A㈱", "alias": "gf.A"})
check("正式名そのものは別名にしない", r.status_code == 200 and "gf.A" not in r.json()["aliases"])
r = client.post("/api/company-master/alias", json={"domain": "sales", "canonical_name": "㈱ジュン", "alias": "CLANE"})
check("他社の別名との衝突は 400", r.status_code == 400, str(r.status_code))
r = client.post("/api/company-master/alias", json={"domain": "sales", "canonical_name": "存在しない", "alias": "X"})
check("会社が無ければ 404", r.status_code == 404, str(r.status_code))

r = client.post("/api/company-master", json={
    "domain": "sales", "canonical_name": "テスト別名商事㈱", "aliases": ["TEST ALIAS TRADING", "TAT"],
})
check("追加時に別名を渡せる", r.status_code == 200 and r.json()["aliases"] == ["TEST ALIAS TRADING", "TAT"], r.text[:200])
new_id = r.json()["id"]
r = client.patch(f"/api/company-master/{new_id}", json={"address": "住所だけ"})
check("他項目の更新で別名は保持", r.json()["aliases"] == ["TEST ALIAS TRADING", "TAT"])
r = client.patch(f"/api/company-master/{new_id}", json={"aliases": []})
check("[] で全削除", r.json()["aliases"] == [])
r = client.patch(f"/api/company-master/{new_id}", json={"aliases": ["CLANE"]})
check("PATCH でも衝突は 400", r.status_code == 400, str(r.status_code))

# 無効化した会社の別名は照合に使われない
db.update_company(new_id, aliases=["ZOMBIE ALIAS"])
client.delete(f"/api/company-master/{new_id}")
check("無効化済み会社の別名は無視", sheets_client.get_canonical_company_name("ZOMBIE ALIAS") is None)

print(f"\n結果: PASS={PASS} FAIL={FAIL}")
sys.exit(1 if FAIL else 0)
