"""Gemini 3 Flash Preview vs Claude Sonnet 4.6 のコスト実測

代表PDFを各モデルに1回ずつ送り、入力/出力トークン数とAPIコストを実測。
インス2月分(34ファイル)へのスケール換算も行う。

価格（2026年5月時点、米ドル / 100万トークン）:
  gemini-3-flash-preview : $0.50 input, $3.00 output
  claude-sonnet-4-6      : $3.00 input, $15.00 output

使い方:
    cd /home/ebi/projects/unchain/advan-workflow
    venv/bin/python -m scripts.benchmark_cost
    venv/bin/python -m scripts.benchmark_cost --files 0212インス・佐藤1枚（返品）.pdf 0217インス・佐藤21枚_Part6@.pdf
"""
from __future__ import annotations

import argparse
import base64
import json
import sys
import time
from io import BytesIO
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import anthropic
from google import genai
from google.genai import types
from pdf2image import convert_from_path

from src.config import ANTHROPIC_API_KEY, GEMINI_API_KEY
from src.llm_extractor import EXTRACTION_PROMPT


# 価格表 (USD per 1M tokens)
PRICING = {
    "gemini-3-flash-preview": {"input": 0.50, "output": 3.00},
    "claude-sonnet-4-6": {"input": 3.00, "output": 15.00},
}

SOURCE_DIR = Path("/home/ebi/Downloads/2月DONE")

# 代表選定: 小・中・大 のPDF
DEFAULT_FILES = [
    "0212インス・佐藤1枚（返品）.pdf",  # 2行（小）
    "0213インス・佐藤1枚（2026）.pdf",  # 4行（小）
    "0217インス・佐藤21枚_Part2@.pdf",  # 26行（中）
    "0217インス・佐藤21枚_Part4@.pdf",  # 26行（中）
    "0217インス・佐藤21枚_Part6@.pdf",  # 28行（中）
]


def pdf_to_images(pdf_path: Path):
    return convert_from_path(str(pdf_path), dpi=300)


def measure_gemini(pdf_path: Path) -> dict:
    images = pdf_to_images(pdf_path)
    client = genai.Client(api_key=GEMINI_API_KEY)
    contents = []
    for img in images:
        buf = BytesIO()
        img.save(buf, format="PNG")
        contents.append(
            types.Part.from_bytes(data=buf.getvalue(), mime_type="image/png")
        )
    contents.append(EXTRACTION_PROMPT)

    t0 = time.time()
    resp = client.models.generate_content(
        model="gemini-3-flash-preview",
        contents=contents,
    )
    elapsed = time.time() - t0
    um = resp.usage_metadata
    return {
        "input_tokens": int(getattr(um, "prompt_token_count", 0) or 0),
        "output_tokens": int(getattr(um, "candidates_token_count", 0) or 0),
        "total_tokens": int(getattr(um, "total_token_count", 0) or 0),
        "elapsed_sec": round(elapsed, 2),
        "pages": len(images),
    }


def measure_claude(pdf_path: Path) -> dict:
    images = pdf_to_images(pdf_path)
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    content = []
    for img in images:
        buf = BytesIO()
        img.save(buf, format="PNG")
        b64 = base64.standard_b64encode(buf.getvalue()).decode("ascii")
        content.append(
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": "image/png",
                    "data": b64,
                },
            }
        )
    content.append({"type": "text", "text": EXTRACTION_PROMPT})

    t0 = time.time()
    resp = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=16384,
        messages=[{"role": "user", "content": content}],
    )
    elapsed = time.time() - t0
    return {
        "input_tokens": int(resp.usage.input_tokens),
        "output_tokens": int(resp.usage.output_tokens),
        "total_tokens": int(resp.usage.input_tokens + resp.usage.output_tokens),
        "elapsed_sec": round(elapsed, 2),
        "pages": len(images),
    }


