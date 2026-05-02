"""行レベル差分レポート生成

diff_test_insu_2026_02.py が出した JSON 結果と、ground truth lines.csv を突合して、
FAILファイルごとに「どの行が抜けた・重複した・単価違うか」を行単位で diff 表示する。

使い方:
    venv/bin/python -m scripts.line_level_diff \
        --result reports/all73_claude_sonnet_46.json \
        --output reports/line_diff_claude_sonnet.md
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
LINES_CSV = PROJECT_ROOT / "reports" / "ground_truth" / "lines.csv"


def _load_truth_lines(csv_path: Path) -> dict[str, list[dict]]:
    """filename → [行dict, ...] のマップ"""
    by_file: dict[str, list[dict]] = {}
    with csv_path.open("r", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            fname = (row.get("filename") or "").strip()
            if not fname:
                continue
            by_file.setdefault(fname, []).append(
                {
                    "line_num": int(row["line_num"]),
                    "product_code": (row.get("product_code") or "").strip(),
                    "product_name": (row.get("product_name") or "").strip(),
                    "color": (row.get("color") or "").strip(),
                    "size": (row.get("size") or "").strip(),
                    "quantity": int(row["quantity"]),
                    "unit_price": int(row["unit_price"]),
                    "amount": int(row["amount"]),
                }
            )
    return by_file


def _line_key(it: dict) -> tuple:
    """行のマッチング用キー: (qty, unit_price, amount) をベースに緩めにマッチ"""
    return (int(it.get("quantity", 0)), int(it.get("unit_price", 0)), int(it.get("amount", 0)))


def _diff_lines(truth_lines: list[dict], extracted_lines: list[dict]) -> dict:
    """multiset ベースで行差分を計算"""
    truth_keys = Counter(_line_key(t) for t in truth_lines)
    ext_keys = Counter(_line_key(e) for e in extracted_lines)

    only_in_truth = truth_keys - ext_keys  # 抜け
    only_in_ext = ext_keys - truth_keys  # 余分・重複・置き換わり

    truth_lookup: dict[tuple, list[dict]] = {}
    for t in truth_lines:
        truth_lookup.setdefault(_line_key(t), []).append(t)
    ext_lookup: dict[tuple, list[dict]] = {}
    for e in extracted_lines:
        ext_lookup.setdefault(_line_key(e), []).append(e)

    missing = []
    for key, n in only_in_truth.items():
        for t in (truth_lookup.get(key) or [])[:n]:
            missing.append(t)
    extras = []
    for key, n in only_in_ext.items():
        for e in (ext_lookup.get(key) or [])[:n]:
            extras.append(e)

    return {
        "missing": missing,
        "extras": extras,
        "match_count": (truth_keys & ext_keys).total(),
        "truth_count": len(truth_lines),
        "extracted_count": len(extracted_lines),
    }


def _fmt_truth_line(t: dict) -> str:
    pc = t.get("product_code") or "-"
    pn = t.get("product_name") or "-"
    color = t.get("color") or ""
    size = t.get("size") or ""
    return (
        f"行{t['line_num']:>2}: {pc} / {pn} / {color} / {size} / "
        f"qty={t['quantity']} @{t['unit_price']:,} = ¥{t['amount']:,}"
    )


def _fmt_ext_line(e: dict) -> str:
    pc = e.get("product_code") or "-"
    pn = e.get("product_name") or "-"
    return (
        f"     {pc} / {pn} / "
        f"qty={e.get('quantity', 0)} @{e.get('unit_price', 0):,} = ¥{e.get('amount', 0):,}"
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--result",
        type=Path,
        required=True,
        help="diff_test_insu_2026_02.py が出した JSON",
    )
    ap.add_argument(
        "--output",
        type=Path,
        default=PROJECT_ROOT / "reports" / "line_diff.md",
    )
    ap.add_argument(
        "--lines-csv",
        type=Path,
        default=LINES_CSV,
    )
    ap.add_argument(
        "--include-pass",
        action="store_true",
        help="PASSファイルも詳細を出す（既定はFAIL/ERRORのみ）",
    )
    args = ap.parse_args()

    if not args.result.exists():
        print(f"❌ JSON not found: {args.result}")
        return 2
    if not args.lines_csv.exists():
        print(f"❌ lines.csv not found: {args.lines_csv}")
        return 2

    with args.result.open("r", encoding="utf-8") as f:
        results = json.load(f)
    truth_by_file = _load_truth_lines(args.lines_csv)

    md = ["# 行レベル差分レポート\n"]
    md.append(f"- 結果: `{args.result}`")
    md.append(f"- 真値: `{args.lines_csv}`")
    md.append("")

    total = len(results)
    passes = [r for r in results if r["pass_status"] == "PASS"]
    fails = [r for r in results if r["pass_status"] == "FAIL"]
    errors = [r for r in results if r["pass_status"] == "ERROR"]

    md.append(f"## サマリ\n")
    md.append(f"- 総数: {total}")
    md.append(f"- PASS: {len(passes)}")
    md.append(f"- FAIL: {len(fails)}")
    md.append(f"- ERROR: {len(errors)}")
    md.append("")

    targets = fails + errors
    if args.include_pass:
        targets += passes

    if not targets:
        md.append("\n*差分・エラーは検出されませんでした。* 🎉\n")
    else:
        md.append("\n## ファイル別差分\n")

    for r in targets:
        fname = r["filename"]
        md.append(f"\n### 📄 `{fname}`")
        md.append(f"- backend: {r.get('backend', '-')} / status: **{r['pass_status']}**")
        if r.get("error"):
            md.append(f"\n```\n{r['error'].splitlines()[0]}\n```")
            continue

        md.append(
            f"- 件数: 抽出={r['extracted_items_count']} / 真={r['truth_items_count']} (差 {r['extracted_items_count']-r['truth_items_count']:+})"
        )
        md.append(
            f"- 数量: 抽出={r['extracted_quantity_sum']} / 真={r['truth_quantity_sum']} (差 {r['extracted_quantity_sum']-r['truth_quantity_sum']:+})"
        )
        md.append(
            f"- 金額: 抽出=¥{r['extracted_items_sum']:,} / 真=¥{r['truth_subtotal']:,} (差 ¥{r['diff_amount']:+,})"
        )
        if r.get("notes"):
            md.append(f"- notes: {r['notes']}")

        truth_lines = truth_by_file.get(fname, [])
        extracted_lines = r.get("extracted_items") or []
        if not truth_lines:
            md.append("\n⚠️ ground truth lines が見つかりません")
            continue

        diff = _diff_lines(truth_lines, extracted_lines)

        md.append(
            f"\n- 一致行: {diff['match_count']} / 真={diff['truth_count']} / 抽出={diff['extracted_count']}"
        )

        if diff["missing"]:
            md.append(f"\n#### ❌ 抜けた行（{len(diff['missing'])}件）")
            for t in diff["missing"]:
                md.append(f"- {_fmt_truth_line(t)}")

        if diff["extras"]:
            md.append(f"\n#### ⚠️ 余分/重複/誤抽出（{len(diff['extras'])}件）")
            for e in diff["extras"]:
                md.append(f"- {_fmt_ext_line(e)}")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text("\n".join(md) + "\n", encoding="utf-8")
    print(f"レポート出力: {args.output}")
    print(f"PASS={len(passes)} FAIL={len(fails)} ERROR={len(errors)} / total={total}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
