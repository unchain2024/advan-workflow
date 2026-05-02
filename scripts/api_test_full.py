"""本番API + DB を使った全73ファイル E2Eテスト

backend-api を起動した状態で、本番のFastAPIエンドポイント /api/process-pdf と
/api/save-billing を順番に叩いて、73ファイルの完全なフローをテストする。

テスト内容:
  Phase 1 (API レベル): /process-pdf レスポンスを ground truth CSV と突合
  Phase 2 (DB レベル):  保存後の SQLite DB を ground truth CSV と突合

使い方:
    # 1. 別ターミナルで backend-api を起動
    cd backend-api && ../venv/bin/python -m uvicorn main:app --reload --port 8000

    # 2. テスト実行 (新規 / DBクリーンせず)
    venv/bin/python -m scripts.api_test_full

    # クリーンスタート (テスト前に2026年2月の既存DBレコードを削除)
    venv/bin/python -m scripts.api_test_full --clean

    # 一部だけ
    venv/bin/python -m scripts.api_test_full --files 0212インス・佐藤1枚（返品）.pdf

    # APIフェーズをスキップしてDB整合性検証のみ
    venv/bin/python -m scripts.api_test_full --verify-db-only

    # 並列度
    venv/bin/python -m scripts.api_test_full --parallel 4
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sqlite3
import sys
import time
import traceback
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass, field
from pathlib import Path

import requests

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.database import MonthlyItemsDB
from src.config import DATABASE_PATH

SOURCE_DIR = Path("/home/ebi/Downloads/2月DONE")
GROUND_TRUTH_FILES_CSV = PROJECT_ROOT / "reports" / "ground_truth" / "files.csv"
GROUND_TRUTH_LINES_CSV = PROJECT_ROOT / "reports" / "ground_truth" / "lines.csv"
DEFAULT_OUTPUT_JSON = PROJECT_ROOT / "reports" / "api_test_full_result.json"
DEFAULT_OUTPUT_MD = PROJECT_ROOT / "reports" / "api_test_full_result.md"

DEFAULT_API_BASE = "http://localhost:8000/api"
DEFAULT_TARGET_YEAR_MONTH = "2026年2月"  # DB保存先

SALES_PERSONS = ["佐藤", "岡部", "一和多", "星野", "原田", "草島"]


def extract_sales_person(filename: str) -> str:
    for sp in SALES_PERSONS:
        if sp in filename:
            return sp
    return ""


def _parse_int(s: str) -> int:
    return int(str(s).replace(",", "").strip() or 0)


def load_ground_truth_files(csv_path: Path) -> dict[str, dict]:
    truth: dict[str, dict] = {}
    with csv_path.open("r", encoding="utf-8") as f:
        for row in csv.DictReader(f):
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


@dataclass
class APITestResult:
    filename: str
    file_path: str
    target_year_month: str

    # ground truth
    truth_slip: str = ""
    truth_company: str = ""
    truth_items_count: int = 0
    truth_quantity_sum: int = 0
    truth_subtotal: int = 0
    truth_is_return: bool = False

    # /process-pdf 結果
    process_pdf_status: str = ""  # "OK" / "FAIL" / "ERROR"
    process_pdf_error: str = ""
    extracted_company: str = ""
    extracted_slip: str = ""
    extracted_items_count: int = 0
    extracted_quantity_sum: int = 0
    extracted_items_sum: int = 0
    extracted_subtotal: int = 0
    extracted_total: int = 0
    extracted_items: list[dict] = field(default_factory=list)
    response_year_month: str = ""

    # /save-billing 結果
    save_billing_status: str = ""  # "OK" / "FAIL" / "SKIPPED"
    save_billing_error: str = ""
    saved_count: int = 0

    # 比較結果
    match_pass: bool = False  # ground truth と一致したか
    diff_items: int = 0
    diff_quantity: int = 0
    diff_amount: int = 0


def _is_quota_error(e: Exception) -> bool:
    """Google Sheets の 429 quota エラーか判定"""
    if isinstance(e, requests.exceptions.HTTPError):
        body = (e.response.text or "")[:500].lower()
        if e.response.status_code in (429, 500) and (
            "quota exceeded" in body or "429" in body or "rate limit" in body
        ):
            return True
    return False


def _post_with_retry(
    method: str,
    url: str,
    *,
    files=None,
    data=None,
    json_payload=None,
    timeout: int = 180,
    max_retries: int = 5,
) -> dict:
    """POST に retry on 429/quota を付加。Sheets per-minute quota は60秒待てばリセットされる"""
    backoffs = [30, 60, 60, 90, 120]
    last_err = None
    for attempt in range(max_retries + 1):
        try:
            if method.upper() == "POST":
                resp = requests.post(
                    url, files=files, data=data, json=json_payload, timeout=timeout
                )
            else:
                resp = requests.get(url, params=data, timeout=timeout)
            resp.raise_for_status()
            return resp.json()
        except requests.exceptions.HTTPError as e:
            last_err = e
            if _is_quota_error(e) and attempt < max_retries:
                delay = backoffs[min(attempt, len(backoffs) - 1)]
                print(f"    🕒 429/quota → {delay}s 待機して再試行")
                time.sleep(delay)
                continue
            raise
    raise last_err  # type: ignore


def call_process_pdf(
    api_base: str,
    pdf_path: Path,
    target_year: int,
    target_month: int,
    sales_person: str,
    timeout: int = 180,
    max_retries: int = 5,
) -> dict:
    """retry の度にファイルを open し直す（fp の EOF 問題回避）"""
    url = api_base.rstrip("/") + "/process-pdf"
    backoffs = [30, 60, 60, 90, 120]
    data = {
        "sales_person": sales_person,
        "year": str(target_year),
        "month": str(target_month),
    }
    last_err = None
    for attempt in range(max_retries + 1):
        try:
            with pdf_path.open("rb") as fp:
                files = {"file": (pdf_path.name, fp, "application/pdf")}
                resp = requests.post(
                    url, files=files, data=data, timeout=timeout
                )
            resp.raise_for_status()
            return resp.json()
        except requests.exceptions.HTTPError as e:
            last_err = e
            if _is_quota_error(e) and attempt < max_retries:
                delay = backoffs[min(attempt, len(backoffs) - 1)]
                print(f"    🕒 429/quota → {delay}s 待機して再試行")
                time.sleep(delay)
                continue
            raise
    raise last_err  # type: ignore


def call_save_billing(
    api_base: str,
    company_name: str,
    year_month: str,
    delivery_note: dict,
    previous_billing: dict,
    sales_person: str,
    timeout: int = 180,  # 大型伝票でも余裕を持たせる
) -> dict:
    url = api_base.rstrip("/") + "/save-billing"
    payload = {
        "company_name": company_name,
        "year_month": year_month,
        "delivery_notes": [delivery_note],
        "previous_billing": {
            "previous_amount": previous_billing.get("previous_amount", 0),
            "payment_received": previous_billing.get("payment_received", 0),
            "carried_over": previous_billing.get("carried_over", 0),
        },
        "sales_person": sales_person,
        "request_id": str(uuid.uuid4()),
        "force_overwrite": True,
    }
    return _post_with_retry(
        "POST", url, json_payload=payload, timeout=timeout
    )


def clean_db_for_year_month(year_month: str) -> int:
    """指定年月のDBレコードを削除する。ground truth と独立にFKカスケードで安全に削除。"""
    deleted = 0
    with sqlite3.connect(str(DATABASE_PATH)) as conn:
        cur = conn.cursor()
        cur.execute("PRAGMA foreign_keys = ON")
        cur.execute(
            "SELECT id FROM monthly_invoices WHERE year_month = ?", (year_month,)
        )
        invoice_ids = [row[0] for row in cur.fetchall()]
        if not invoice_ids:
            return 0
        # delivery_items → delivery_notes → monthly_invoices の順で削除
        for inv_id in invoice_ids:
            cur.execute(
                "DELETE FROM delivery_items WHERE delivery_note_id IN "
                "(SELECT id FROM delivery_notes WHERE monthly_invoice_id = ?)",
                (inv_id,),
            )
            cur.execute(
                "DELETE FROM delivery_notes WHERE monthly_invoice_id = ?", (inv_id,)
            )
        cur.execute(
            "DELETE FROM monthly_invoices WHERE year_month = ?", (year_month,)
        )
        deleted = cur.rowcount
        conn.commit()
    return deleted


def run_one_pdf(
    api_base: str,
    pdf_path: Path,
    truth: dict,
    target_year: int,
    target_month: int,
    target_year_month: str,
) -> APITestResult:
    fname = pdf_path.name
    res = APITestResult(
        filename=fname,
        file_path=str(pdf_path),
        target_year_month=target_year_month,
        truth_slip=truth.get("slip_number", ""),
        truth_company=truth.get("company", ""),
        truth_items_count=truth.get("items_count", 0),
        truth_quantity_sum=truth.get("quantity_sum", 0),
        truth_subtotal=truth.get("subtotal", 0),
        truth_is_return=truth.get("is_return", False),
    )
    sales_person = extract_sales_person(fname)

    # Phase 1: /process-pdf
    try:
        resp = call_process_pdf(
            api_base, pdf_path, target_year, target_month, sales_person
        )
    except requests.exceptions.HTTPError as e:
        res.process_pdf_status = "ERROR"
        res.process_pdf_error = (
            f"HTTP {e.response.status_code}: {e.response.text[:300]}"
        )
        return res
    except Exception as e:
        res.process_pdf_status = "ERROR"
        res.process_pdf_error = f"{type(e).__name__}: {e}"
        return res

    dn = resp.get("delivery_note") or {}
    items = dn.get("items") or []
    res.extracted_company = dn.get("company_name") or ""
    res.extracted_slip = dn.get("slip_number") or ""
    res.extracted_items_count = len(items)
    res.extracted_quantity_sum = sum(int(i.get("quantity", 0) or 0) for i in items)
    res.extracted_items_sum = sum(int(i.get("amount", 0) or 0) for i in items)
    res.extracted_subtotal = int(dn.get("subtotal", 0) or 0)
    res.extracted_total = int(dn.get("total", 0) or 0)
    res.extracted_items = items
    res.response_year_month = resp.get("year_month") or ""

    # ground truth との比較
    res.diff_items = res.extracted_items_count - res.truth_items_count
    res.diff_quantity = res.extracted_quantity_sum - res.truth_quantity_sum
    res.diff_amount = res.extracted_items_sum - res.truth_subtotal
    res.match_pass = (
        res.diff_items == 0 and res.diff_quantity == 0 and res.diff_amount == 0
    )
    res.process_pdf_status = "OK" if res.match_pass else "FAIL"

    # Phase 2: /save-billing (DB保存)
    company = (resp.get("company_info") or {}).get("company_name") or res.extracted_company
    prev = resp.get("previous_billing") or {}
    try:
        save_resp = call_save_billing(
            api_base,
            company_name=company,
            year_month=target_year_month,
            delivery_note=dn,
            previous_billing=prev,
            sales_person=sales_person,
        )
        if save_resp.get("success"):
            res.save_billing_status = "OK"
            res.saved_count = int(save_resp.get("saved_count", 0))
        else:
            res.save_billing_status = "FAIL"
            res.save_billing_error = (
                save_resp.get("message") or json.dumps(save_resp, ensure_ascii=False)[:200]
            )
    except requests.exceptions.HTTPError as e:
        res.save_billing_status = "ERROR"
        res.save_billing_error = (
            f"HTTP {e.response.status_code}: {e.response.text[:300]}"
        )
    except Exception as e:
        res.save_billing_status = "ERROR"
        res.save_billing_error = f"{type(e).__name__}: {e}"

    return res


def collect_targets(
    truth_files: dict[str, dict], file_filter: list[str] | None
) -> list[Path]:
    if file_filter:
        return [SOURCE_DIR / f for f in file_filter]
    return sorted(SOURCE_DIR / fn for fn in truth_files)


def verify_db_against_truth(
    truth_files: dict[str, dict],
    truth_lines_by_file: dict[str, list[dict]],
    target_year_month: str,
) -> list[dict]:
    """DB ↔ ground truth 整合性検証。

    各 (company × target_year_month) について DB の合計と ground truth を比較する。
    """
    db = MonthlyItemsDB()

    # 会社別に ground truth を集計
    truth_by_company: dict[str, dict] = {}
    for fname, t in truth_files.items():
        c = t["company"]
        d = truth_by_company.setdefault(
            c, {"files": 0, "items": 0, "qty": 0, "subtotal": 0, "filenames": []}
        )
        d["files"] += 1
        d["items"] += t["items_count"]
        d["qty"] += t["quantity_sum"]
        d["subtotal"] += t["subtotal"]
        d["filenames"].append(fname)

    rows = []
    for company in sorted(truth_by_company):
        truth = truth_by_company[company]
        try:
            notes = db.get_monthly_items(company, target_year_month)
        except Exception as e:
            rows.append(
                {
                    "company": company,
                    "year_month": target_year_month,
                    "db_status": f"ERROR: {e}",
                    "truth_files": truth["files"],
                    "truth_items": truth["items"],
                    "truth_qty": truth["qty"],
                    "truth_subtotal": truth["subtotal"],
                }
            )
            continue
        db_files = len(notes)
        db_items = sum(len(n.items) for n in notes)
        db_qty = sum(int(it.quantity) for n in notes for it in n.items)
        db_subtotal = sum(int(it.amount) for n in notes for it in n.items)
        rows.append(
            {
                "company": company,
                "year_month": target_year_month,
                "db_status": "OK",
                "db_files": db_files,
                "db_items": db_items,
                "db_qty": db_qty,
                "db_subtotal": db_subtotal,
                "truth_files": truth["files"],
                "truth_items": truth["items"],
                "truth_qty": truth["qty"],
                "truth_subtotal": truth["subtotal"],
                "diff_files": db_files - truth["files"],
                "diff_items": db_items - truth["items"],
                "diff_qty": db_qty - truth["qty"],
                "diff_subtotal": db_subtotal - truth["subtotal"],
                "match": (
                    db_files == truth["files"]
                    and db_items == truth["items"]
                    and db_qty == truth["qty"]
                    and db_subtotal == truth["subtotal"]
                ),
            }
        )
    return rows


def fmt_diff(d: int) -> str:
    if d == 0:
        return "  0"
    return f"{d:+,}"


def write_report(
    api_results: list[APITestResult],
    db_rows: list[dict],
    output_md: Path,
    output_json: Path,
    target_year_month: str,
) -> None:
    md = ["# API E2E テスト結果\n"]
    md.append(f"- 対象年月: {target_year_month}")
    md.append(f"- 件数: {len(api_results)}")
    md.append("")

    # API summary
    pp_ok = sum(1 for r in api_results if r.process_pdf_status == "OK")
    pp_fail = sum(1 for r in api_results if r.process_pdf_status == "FAIL")
    pp_err = sum(1 for r in api_results if r.process_pdf_status == "ERROR")
    sb_ok = sum(1 for r in api_results if r.save_billing_status == "OK")
    sb_fail = sum(
        1 for r in api_results if r.save_billing_status in ("FAIL", "ERROR")
    )

    md.append("## Phase 1: /api/process-pdf レスポンス vs ground truth")
    md.append("")
    md.append(
        f"- ✅ PASS: **{pp_ok}/{len(api_results)}** "
        f"({pp_ok / len(api_results) * 100:.1f}%)"
    )
    md.append(f"- ❌ FAIL: {pp_fail}")
    md.append(f"- 💥 ERROR: {pp_err}")
    md.append("")

    md.append("## Phase 2: /api/save-billing → DB保存")
    md.append("")
    md.append(f"- 保存成功: {sb_ok}/{len(api_results)}")
    md.append(f"- 保存失敗: {sb_fail}")
    md.append("")

    # 失敗詳細
    if pp_fail or pp_err:
        md.append("## API レスポンスで FAIL/ERROR となったファイル\n")
        for r in api_results:
            if r.process_pdf_status not in ("FAIL", "ERROR"):
                continue
            md.append(f"### `{r.filename}` — {r.process_pdf_status}")
            if r.process_pdf_error:
                md.append(f"\n```\n{r.process_pdf_error[:400]}\n```\n")
                continue
            md.append(
                f"- 件数: 抽出 {r.extracted_items_count} / 真 {r.truth_items_count} "
                f"(diff {fmt_diff(r.diff_items)})"
            )
            md.append(
                f"- 数量: 抽出 {r.extracted_quantity_sum} / 真 {r.truth_quantity_sum} "
                f"(diff {fmt_diff(r.diff_quantity)})"
            )
            md.append(
                f"- 金額: 抽出 ¥{r.extracted_items_sum:,} / 真 ¥{r.truth_subtotal:,} "
                f"(diff ¥{fmt_diff(r.diff_amount)})"
            )
            md.append("")

    # save-billing 失敗
    sb_failed = [r for r in api_results if r.save_billing_status in ("FAIL", "ERROR")]
    if sb_failed:
        md.append("## /save-billing で失敗したファイル\n")
        for r in sb_failed:
            md.append(f"- `{r.filename}`: {r.save_billing_status}")
            if r.save_billing_error:
                md.append(f"  - {r.save_billing_error[:300]}")
        md.append("")

    # DB 整合性
    if db_rows:
        md.append(f"## Phase 3: DB ↔ ground truth 整合性 ({target_year_month})\n")
        md.append(
            "| 取引先 | DBファイル数/真 | DB件数/真 | DB数量/真 | DB金額/真 | 一致 |"
        )
        md.append("|---|---:|---:|---:|---:|:---:|")
        for r in db_rows:
            if r["db_status"] != "OK":
                md.append(f"| {r['company']} | DB ERROR: {r['db_status']} | | | | ❌ |")
                continue
            mark = "✅" if r["match"] else "❌"
            md.append(
                f"| {r['company']} | {r['db_files']}/{r['truth_files']} "
                f"| {r['db_items']}/{r['truth_items']} "
                f"| {r['db_qty']}/{r['truth_qty']} "
                f"| ¥{r['db_subtotal']:,}/¥{r['truth_subtotal']:,} | {mark} |"
            )
        md.append("")
        ok = sum(1 for r in db_rows if r.get("match"))
        md.append(f"DB整合性: **{ok}/{len(db_rows)}** 取引先で一致")
        md.append("")

    # 全行サマリ表
    md.append("## 全件サマリ\n")
    md.append(
        "| ファイル | API状態 | DB状態 | 件数(抽/真) | 数量(抽/真) | 金額(抽/真) |"
    )
    md.append("|---|---|---|---:|---:|---:|")
    for r in sorted(api_results, key=lambda x: x.filename):
        md.append(
            f"| `{r.filename}` | {r.process_pdf_status} | {r.save_billing_status} "
            f"| {r.extracted_items_count}/{r.truth_items_count} "
            f"| {r.extracted_quantity_sum}/{r.truth_quantity_sum} "
            f"| ¥{r.extracted_items_sum:,}/¥{r.truth_subtotal:,} |"
        )

    output_md.parent.mkdir(parents=True, exist_ok=True)
    output_md.write_text("\n".join(md) + "\n", encoding="utf-8")

    # JSON
    output_json.parent.mkdir(parents=True, exist_ok=True)
    with output_json.open("w", encoding="utf-8") as f:
        json.dump(
            {
                "target_year_month": target_year_month,
                "api_results": [asdict(r) for r in api_results],
                "db_verification": db_rows,
            },
            f,
            ensure_ascii=False,
            indent=2,
        )

    print(f"\nレポート: {output_md}")
    print(f"JSON:    {output_json}")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument(
        "--api-base",
        default=DEFAULT_API_BASE,
        help=f"API ベースURL（既定 {DEFAULT_API_BASE}）",
    )
    p.add_argument(
        "--year-month",
        default=DEFAULT_TARGET_YEAR_MONTH,
        help=f"DB 保存先の年月（既定 {DEFAULT_TARGET_YEAR_MONTH}）",
    )
    p.add_argument(
        "--year",
        type=int,
        default=2026,
        help="API /process-pdf の year パラメータ",
    )
    p.add_argument(
        "--month",
        type=int,
        default=2,
        help="API /process-pdf の month パラメータ",
    )
    p.add_argument(
        "--clean",
        action="store_true",
        help="テスト前に対象年月のDBレコードを削除",
    )
    p.add_argument(
        "--verify-db-only",
        action="store_true",
        help="API呼び出しをスキップし、現状のDBと ground truth を突合のみ",
    )
    p.add_argument(
        "--files",
        nargs="*",
        help="特定ファイルのみテスト",
    )
    p.add_argument(
        "--parallel",
        type=int,
        default=1,
        help="並列実行数（DB書込みが直列だが /process-pdf は並列可能。既定1）",
    )
    p.add_argument(
        "--output-json",
        type=Path,
        default=DEFAULT_OUTPUT_JSON,
    )
    p.add_argument(
        "--output-md",
        type=Path,
        default=DEFAULT_OUTPUT_MD,
    )
    return p.parse_args()


def main() -> int:
    args = parse_args()

    truth_files = load_ground_truth_files(GROUND_TRUTH_FILES_CSV)
    truth_lines_by_file: dict[str, list[dict]] = {}
    if GROUND_TRUTH_LINES_CSV.exists():
        with GROUND_TRUTH_LINES_CSV.open("r", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                fn = (row.get("filename") or "").strip()
                if not fn:
                    continue
                truth_lines_by_file.setdefault(fn, []).append(row)

    print(f"ground truth: {len(truth_files)} ファイル")

    api_results: list[APITestResult] = []

    if not args.verify_db_only:
        # API ヘルスチェック
        try:
            health = requests.get(args.api_base.rstrip("/api") + "/health", timeout=5)
            health.raise_for_status()
        except Exception as e:
            print(f"❌ APIに接続できません: {args.api_base} ({e})")
            print(
                "  別ターミナルで backend-api を起動してください:\n"
                "    cd backend-api && ../venv/bin/python -m uvicorn main:app --reload --port 8000"
            )
            return 2

        # DB クリーン (オプション)
        if args.clean:
            print(f"\n🧹 DB cleaning: {args.year_month} のレコードを削除...")
            n = clean_db_for_year_month(args.year_month)
            print(f"   {n} 件の monthly_invoices を削除")

        targets = collect_targets(truth_files, args.files)
        missing = [p for p in targets if not p.exists()]
        if missing:
            for p in missing:
                print(f"❌ ファイル無し: {p}")
            return 2

        print(f"\nテスト対象: {len(targets)} ファイル / 並列度 {args.parallel}")
        started = time.time()

        def worker(p: Path) -> APITestResult:
            t = truth_files.get(p.name) or {}
            return run_one_pdf(
                args.api_base,
                p,
                t,
                args.year,
                args.month,
                args.year_month,
            )

        if args.parallel <= 1:
            for p in targets:
                r = worker(p)
                marker = (
                    "✅" if r.process_pdf_status == "OK" and r.save_billing_status == "OK"
                    else "❌"
                )
                print(
                    f"  {marker} {p.name}: API={r.process_pdf_status} DB={r.save_billing_status}"
                )
                api_results.append(r)
        else:
            with ThreadPoolExecutor(max_workers=args.parallel) as ex:
                futs = {ex.submit(worker, p): p for p in targets}
                for fut in as_completed(futs):
                    r = fut.result()
                    marker = (
                        "✅"
                        if r.process_pdf_status == "OK" and r.save_billing_status == "OK"
                        else "❌"
                    )
                    print(
                        f"  {marker} {r.filename}: API={r.process_pdf_status} DB={r.save_billing_status}"
                    )
                    api_results.append(r)

        api_results.sort(key=lambda r: r.filename)
        print(f"\nPhase 1+2 所要時間: {time.time() - started:.1f}s")

    # Phase 3: DB ↔ ground truth 整合性検証
    print(f"\n📊 Phase 3: DB整合性検証 ({args.year_month})...")
    db_rows = verify_db_against_truth(
        truth_files, truth_lines_by_file, args.year_month
    )

    # 結果出力
    write_report(
        api_results,
        db_rows,
        args.output_md,
        args.output_json,
        args.year_month,
    )

    # 終了コード
    api_fail = sum(
        1 for r in api_results if r.process_pdf_status != "OK"
    )
    db_mismatch = sum(1 for r in db_rows if not r.get("match"))
    return 1 if (api_fail or db_mismatch) else 0


if __name__ == "__main__":
    sys.exit(main())
