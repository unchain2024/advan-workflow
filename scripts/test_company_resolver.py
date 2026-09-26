"""会社名候補解決 / 類似会社警告 / 複数伝票分割 の自己完結テスト（pytest不要・API呼出なし）

実行:
    venv/bin/python -m scripts.test_company_resolver

確認内容:
  1. company_resolver: 自社名（別名義）除外・マスタ一致優先・役割スコア
  2. 類似会社検出（包含 / 郵便番号 / 住所）と無効化済み除外
  3. add_company: 同名(有効)は拒否、無効化済み同名は再有効化、類似は SimilarCompanyError、force で追加
  4. extract_notes_by_slip: ページ→伝票のグルーピング（偽の抽出器で検証）
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

os.environ["DATABASE_PATH"] = tempfile.mktemp(suffix=".db")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.company_resolver import (  # noqa: E402
    is_own_company,
    normalize_for_similarity,
    resolve_company_name,
)
from src.database import MonthlyItemsDB, SimilarCompanyError  # noqa: E402
from src.extractor import extract_notes_by_slip  # noqa: E402
from src.pdf_extractor import DeliveryNote  # noqa: E402

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


# ---------------------------------------------------------------------------
# 1. company_resolver
# ---------------------------------------------------------------------------
section("1. 会社名候補の解決")

check("正規化: CO.,LTD と空白を除去", normalize_for_similarity("CLANE DESIGN CO.,LTD") == "CLANEDESIGN")
check("正規化: '.' は残す", normalize_for_similarity("gf.A㈱") == "GF.A")
check("自社名: アドバンパートナーズ株式会社", is_own_company("アドバンパートナーズ株式会社"))
check("自社名: ADVAN APPAREL CO.,LTD.", is_own_company("ADVAN APPAREL CO.,LTD."))
check("自社名ではない: CLANE DESIGN", not is_own_company("CLANE DESIGN CO.,LTD"))
check("自社名ではない: 短い断片 'A'", not is_own_company("A"))

master = ["gf.A㈱", "CLANE DESIGN CO.,LTD", "（株）アダストリア", "㈱ジュン"]

# CLANE 伝票: 仕入先欄が自社（別名義）、発行元が CLANE
raw = {
    "company_name": "アドバンパートナーズ株式会社",
    "company_candidates": [
        {"name": "アドバンパートナーズ株式会社", "role": "仕入先欄", "confidence": 0.3},
        {"name": "CLANE DESIGN CO.,LTD", "role": "発行元", "confidence": 0.8},
        {"name": "CLANE", "role": "ブランド", "confidence": 0.5},
    ],
}
name, cands = resolve_company_name(raw, master_names=master)
check("自社別名義を除外して発行元を選ぶ", name == "CLANE DESIGN CO.,LTD", name)

# 通常伝票: 宛先が取引先、発行元が自社
raw = {
    "company_name": "株式会社ジュン",
    "company_candidates": [
        {"name": "株式会社ジュン 御中", "role": "宛先", "confidence": 0.9},
        {"name": "アドバンアパレル株式会社", "role": "発行元", "confidence": 0.1},
    ],
}
name, _ = resolve_company_name(raw, master_names=master)
check("宛先の取引先を選ぶ（敬称除去）", name == "株式会社ジュン", name)

# マスタ一致が役割より優先される
raw = {
    "company_candidates": [
        {"name": "どこかの運送会社", "role": "宛先", "confidence": 0.9},
        {"name": "アダストリア", "role": "その他", "confidence": 0.4},
    ],
}
name, _ = resolve_company_name(raw, master_names=master)
check("マスタ一致候補を優先", name == "アダストリア", name)

# 後方互換: company_candidates が無い
name, _ = resolve_company_name({"company_name": "㈱ジュン"}, master_names=master)
check("候補配列なしでも company_name を使う", name == "㈱ジュン", name)

# 全部自社
name, _ = resolve_company_name(
    {"company_name": "アドバンアパレル株式会社", "company_candidates": [{"name": "ADVAN APPAREL", "role": "宛先"}]},
    master_names=master,
)
check("候補が全て自社なら空", name == "", name)


# ---------------------------------------------------------------------------
# 2-3. 類似会社検出 / add_company
# ---------------------------------------------------------------------------
section("2. 類似会社の検出（包含 / 郵便番号 / 住所）")

db = MonthlyItemsDB()  # シード済み（gf.A㈱ を含む）
sim = db.find_similar_companies("sales", "gf.A㈱/CLANE DESIGN CO.,LTD")
check("包含: gf.A㈱ を検出", any(s["canonical_name"] == "gf.A㈱" for s in sim), str([s["canonical_name"] for s in sim]))
sim = db.find_similar_companies("sales", "CLANE DESIGN CO.,LTD")
check("名前が無関係なら検出なし", not sim, str([s["canonical_name"] for s in sim]))

gfa = db.get_company("sales", "gf.A㈱")
db.update_company(gfa["id"], postal_code="102-0093", address="東京都千代田区平河町1-7-20 COI平河町ビル3階")
sim = db.find_similar_companies("sales", "CLANE DESIGN CO.,LTD", postal_code="１０２－００９３")
check("郵便番号一致（全角/ハイフンゆれ）で検出", any("郵便番号" in r for s in sim for r in s["reasons"]), str(sim))
sim = db.find_similar_companies("sales", "CLANE DESIGN CO.,LTD", address="東京都千代田区平河町1-7-20　COI平河町ビル3階")
check("住所一致（空白ゆれ）で検出", any("住所" in r for s in sim for r in s["reasons"]), str(sim))
sim = db.find_similar_companies("sales", "D.O.N")
check("短い名前の誤反応なし (D.O.N)", not any("DONGGUAN" in s["canonical_name"] for s in sim))

section("3. add_company の挙動")

try:
    db.add_company("sales", "gf.A㈱")
    check("同名(有効)は ValueError", False)
except SimilarCompanyError:
    check("同名(有効)は ValueError", False, "SimilarCompanyError が出た")
except ValueError:
    check("同名(有効)は ValueError", True)

try:
    db.add_company("sales", "gf.A㈱/CLANE DESIGN CO.,LTD")
    check("類似は SimilarCompanyError", False)
except SimilarCompanyError as e:
    check("類似は SimilarCompanyError", any(s["canonical_name"] == "gf.A㈱" for s in e.similar))

added = db.add_company("sales", "gf.A㈱/CLANE DESIGN CO.,LTD", force=True)
check("force=True で追加できる", added["is_active"] is True and added["canonical_name"] == "gf.A㈱/CLANE DESIGN CO.,LTD")

db.deactivate_company(added["id"])
sim = db.find_similar_companies("sales", "CLANE DESIGN CO.,LTD/gf.A㈱")
check("無効化済みは類似判定の対象外", not any(s["id"] == added["id"] for s in sim), str([s["canonical_name"] for s in sim]))

re_added = db.add_company("sales", "gf.A㈱/CLANE DESIGN CO.,LTD", address="新住所", force=True)
check("無効化済み同名は再有効化（新規行を作らない）", re_added["id"] == added["id"] and re_added["is_active"] is True and re_added["address"] == "新住所")
db.deactivate_company(added["id"])

# 無効化済みだけが似ていて、有効な類似が無い → 警告なしで追加できる
gfa = db.get_company("sales", "gf.A㈱")
db.deactivate_company(gfa["id"])
try:
    x = db.add_company("sales", "gf.A（新）")
    check("有効な類似が無ければ警告なし", x["is_active"] is True)
    db.deactivate_company(x["id"])
except SimilarCompanyError as e:
    check("有効な類似が無ければ警告なし", False, str(e))
db.update_company(gfa["id"], is_active=True)


# ---------------------------------------------------------------------------
# 4. 複数伝票の分割（偽の抽出器）
# ---------------------------------------------------------------------------
section("4. 複数伝票の分割")


class FakeImpl:
    """ページ画像の代わりに dict を受け取る偽抽出器"""

    def __init__(self):
        self.calls: list[list] = []

    def _extract_raw(self, images, max_retries=6, allow_empty=False):
        self.calls.append(list(images))
        # 1 ページずつのときはそのページの生 JSON を返す
        if len(images) == 1:
            return images[0]
        # 複数ページ（グループ再抽出）: 先頭の伝票番号で items を合算
        merged = dict(images[0])
        merged["items"] = [it for pg in images for it in pg.get("items", [])]
        return merged

    def _postprocess(self, raw, filename=None):
        return DeliveryNote(
            date=raw.get("date", "2026/08/28"),
            company_name=raw.get("company_name", "X"),
            slip_number=str(raw.get("slip_number", "")),
            items=[],
            subtotal=raw.get("subtotal", 0),
            tax=0,
            total=raw.get("subtotal", 0),
        )

    def extract_from_images(self, images, filename=None):
        return self._postprocess(self._extract_raw(images), filename)


def pg(slip, n_items=1, subtotal=100):
    return {"slip_number": slip, "items": [{"x": 1}] * n_items, "subtotal": subtotal}


# 3 伝票（1 ページずつ）
impl = FakeImpl()
res = extract_notes_by_slip(impl, [pg("A-1"), pg("A-2"), pg("A-3")])
check("3 ページ 3 伝票に分割", [dn.slip_number for dn, _ in res] == ["A-1", "A-2", "A-3"], str([dn.slip_number for dn, _ in res]))
check("ページ番号が対応", [p for _, p in res] == [[0], [1], [2]])

# 1 伝票が 2 ページ + 別伝票 1 ページ
impl = FakeImpl()
res = extract_notes_by_slip(impl, [pg("B-1"), pg("", 2), pg("B-2")])
check("続きページ（伝票番号なし）は前の伝票に付く", [p for _, p in res] == [[0, 1], [2]], str([p for _, p in res]))
check("複数ページ伝票はまとめて再抽出される", any(len(c) == 2 for c in impl.calls))

# 全ページ同じ伝票番号 → 1 伝票（PDF 全体を従来どおり 1 回で抽出）
impl = FakeImpl()
res = extract_notes_by_slip(impl, [pg("C-1"), pg("C-1"), pg("C-1")])
check("全ページ同一伝票なら 1 件", len(res) == 1 and res[0][1] == [0, 1, 2])
check("1 伝票のときは全体を 1 回で再抽出", any(len(c) == 3 for c in impl.calls))

# OCR で枝番が付いたケース（"D-1" と "D-1-2"）は同一伝票
impl = FakeImpl()
res = extract_notes_by_slip(impl, [pg("D-1"), pg("D-1-2"), pg("E-9")])
check("枝番付きは同一伝票扱い", [p for _, p in res] == [[0, 1], [2]], str([p for _, p in res]))

# 白紙ページ（内容なし）は直前の伝票に付く
impl = FakeImpl()
res = extract_notes_by_slip(impl, [pg("F-1"), {}, pg("F-2")])
check("白紙ページは前の伝票に付く", [p for _, p in res] == [[0, 1], [2]], str([p for _, p in res]))

# 1 ページ PDF は従来経路
impl = FakeImpl()
res = extract_notes_by_slip(impl, [pg("G-1")])
check("1 ページは 1 回の抽出で完了", len(res) == 1 and len(impl.calls) == 1)


print(f"\n結果: PASS={PASS} FAIL={FAIL}")
sys.exit(1 if FAIL else 0)
