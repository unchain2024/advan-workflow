"""(株)インス 2026年2月 差分テスト + モデル比較

各納品書PDFを指定バックエンドで抽出し、源PDFの「合計」と突合する。
事前に手動で源PDFを読み込んだ ground truth (GROUND_TRUTH) を持っており、
それと比較して数量・金額の差異を検出する。

バックエンド (--backend):
    gemini-2.5-flash      : 現行（軽量・速い）
    gemini-2.5-pro        : Gemini 2.5 Pro
    gemini-3-flash        : Gemini 3 Flash Preview (15%精度向上)
    gemini-3.1-pro        : Gemini 3.1 Pro Preview (高精度)
    claude-haiku-4-5      : Claude Haiku 4.5 (軽量)
    claude-sonnet-4-6     : Claude Sonnet 4.6 (バランス)
    claude-opus-4-7       : Claude Opus 4.7 (最高精度)

使い方:
    cd /home/ebi/projects/unchain/advan-workflow
    venv/bin/python -m scripts.diff_test_insu_2026_02 --known-only
    venv/bin/python -m scripts.diff_test_insu_2026_02 --known-only --backend claude-sonnet-4-6
    venv/bin/python -m scripts.diff_test_insu_2026_02 --known-only --backend gemini-3-flash --parallel 5

    # 全バックエンドで横並び比較（時間かかる）
    venv/bin/python -m scripts.diff_test_insu_2026_02 --known-only --compare-all
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass, field
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.claude_extractor import ClaudeExtractor
from src.llm_extractor import LLMExtractor
from src.pdf_extractor import DeliveryNote


# バックエンド別: (provider, api-model-id)
BACKENDS: dict[str, tuple[str, str]] = {
    "gemini-2.5-flash": ("gemini", "gemini-2.5-flash"),
    "gemini-2.5-pro": ("gemini", "gemini-2.5-pro"),
    "gemini-3-flash": ("gemini", "gemini-3-flash-preview"),
    "gemini-3.1-pro": ("gemini", "gemini-3.1-pro-preview"),
    "claude-haiku-4-5": ("claude", "claude-haiku-4-5"),
    "claude-sonnet-4-6": ("claude", "claude-sonnet-4-6"),
    "claude-opus-4-7": ("claude", "claude-opus-4-7"),
}


def make_extractor(backend: str):
    if backend not in BACKENDS:
        raise ValueError(f"未知のバックエンド: {backend}. 候補: {list(BACKENDS)}")
    provider, model_id = BACKENDS[backend]
    if provider == "gemini":
        return LLMExtractor(model=model_id)
    if provider == "claude":
        return ClaudeExtractor(model=model_id)
    raise ValueError(f"未知のprovider: {provider}")


SOURCE_DIR = Path("/home/ebi/Downloads/2月DONE")
DEFAULT_OUTPUT = PROJECT_ROOT / "reports" / "insu_2026_02_test_result.json"
GROUND_TRUTH_CSV = PROJECT_ROOT / "reports" / "ground_truth" / "files.csv"
GROUND_TRUTH_LINES_CSV = PROJECT_ROOT / "reports" / "ground_truth" / "lines.csv"


def _parse_int(s: str) -> int:
    return int(str(s).replace(",", "").strip() or 0)


def _load_ground_truth_from_csv(csv_path: Path) -> dict[str, dict]:
    """files.csv を読んで GROUND_TRUTH 形式の dict にする。"""
    import csv as _csv

    if not csv_path.exists():
        print(f"⚠️ ground truth CSV が見つからない: {csv_path}")
        return {}
    truth: dict[str, dict] = {}
    with csv_path.open("r", encoding="utf-8") as f:
        for row in _csv.DictReader(f):
            fname = (row.get("filename") or "").strip()
            if not fname:
                continue
            truth[fname] = {
                "slip_number": (row.get("slip_number") or "").strip(),
                "date": (row.get("date") or "").strip(),
                "company": (row.get("company") or "").strip(),
                "items_count": _parse_int(row.get("items_count") or "0"),
                "quantity_sum": _parse_int(row.get("quantity_sum") or "0"),
                "subtotal": _parse_int(row.get("subtotal") or "0"),
                "is_return": str(row.get("is_return", "")).strip().upper() == "TRUE",
                "notes": (row.get("notes") or "").strip(),
            }
    return truth


# CSVから読み込み（ファイルが存在しない場合は空dictになる）
GROUND_TRUTH: dict[str, dict] = _load_ground_truth_from_csv(GROUND_TRUTH_CSV)


@dataclass
class TestResult:
    filename: str
    file_path: str
    backend: str
    truth_known: bool
    extracted_slip_number: str = ""
    extracted_date: str = ""
    extracted_items_count: int = 0
    extracted_quantity_sum: int = 0
    extracted_items_sum: int = 0  # 明細の amount 合計（真の検算値）
    extracted_subtotal: int = 0  # Geminiが書類から読み取った小計フィールド
    extracted_total: int = 0
    subtotal_vs_items_diff: int = 0  # subtotalとitems_sumのズレ（書類側のミスマッチ検出用）
    truth_slip_number: str = ""
    truth_date: str = ""
    truth_items_count: int = 0
    truth_quantity_sum: int = 0
    truth_subtotal: int = 0
    diff_items: int = 0
    diff_quantity: int = 0
    diff_amount: int = 0  # items_sumと真値の差
    pass_status: str = ""  # "PASS" / "FAIL" / "UNKNOWN" / "ERROR"
    error: str = ""
    notes: str = ""
    extracted_items: list[dict] = field(default_factory=list)


def _calc_quantity_sum(dn: DeliveryNote) -> int:
    return sum(int(i.quantity) for i in dn.items)


def _apply_filename_unit_price_override(pdf_path: Path, dn: DeliveryNote) -> DeliveryNote:
    """ファイル名から '@\\d+' を抽出し、全明細の unit_price と amount を補正する。

    アダストリア納品伝票はPDF本文に売価18,000等が書かれているが実際の取引単価は別途
    ファイル名 (例: 0218アダストリア岡部@8600.pdf) で示される下代単価。
    本番側でも同じロジックを使う想定。
    """
    import re as _re

    m = _re.search(r"@(\d+)", pdf_path.name)
    if not m:
        return dn
    if "アダストリア" not in pdf_path.name:
        return dn  # 安全のためアダストリア限定
    new_unit = int(m.group(1))
    for it in dn.items:
        it.unit_price = new_unit
        it.amount = int(it.quantity) * new_unit
    # subtotal も items 合計に揃える
    if dn.items:
        dn.subtotal = sum(int(i.amount) for i in dn.items)
        dn.tax = int(dn.subtotal * 0.1)
        dn.total = dn.subtotal + dn.tax
    return dn


def run_one(pdf_path: Path, backend: str) -> TestResult:
    fname = pdf_path.name
    res = TestResult(
        filename=fname,
        file_path=str(pdf_path),
        backend=backend,
        truth_known=fname in GROUND_TRUTH,
    )
    truth = GROUND_TRUTH.get(fname)
    if truth:
        res.truth_slip_number = truth.get("slip_number", "")
        res.truth_date = truth.get("date", "")
        res.truth_items_count = truth.get("items_count", 0)
        res.truth_quantity_sum = truth.get("quantity_sum", 0)
        res.truth_subtotal = truth.get("subtotal", 0)
        res.notes = truth.get("notes", "")

    try:
        extractor = make_extractor(backend)
        dn = extractor.extract(pdf_path)
        dn = _apply_filename_unit_price_override(pdf_path, dn)
    except Exception as e:
        res.pass_status = "ERROR"
        res.error = f"{type(e).__name__}: {e}\n{traceback.format_exc()}"
        return res

    res.extracted_slip_number = dn.slip_number or ""
    res.extracted_date = dn.date or ""
    res.extracted_items_count = len(dn.items)
    res.extracted_quantity_sum = _calc_quantity_sum(dn)
    res.extracted_items_sum = sum(int(i.amount) for i in dn.items)
    res.extracted_subtotal = dn.subtotal
    res.extracted_total = dn.total
    res.subtotal_vs_items_diff = res.extracted_subtotal - res.extracted_items_sum
    res.extracted_items = [
        {
            "product_code": it.product_code,
            "product_name": it.product_name,
            "quantity": it.quantity,
            "unit_price": it.unit_price,
            "amount": it.amount,
        }
        for it in dn.items
    ]

    if truth:
        res.diff_items = res.extracted_items_count - res.truth_items_count
        res.diff_quantity = res.extracted_quantity_sum - res.truth_quantity_sum
        res.diff_amount = res.extracted_items_sum - res.truth_subtotal
        ok = (
            res.diff_items == 0
            and res.diff_quantity == 0
            and res.diff_amount == 0
        )
        res.pass_status = "PASS" if ok else "FAIL"
    else:
        # ground truthが無い場合: 内部整合性チェック（書類のsubtotal欄=明細合計か）
        # 0件抽出 / sub-itm差≠0 を異常扱い
        if res.extracted_items_count == 0:
            res.pass_status = "FAIL"
            res.notes = "items 0件 (抽出失敗)"
        elif res.subtotal_vs_items_diff != 0:
            res.pass_status = "FAIL"
            res.notes = f"書類subtotal({res.extracted_subtotal:,}) ≠ 明細合計({res.extracted_items_sum:,})"
        else:
            res.pass_status = "PASS_INTERNAL"

    return res


def fmt_diff(d: int) -> str:
    if d == 0:
        return "  0"
    return f"{d:+,}"


def print_table(results: list[TestResult]) -> None:
    print()
    print("=" * 160)
    print(
        f"{'BACKEND':<22} {'STATUS':<8} {'FILE':<48} "
        f"{'件数':>4}/{'真':<4} {'数量':>5}/{'真':<5} "
        f"{'明細計':>11}/{'真値':<11} {'差(円)':>10} {'sub-itm':>9}"
    )
    print("-" * 160)
    for r in results:
        truth_items = str(r.truth_items_count) if r.truth_known else "-"
        truth_qty = str(r.truth_quantity_sum) if r.truth_known else "-"
        truth_sub = f"{r.truth_subtotal:,}" if r.truth_known else "-"
        diff_amt = fmt_diff(r.diff_amount) if r.truth_known else "-"
        sub_diff = fmt_diff(r.subtotal_vs_items_diff)
        print(
            f"{r.backend[:20]:<22} "
            f"{r.pass_status:<8} "
            f"{r.filename[:46]:<48} "
            f"{r.extracted_items_count:>4}/{truth_items:<4} "
            f"{r.extracted_quantity_sum:>5}/{truth_qty:<5} "
            f"{r.extracted_items_sum:>11,}/{truth_sub:<11} "
            f"{diff_amt:>10} {sub_diff:>9}"
        )
    print("=" * 160)

    # バックエンド別の集計
    by_backend: dict[str, dict[str, int]] = {}
    for r in results:
        d = by_backend.setdefault(
            r.backend,
            {"PASS": 0, "PASS_INTERNAL": 0, "FAIL": 0, "ERROR": 0, "UNKNOWN": 0},
        )
        d[r.pass_status] = d.get(r.pass_status, 0) + 1
    print("\n■ バックエンド別 サマリ")
    print(
        f"{'BACKEND':<22} {'PASS':>5} {'P_INT':>6} {'FAIL':>5} {'ERROR':>5} {'UNK':>5}   PASS率(全)"
    )
    for bk, d in by_backend.items():
        total = sum(d.values())
        ok = d["PASS"] + d.get("PASS_INTERNAL", 0)
        rate = (ok / total * 100) if total else 0.0
        print(
            f"{bk:<22} {d['PASS']:>5} {d.get('PASS_INTERNAL', 0):>6} "
            f"{d['FAIL']:>5} {d['ERROR']:>5} {d.get('UNKNOWN', 0):>5}   {rate:.1f}%"
        )

    # 取引先別の集計（複数バックエンドある場合は最初のbackendのみ）
    if len(by_backend) == 1:
        bk_only = list(by_backend)[0]
        by_company: dict[str, dict[str, int]] = {}
        for r in results:
            company = detect_company(r.filename)
            d = by_company.setdefault(
                company,
                {"PASS": 0, "PASS_INTERNAL": 0, "FAIL": 0, "ERROR": 0, "UNKNOWN": 0},
            )
            d[r.pass_status] = d.get(r.pass_status, 0) + 1
        print(f"\n■ 取引先別 サマリ ({bk_only})")
        print(
            f"{'会社':<18} {'PASS':>5} {'P_INT':>6} {'FAIL':>5} {'ERROR':>5} {'UNK':>5}   PASS率"
        )
        for cn in sorted(by_company):
            d = by_company[cn]
            total = sum(d.values())
            ok = d["PASS"] + d.get("PASS_INTERNAL", 0)
            rate = (ok / total * 100) if total else 0.0
            print(
                f"{cn:<18} {d['PASS']:>5} {d.get('PASS_INTERNAL', 0):>6} "
                f"{d['FAIL']:>5} {d['ERROR']:>5} {d.get('UNKNOWN', 0):>5}   {rate:.1f}%"
            )

    print(
        "\n  ※ 明細計 = 明細行amount合計 / sub-itm = 書類のsubtotal - 明細計"
    )
    print(
        "  ※ PASS = ground truth と完全一致 / P_INT = 内部整合性OK(書類subtotal=明細計) / FAIL = 不一致や0件"
    )

    fails = [r for r in results if r.pass_status == "FAIL"]
    errors = [r for r in results if r.pass_status == "ERROR"]
    passes = [r for r in results if r.pass_status == "PASS"]
    unknowns = [r for r in results if r.pass_status == "UNKNOWN"]
    print(
        f"\nPASS={len(passes)}  FAIL={len(fails)}  ERROR={len(errors)}  UNKNOWN={len(unknowns)}  total={len(results)}"
    )
    if fails:
        print("\n*** FAILED FILES ***")
        for r in fails:
            print(f"  {r.file_path}")
            print(
                f"    items: extracted={r.extracted_items_count} truth={r.truth_items_count} (diff={fmt_diff(r.diff_items)})"
            )
            print(
                f"    qty:   extracted={r.extracted_quantity_sum} truth={r.truth_quantity_sum} (diff={fmt_diff(r.diff_quantity)})"
            )
            print(
                f"    items_sum:    {r.extracted_items_sum:,} (truth {r.truth_subtotal:,}, diff {fmt_diff(r.diff_amount)})"
            )
            print(
                f"    doc_subtotal: {r.extracted_subtotal:,}  ← 書類フィールドの読取値"
            )
            print(
                f"    sub-items差:  {fmt_diff(r.subtotal_vs_items_diff)}  (≠0なら書類の小計フィールドの読取りズレ)"
            )
            if r.notes:
                print(f"    note:  {r.notes}")
    if errors:
        print("\n*** ERROR FILES ***")
        for r in errors:
            print(f"  {r.file_path}")
            print(f"    {r.error.splitlines()[0]}")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument(
        "--known-only",
        action="store_true",
        help="GROUND_TRUTH に登録された5件のみテスト",
    )
    p.add_argument(
        "--files",
        nargs="*",
        help="特定のファイル名だけテスト（カレントディレクトリ無関係、SOURCE_DIRの中で探す）",
    )
    p.add_argument(
        "--parallel",
        type=int,
        default=3,
        help="並列実行数（既定3）",
    )
    p.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help=f"JSONレポート出力先（既定 {DEFAULT_OUTPUT}）",
    )
    p.add_argument(
        "--backend",
        choices=list(BACKENDS),
        default="gemini-2.5-flash",
        help=f"バックエンド（既定 gemini-2.5-flash）。候補: {', '.join(BACKENDS)}",
    )
    p.add_argument(
        "--compare-all",
        action="store_true",
        help="全バックエンドで横並び比較（時間とAPIコストが掛かる）",
    )
    p.add_argument(
        "--compare",
        nargs="+",
        help="比較するバックエンドを明示指定（例: --compare gemini-2.5-flash claude-sonnet-4-6）",
    )
    p.add_argument(
        "--repeat",
        type=int,
        default=1,
        help="同じファイルを N 回実行する（OCRの非決定性を確認用）",
    )
    p.add_argument(
        "--all",
        action="store_true",
        help="SOURCE_DIR 内の全PDFをテスト（インスに限らず全取引先）",
    )
    return p.parse_args()


def collect_targets(args: argparse.Namespace) -> list[Path]:
    if args.files:
        return [SOURCE_DIR / f for f in args.files]
    if args.known_only:
        return [SOURCE_DIR / f for f in GROUND_TRUTH]
    if args.all:
        return sorted(SOURCE_DIR.glob("*.pdf"))
    # 既定: インス系PDF全部
    return sorted(p for p in SOURCE_DIR.glob("*.pdf") if "インス" in p.name or "INS" in p.name)


def detect_company(filename: str) -> str:
    """ファイル名から取引先を推測"""
    name = filename
    if "インス" in name or "INS" in name:
        return "インス"
    if "アダストリア" in name:
        return "アダストリア"
    if "バロック" in name:
        return "バロック"
    if "アンフィル" in name:
        return "アンフィル"
    if "ミスターハリウッド" in name:
        return "ミスターハリウッド"
    if "SIM" in name:
        return "SIM"
    if "JUN" in name:
        return "JUN"
    if "高荘" in name:
        return "高荘"
    if "キュー" in name:
        return "キュー"
    return "その他"


def _resolve_backends(args: argparse.Namespace) -> list[str]:
    if args.compare_all:
        return list(BACKENDS)
    if args.compare:
        for b in args.compare:
            if b not in BACKENDS:
                raise SystemExit(f"未知のバックエンド: {b}. 候補: {list(BACKENDS)}")
        return args.compare
    return [args.backend]


def main() -> int:
    args = parse_args()
    targets = collect_targets(args)
    missing = [p for p in targets if not p.exists()]
    if missing:
        print(f"❌ 見つからないファイル:")
        for p in missing:
            print(f"  {p}")
        return 2

    backends = _resolve_backends(args)
    runs = [(p, b, i) for p in targets for b in backends for i in range(args.repeat)]

    print(
        f"対象 {len(targets)} ファイル × {len(backends)} backends × {args.repeat} 回 "
        f"= {len(runs)} 走査 / 並列度 {args.parallel}"
    )
    for p in targets:
        marker = " (truth)" if p.name in GROUND_TRUTH else ""
        print(f"  - {p.name}{marker}")
    print(f"  backends: {backends}")

    results: list[TestResult] = []
    started = time.time()

    def _wrap(item):
        p, backend, idx = item
        return run_one(p, backend)

    if args.parallel <= 1:
        for item in runs:
            p, backend, idx = item
            print(f"\n>>> [{backend}] {p.name} (run #{idx + 1})")
            results.append(_wrap(item))
    else:
        with ThreadPoolExecutor(max_workers=args.parallel) as ex:
            futs = {ex.submit(_wrap, item): item for item in runs}
            for fut in as_completed(futs):
                r = fut.result()
                print(f"  done: [{r.backend}] {r.filename} → {r.pass_status}")
                results.append(r)

    # backend, filename でソート
    results.sort(key=lambda r: (r.backend, r.filename))
    print_table(results)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8") as f:
        json.dump([asdict(r) for r in results], f, ensure_ascii=False, indent=2)
    print(f"\nJSONレポート保存: {args.output}")
    print(f"所要時間: {time.time() - started:.1f}s")

    fail_count = sum(1 for r in results if r.pass_status == "FAIL")
    err_count = sum(1 for r in results if r.pass_status == "ERROR")
    return 1 if (fail_count or err_count) else 0


if __name__ == "__main__":
    sys.exit(main())