def cost_usd(model: str, input_tok: int, output_tok: int) -> float:
    p = PRICING[model]
    return (input_tok / 1_000_000) * p["input"] + (output_tok / 1_000_000) * p["output"]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--files", nargs="*", default=DEFAULT_FILES)
    args = ap.parse_args()

    targets = [SOURCE_DIR / f for f in args.files]
    missing = [p for p in targets if not p.exists()]
    if missing:
        for p in missing:
            print(f"❌ 見つからない: {p}")
        return 2

    print(f"対象 {len(targets)} ファイル\n")

    rows = []
    for p in targets:
        print(f">>> {p.name}")
        try:
            g = measure_gemini(p)
        except Exception as e:
            print(f"  Gemini エラー: {e}")
            g = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0, "elapsed_sec": 0, "pages": 0}
        try:
            c = measure_claude(p)
        except Exception as e:
            print(f"  Claude エラー: {e}")
            c = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0, "elapsed_sec": 0, "pages": 0}

        g_cost = cost_usd("gemini-3-flash-preview", g["input_tokens"], g["output_tokens"])
        c_cost = cost_usd("claude-sonnet-4-6", c["input_tokens"], c["output_tokens"])
        rows.append(
            {
                "file": p.name,
                "pages": g.get("pages") or c.get("pages"),
                "gemini": {**g, "cost_usd": g_cost},
                "claude": {**c, "cost_usd": c_cost},
                "ratio_claude_over_gemini": (c_cost / g_cost) if g_cost else None,
            }
        )
        print(
            f"  Gemini-3-Flash: in={g['input_tokens']:>6} out={g['output_tokens']:>5} "
            f"cost=${g_cost:.5f} ({g['elapsed_sec']}s)"
        )
        print(
            f"  Claude-Sonnet:  in={c['input_tokens']:>6} out={c['output_tokens']:>5} "
            f"cost=${c_cost:.5f} ({c['elapsed_sec']}s)"
        )
        if g_cost:
            print(f"  比 (Claude/Gemini): {c_cost / g_cost:.2f}x")
        print()

    # 集計
    g_tot_in = sum(r["gemini"]["input_tokens"] for r in rows)
    g_tot_out = sum(r["gemini"]["output_tokens"] for r in rows)
    c_tot_in = sum(r["claude"]["input_tokens"] for r in rows)
    c_tot_out = sum(r["claude"]["output_tokens"] for r in rows)
    g_tot_cost = sum(r["gemini"]["cost_usd"] for r in rows)
    c_tot_cost = sum(r["claude"]["cost_usd"] for r in rows)

    print("=" * 90)
    print(f"合計 ({len(rows)}ファイル)")
    print(f"  Gemini-3-Flash: in={g_tot_in:,} out={g_tot_out:,} cost=${g_tot_cost:.4f}")
    print(f"  Claude-Sonnet:  in={c_tot_in:,} out={c_tot_out:,} cost=${c_tot_cost:.4f}")
    if g_tot_cost:
        print(f"  比 (Claude/Gemini): {c_tot_cost / g_tot_cost:.2f}x")
    print()
    avg_g = g_tot_cost / len(rows)
    avg_c = c_tot_cost / len(rows)
    print(f"平均 1ファイルあたり")
    print(f"  Gemini-3-Flash: ${avg_g:.5f}")
    print(f"  Claude-Sonnet:  ${avg_c:.5f}")
    print()

    print("=" * 90)
    print("月次スケール換算 (例: インス2月分=34ファイル)")
    print(f"  Gemini-3-Flash: ${avg_g * 34:.3f}  (≒ ¥{avg_g * 34 * 155:.1f} @ 1USD=¥155)")
    print(f"  Claude-Sonnet:  ${avg_c * 34:.3f}  (≒ ¥{avg_c * 34 * 155:.1f} @ 1USD=¥155)")
    print()
    print("年間スケール (12ヶ月) - 取引先全体で月100ファイルと仮定")
    yearly_g = avg_g * 100 * 12
    yearly_c = avg_c * 100 * 12
    print(f"  Gemini-3-Flash: ${yearly_g:.2f}/年  (≒ ¥{yearly_g * 155:.0f}/年)")
    print(f"  Claude-Sonnet:  ${yearly_c:.2f}/年  (≒ ¥{yearly_c * 155:.0f}/年)")
    print(f"  差額: ${yearly_c - yearly_g:.2f}/年  (≒ ¥{(yearly_c - yearly_g) * 155:.0f}/年)")

    out = PROJECT_ROOT / "reports" / "cost_benchmark.json"
    with out.open("w", encoding="utf-8") as f:
        json.dump(
            {
                "rows": rows,
                "totals": {
                    "gemini": {"input": g_tot_in, "output": g_tot_out, "cost_usd": g_tot_cost},
                    "claude": {"input": c_tot_in, "output": c_tot_out, "cost_usd": c_tot_cost},
                },
                "averages_per_file": {"gemini_usd": avg_g, "claude_usd": avg_c},
                "pricing_used": PRICING,
            },
            f,
            ensure_ascii=False,
            indent=2,
        )
    print(f"\nJSON保存: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
