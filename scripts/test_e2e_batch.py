"""納品書PDFの一括E2Eテストスクリプト

UIでPDFを1枚ずつ処理する流れと同等の処理を、指定ディレクトリ内の全PDFに対して
自動実行する。会社名マッチ不一致や金額の整合性チェックで異常が見つかった場合は
対話プロンプトで修正できる。

処理内容（UIの /process-pdf + /save-billing 相当）:
  1. LLMExtractor で PDF から抽出
  2. スプレッドシートの正規会社名にマッチング（マッチしない場合は対話）
  3. 金額の整合性チェック（subtotal+tax=total, items合計=subtotal）異常なら対話
  4. 請求書PDFを output/ に生成（UIと同様）
  5. DB に保存（save_monthly_items_batch）
  6. スプレッドシートへの書き込みは **行わない**

使用方法:
    python -m scripts.test_e2e_batch <PDF_DIR> [--output REPORT.json] [--auto-approve]

例:
    python -m scripts.test_e2e_batch ~/Downloads/2月DONE
    python -m scripts.test_e2e_batch ~/Downloads/2月DONE --auto-approve
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
import time
import traceback
import unicodedata
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

# プロジェクトルートを sys.path に追加
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.database import MonthlyItemsDB
from src.invoice_generator import InvoiceGenerator
from src.llm_extractor import LLMExtractor
from src.pdf_extractor import DeliveryItem, DeliveryNote
from src.sheets_client import GoogleSheetsClient


# --- ANSIカラー ---
class C:
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    RED = "\033[31m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    BLUE = "\033[34m"
    CYAN = "\033[36m"


# ファイル名から担当者を抽出
SALES_PERSONS = ["佐藤", "岡部", "一和多", "星野", "原田"]


def extract_sales_person(filename: str) -> str:
    for sp in SALES_PERSONS:
        if sp in filename:
            return sp
    return ""


@dataclass
class PDFResult:
    filename: str
    status: str  # "ok" | "anomaly_fixed" | "skipped" | "error"
    company_name: str = ""
    canonical_company: str = ""
    company_matched: bool = False
    slip_number: str = ""
    date: str = ""
    year_month: str = ""
    sales_person: str = ""
    subtotal: int = 0
    tax: int = 0
    total: int = 0
    items_count: int = 0
    items_sum: int = 0  # 明細金額の合計
    anomalies: list[str] = field(default_factory=list)
    user_edits: list[str] = field(default_factory=list)  # ユーザー編集の履歴
    error: str = ""
    extracted_raw: dict = field(default_factory=dict)  # 抽出時の元データ
    saved_to_db: bool = False
    invoice_pdf: str = ""


def yn_prompt(question: str, default: str = "n") -> bool:
    suffix = "[Y/n]" if default == "y" else "[y/N]"
    while True:
        ans = input(f"{C.CYAN}{question} {suffix}: {C.RESET}").strip().lower()
        if not ans:
            ans = default
        if ans in ("y", "yes"):
            return True
        if ans in ("n", "no"):
            return False


def choice_prompt(question: str, choices: list[str]) -> str:
    print(f"{C.CYAN}{question}{C.RESET}")
    for i, c in enumerate(choices, 1):
        print(f"  {i}. {c}")
    while True:
        ans = input(f"{C.CYAN}選択 (1-{len(choices)}): {C.RESET}").strip()
        if ans.isdigit() and 1 <= int(ans) <= len(choices):
            return choices[int(ans) - 1]
        print(f"{C.YELLOW}無効な選択です{C.RESET}")


def edit_int(label: str, current: int) -> int:
    raw = input(
        f"{C.CYAN}{label} (現在 {current:,}, Enter で維持): {C.RESET}"
    ).strip().replace(",", "")
    if not raw:
        return current
    try:
        return int(raw)
    except ValueError:
        print(f"{C.YELLOW}数値として解釈できません。現在値を維持します。{C.RESET}")
        return current


def edit_str(label: str, current: str) -> str:
    raw = input(f"{C.CYAN}{label} (現在 '{current}', Enter で維持): {C.RESET}")
    return raw if raw.strip() else current


def year_month_from_date(date_str: str) -> str:
    """YYYY/MM/DD → YYYY年M月"""
    m = re.match(r"(\d{4})/(\d{1,2})", date_str or "")
    if not m:
        return ""
    return f"{int(m.group(1))}年{int(m.group(2))}月"


def extract_filename_keywords(filename: str) -> list[str]:
    """pdf.py の _extract_filename_keywords と同等"""
    name = re.sub(r"\.\w+$", "", filename)
    name = re.sub(r"^\d{4,8}", "", name)
    name = re.sub(r"納品書|請求書|返品伝票|返品|伝票|明細|見積|売上", "", name)
    name = name.replace("_", " ").replace("-", " ").replace("　", " ").strip()
    # 担当者名も除去
    for sp in SALES_PERSONS:
        name = name.replace(sp, " ")
    # Part番号や@なども除去
    name = re.sub(r"Part\d+|@\d+|\d+枚|[（(]\d+[）)]", "", name, flags=re.IGNORECASE)
    keywords = [k.strip() for k in name.split() if len(k.strip()) >= 2]
    return keywords


def score_company_candidate(candidate: str, extracted: str, filename_keywords: list[str]) -> int:
    """pdf.py の _score_company_candidate と同等"""
    score = 0
    cand_n = unicodedata.normalize("NFKC", candidate)
    cand_clean = re.sub(r"[（(]株[）)]|株式会社|有限会社|㈱|合同会社", "", cand_n).strip()
    for kw in filename_keywords:
        kw_n = unicodedata.normalize("NFKC", kw)
        if kw_n in cand_clean or kw_n in cand_n:
            score += 10
    name_clean = re.sub(
        r"CO\.?,?\s*LTD\.?|INC\.?|CORP\.?|LTD\.?|LIMITED",
        "",
        extracted or "",
        flags=re.IGNORECASE,
    ).strip()
    for token in [t for t in name_clean.split() if len(t) >= 2]:
        if unicodedata.normalize("NFKC", token).lower() in cand_clean.lower():
            score += 5
    return score


def check_anomalies(dn: DeliveryNote) -> list[str]:
    issues = []
    items_sum = sum(i.amount for i in dn.items)
    # 返品の場合はマイナスもあり得るので絶対値で緩めにチェック
    if dn.subtotal + dn.tax != dn.total:
        issues.append(
            f"小計({dn.subtotal:,}) + 税({dn.tax:,}) = {dn.subtotal + dn.tax:,} "
            f"≠ 合計({dn.total:,})"
        )
    if dn.items and items_sum != dn.subtotal:
        issues.append(
            f"明細合計({items_sum:,}) ≠ 小計({dn.subtotal:,}) "
            f"差額={items_sum - dn.subtotal:+,}"
        )
    if not dn.items:
        issues.append("明細が0件です")
    if not dn.date:
        issues.append("日付が抽出できていません")
    if not dn.slip_number:
        issues.append("伝票番号が抽出できていません")
    return issues


def print_delivery_summary(dn: DeliveryNote, filename: str, sales_person: str):
    print(f"\n{C.BOLD}━━━ {filename} ━━━{C.RESET}")
    print(f"  会社名    : {dn.company_name}")
    print(f"  担当者    : {sales_person}")
    print(f"  日付      : {dn.date}")
    print(f"  伝票番号  : {dn.slip_number}")
    print(f"  明細件数  : {len(dn.items)}")
    items_sum = sum(i.amount for i in dn.items)
    print(f"  明細合計  : ¥{items_sum:,}")
    print(f"  小計      : ¥{dn.subtotal:,}")
    print(f"  消費税    : ¥{dn.tax:,}")
    print(f"  合計      : ¥{dn.total:,}")


def _normalize_for_search(s: str) -> str:
    """会社名検索用の正規化: NFKC + 法人格除去 + 空白除去 + 小文字化"""
    n = unicodedata.normalize("NFKC", s or "")
    n = re.sub(r"[（(]株[）)]|株式会社|有限会社|㈱|合同会社|合資会社", "", n)
    n = re.sub(r"\s+", "", n)
    return n.lower()


def _fuzzy_search_candidates(query: str, candidates: list[str]) -> list[str]:
    """正規化してから部分一致で検索"""
    q = _normalize_for_search(query)
    if not q:
        return []
    return [c for c in candidates if q in _normalize_for_search(c)]


def interactive_fix_company(
    dn: DeliveryNote,
    filename: str,
    candidates: list[str],
    result: PDFResult,
) -> bool:
    """会社名マッチ不一致時の対話。True=続行、False=スキップ

    手動入力は不可。必ずシート候補の中から選択させる。
    見つからない場合はスキップのみ。
    """
    print(f"\n{C.YELLOW}⚠ 会社名がシートにマッチしませんでした: '{dn.company_name}'{C.RESET}")

    if not candidates:
        print(f"{C.RED}シート会社名リストが空です。スキップします。{C.RESET}")
        return False

    # スコアで並べ替えた候補を優先表示
    keywords = extract_filename_keywords(filename)
    scored = sorted(
        [(c, score_company_candidate(c, dn.company_name, keywords)) for c in candidates],
        key=lambda x: x[1],
        reverse=True,
    )
    suggested = [c for c, s in scored if s > 0][:5]

    while True:
        options: list[str] = []
        if suggested:
            options.extend(suggested)
        options.append("[シート会社名を検索]")
        options.append("[この1件をスキップ]")

        chosen = choice_prompt("どの会社名を使いますか？", options)

        if chosen == "[この1件をスキップ]":
            return False

        if chosen == "[シート会社名を検索]":
            query = input(f"{C.CYAN}検索キーワード (法人格・空白は無視): {C.RESET}").strip()
            if not query:
                print(f"{C.YELLOW}キーワードが空です。もう一度選び直してください。{C.RESET}")
                continue
            matched = _fuzzy_search_candidates(query, candidates)
            if not matched:
                print(
                    f"{C.YELLOW}'{query}' にマッチする会社名がシートにありません。"
                    f"別のキーワードで再検索するかスキップしてください。{C.RESET}"
                )
                continue
            sub_options = matched + ["[別のキーワードで再検索]", "[この1件をスキップ]"]
            sub = choice_prompt("候補から選択:", sub_options)
            if sub == "[別のキーワードで再検索]":
                continue
            if sub == "[この1件をスキップ]":
                return False
            chosen = sub

        # ここまで来たらシート候補のどれかが chosen に入っている
        result.user_edits.append(f"company_name: '{dn.company_name}' → '{chosen}'")
        dn.company_name = chosen
        return True


def print_items_table(items: list[DeliveryItem]):
    if not items:
        print(f"  {C.DIM}(明細なし){C.RESET}")
        return
    print(f"  {'#':>3}  {'商品コード':<24} {'品名':<30} {'数':>4} {'単価':>10} {'金額':>12}")
    for i, it in enumerate(items, 1):
        pname = (it.product_name or "")[:28]
        pcode = (it.product_code or "")[:22]
        print(
            f"  {i:>3}  {pcode:<24} {pname:<30} {it.quantity:>4} "
            f"¥{it.unit_price:>9,} ¥{it.amount:>11,}"
        )
    total = sum(i.amount for i in items)
    print(f"  {C.DIM}{'合計:':>74} ¥{total:>11,}{C.RESET}")


def interactive_edit_items(dn: DeliveryNote, result: PDFResult):
    """明細の追加・削除・編集を行うサブメニュー"""
    while True:
        print(f"\n{C.BOLD}[明細編集]{C.RESET}  小計={dn.subtotal:,}  明細合計={sum(i.amount for i in dn.items):,}")
        print_items_table(dn.items)
        diff = sum(i.amount for i in dn.items) - dn.subtotal
        if diff != 0:
            print(f"  {C.YELLOW}差額: {diff:+,}（+なら明細過剰、-なら明細不足）{C.RESET}")

        action = choice_prompt(
            "アクション:",
            ["行を追加", "行を削除", "既存行を編集", "終了（保存せず明細メニューを抜ける）"],
        )
        if action == "終了（保存せず明細メニューを抜ける）":
            return
        if action == "行を追加":
            template_idx = None
            if dn.items:
                raw = input(
                    f"{C.CYAN}テンプレにする行番号 (Enterで空行): {C.RESET}"
                ).strip()
                if raw.isdigit() and 1 <= int(raw) <= len(dn.items):
                    template_idx = int(raw) - 1
            if template_idx is not None:
                t = dn.items[template_idx]
                new_item = DeliveryItem(
                    slip_number=t.slip_number,
                    product_code=t.product_code,
                    product_name=t.product_name,
                    quantity=t.quantity,
                    unit_price=t.unit_price,
                    amount=t.amount,
                )
            else:
                new_item = DeliveryItem(
                    slip_number=dn.slip_number,
                    product_code="",
                    product_name="",
                    quantity=1,
                    unit_price=0,
                    amount=0,
                )
            new_item.product_code = edit_str("  商品コード", new_item.product_code)
            new_item.product_name = edit_str("  品名", new_item.product_name)
            new_item.quantity = edit_int("  数量", new_item.quantity)
            new_item.unit_price = edit_int("  単価", new_item.unit_price)
            default_amount = new_item.quantity * new_item.unit_price if new_item.amount == 0 else new_item.amount
            new_item.amount = edit_int("  金額", default_amount)
            dn.items.append(new_item)
            result.user_edits.append(
                f"item added: {new_item.product_code} x{new_item.quantity} ¥{new_item.amount:,}"
            )
            print(f"{C.GREEN}  追加しました{C.RESET}")
        elif action == "行を削除":
            raw = input(f"{C.CYAN}削除する行番号: {C.RESET}").strip()
            if not raw.isdigit() or not (1 <= int(raw) <= len(dn.items)):
                print(f"{C.YELLOW}無効な番号{C.RESET}")
                continue
            idx = int(raw) - 1
            it = dn.items[idx]
            if yn_prompt(
                f"削除: [{idx + 1}] {it.product_name} ¥{it.amount:,}  本当に？",
                default="y",
            ):
                dn.items.pop(idx)
                result.user_edits.append(
                    f"item removed: {it.product_code} ¥{it.amount:,}"
                )
                print(f"{C.GREEN}  削除しました{C.RESET}")
        elif action == "既存行を編集":
            raw = input(f"{C.CYAN}編集する行番号: {C.RESET}").strip()
            if not raw.isdigit() or not (1 <= int(raw) <= len(dn.items)):
                print(f"{C.YELLOW}無効な番号{C.RESET}")
                continue
            idx = int(raw) - 1
            it = dn.items[idx]
            before = f"{it.product_code} x{it.quantity} @¥{it.unit_price:,} =¥{it.amount:,}"
            it.product_code = edit_str("  商品コード", it.product_code)
            it.product_name = edit_str("  品名", it.product_name)
            it.quantity = edit_int("  数量", it.quantity)
            it.unit_price = edit_int("  単価", it.unit_price)
            it.amount = edit_int("  金額", it.amount)
            after = f"{it.product_code} x{it.quantity} @¥{it.unit_price:,} =¥{it.amount:,}"
            result.user_edits.append(f"item edited [{idx + 1}]: {before} → {after}")


def _categorize_issues(issues: list[str]) -> tuple[list[str], list[str]]:
    """issues を「金額の不整合」と「メタデータ欠落」に分類"""
    amount_issues = []
    meta_issues = []
    for issue in issues:
        if (
            "小計" in issue or "明細合計" in issue or "明細が0件" in issue
        ):
            amount_issues.append(issue)
        else:
            meta_issues.append(issue)
    return amount_issues, meta_issues


def interactive_fix_amounts(dn: DeliveryNote, issues: list[str], result: PDFResult) -> bool:
    """異常・欠落時の対話。True=続行、False=スキップ"""
    amount_issues, meta_issues = _categorize_issues(issues)
    header_lines = []
    if amount_issues:
        header_lines.append(f"{C.YELLOW}⚠ 金額の不整合:{C.RESET}")
        header_lines.extend(f"    - {x}" for x in amount_issues)
    if meta_issues:
        header_lines.append(f"{C.YELLOW}⚠ 欠落している項目:{C.RESET}")
        header_lines.extend(f"    - {x}" for x in meta_issues)
    print("\n" + "\n".join(header_lines))

    while True:
        action = choice_prompt(
            "どうしますか？",
            [
                "このまま保存",
                "header金額 (小計/税/合計) を編集",
                "明細行を追加・削除・編集",
                "日付・伝票番号を編集",
                "現在の状態を再表示",
                "この1件をスキップ",
            ],
        )
        if action == "この1件をスキップ":
            return False
        if action == "このまま保存":
            return True
        if action == "現在の状態を再表示":
            print_delivery_summary(dn, result.filename, result.sales_person)
            print_items_table(dn.items)
            continue
        if action == "header金額 (小計/税/合計) を編集":
            print(f"\n{C.DIM}(Enter で現在値を維持){C.RESET}")
            new_subtotal = edit_int("小計", dn.subtotal)
            new_tax = edit_int("消費税", dn.tax)
            new_total = edit_int("合計", dn.total)
            if new_subtotal != dn.subtotal:
                result.user_edits.append(f"subtotal: {dn.subtotal} → {new_subtotal}")
                dn.subtotal = new_subtotal
            if new_tax != dn.tax:
                result.user_edits.append(f"tax: {dn.tax} → {new_tax}")
                dn.tax = new_tax
            if new_total != dn.total:
                result.user_edits.append(f"total: {dn.total} → {new_total}")
                dn.total = new_total
        elif action == "明細行を追加・削除・編集":
            interactive_edit_items(dn, result)
        elif action == "日付・伝票番号を編集":
            print(f"\n{C.DIM}(Enter で現在値を維持。日付は YYYY/MM/DD 形式){C.RESET}")
            new_date = edit_str("日付", dn.date)
            new_slip = edit_str("伝票番号", dn.slip_number)
            if new_date != dn.date:
                if new_date and not re.match(r"^\d{4}/\d{2}/\d{2}$", new_date):
                    print(f"{C.YELLOW}日付形式が不正です (YYYY/MM/DD)。変更をキャンセル{C.RESET}")
                else:
                    result.user_edits.append(f"date: '{dn.date}' → '{new_date}'")
                    dn.date = new_date
            if new_slip != dn.slip_number:
                result.user_edits.append(
                    f"slip_number: '{dn.slip_number}' → '{new_slip}'"
                )
                dn.slip_number = new_slip

        # 再チェックしてOKなら続行確認
        remaining = check_anomalies(dn)
        if not remaining:
            print(f"\n{C.GREEN}✓ 全ての項目がOKになりました。{C.RESET}")
            if yn_prompt("このまま保存しますか？", default="y"):
                return True
        else:
            amount_r, meta_r = _categorize_issues(remaining)
            print(f"\n{C.YELLOW}残り:{C.RESET}")
            for x in amount_r:
                print(f"    金額: {x}")
            for x in meta_r:
                print(f"    欠落: {x}")


def process_pdf(
    pdf_path: Path,
    extractor: LLMExtractor,
    sheets_client: GoogleSheetsClient,
    invoice_gen: InvoiceGenerator,
    db: MonthlyItemsDB,
    output_dir: Path,
    auto_approve: bool,
) -> PDFResult:
    result = PDFResult(filename=pdf_path.name, status="error")
    sales_person = extract_sales_person(pdf_path.name)
    result.sales_person = sales_person

    try:
        # 1. 抽出
        print(f"\n{C.DIM}── 抽出中: {pdf_path.name} ──{C.RESET}")
        dn = extractor.extract(pdf_path)
        result.extracted_raw = {
            "company_name": dn.company_name,
            "date": dn.date,
            "slip_number": dn.slip_number,
            "subtotal": dn.subtotal,
            "tax": dn.tax,
            "total": dn.total,
            "items_count": len(dn.items),
        }
        # 2. 会社名正規化（空の場合も対話で選ばせる）
        target_year = None
        if dn.date:
            m = re.match(r"(\d{4})", dn.date)
            if m:
                target_year = int(m.group(1))
        result.company_name = dn.company_name or ""
        canonical = None
        if dn.company_name:
            canonical = sheets_client.get_canonical_company_name(
                dn.company_name, year=target_year
            )
        if canonical:
            result.canonical_company = canonical
            result.company_matched = True
            if canonical != dn.company_name:
                result.user_edits.append(
                    f"company normalized: '{dn.company_name}' → '{canonical}'"
                )
            dn.company_name = canonical
        else:
            result.company_matched = False
            # シート会社名一覧取得
            try:
                sheet = sheets_client._get_billing_sheet_by_year(target_year)
                col_a = sheet.col_values(1)
                candidates = [v for v in col_a[2:] if v]
            except Exception:
                candidates = []

            if auto_approve:
                if not dn.company_name:
                    raise ValueError(
                        "会社名を抽出できませんでした（auto-approveのため対話不可）"
                    )
                result.anomalies.append(
                    f"会社名マッチなし（自動承認モードのためそのまま使用）: {dn.company_name}"
                )
            else:
                if not dn.company_name:
                    print(
                        f"\n{C.YELLOW}⚠ 会社名が抽出できませんでした。"
                        f"ファイル名から推測してシートから選んでください: {pdf_path.name}{C.RESET}"
                    )
                    dn.company_name = ""  # 空文字として対話へ
                print_delivery_summary(dn, pdf_path.name, sales_person)
                if not interactive_fix_company(dn, pdf_path.name, candidates, result):
                    result.status = "skipped"
                    return result
                result.canonical_company = dn.company_name
                result.company_matched = True

        # 3. 金額チェック
        anomalies = check_anomalies(dn)
        if anomalies:
            result.anomalies.extend(anomalies)
            if not auto_approve:
                print_delivery_summary(dn, pdf_path.name, sales_person)
                if not interactive_fix_amounts(dn, anomalies, result):
                    result.status = "skipped"
                    return result

        # 4. 会社情報・前月請求情報（UIと同様のread）
        company_info = sheets_client.get_company_info(dn.company_name)
        year_month_dash = ""
        if dn.date:
            parts = dn.date.split("/")
            if len(parts) >= 2:
                year_month_dash = f"{parts[0]}-{parts[1]}"
        previous_billing = sheets_client.get_previous_billing(
            dn.company_name, year_month_dash
        )

        # 5. 請求書PDF生成（UIの process_pdf と同様）
        safe_company = dn.company_name.replace("/", "_").replace("\\", "_")
        date_safe = dn.date.replace("/", "") if dn.date else ""
        slip_safe = (
            dn.slip_number.replace("/", "_").replace("\\", "_")
            if dn.slip_number
            else ""
        )
        invoice_filename = f"invoice_{safe_company}_{date_safe}_{slip_safe}.pdf"
        invoice_path = output_dir / invoice_filename
        if invoice_path.exists():
            invoice_path.unlink()
        invoice_gen.generate(
            delivery_note=dn,
            company_info=company_info,
            previous_billing=previous_billing,
            output_path=invoice_path,
        )
        result.invoice_pdf = str(invoice_path)

        # 納品書PDFもコピー保存（UIと同様）
        delivery_filename = f"delivery_{safe_company}_{date_safe}_{slip_safe or str(int(time.time()))}.pdf"
        shutil.copy(pdf_path, output_dir / delivery_filename)

        # 6. DB保存
        year_month = year_month_from_date(dn.date)
        result.year_month = year_month
        if not year_month:
            raise ValueError(f"year_month を決定できません: date='{dn.date}'")

        saved = db.save_monthly_items_batch(
            company_name=dn.company_name,
            year_month=year_month,
            delivery_notes=[dn],
            sales_person=sales_person,
            request_id="",
        )
        result.saved_to_db = saved > 0

        # 結果記録
        result.slip_number = dn.slip_number
        result.date = dn.date
        result.subtotal = dn.subtotal
        result.tax = dn.tax
        result.total = dn.total
        result.items_count = len(dn.items)
        result.items_sum = sum(i.amount for i in dn.items)
        result.status = "anomaly_fixed" if (result.user_edits or result.anomalies) else "ok"

        color = C.GREEN if result.status == "ok" else C.YELLOW
        print(
            f"{color}✓ {pdf_path.name}: {dn.company_name} / {dn.date} / "
            f"¥{dn.total:,} → DB保存{C.RESET}"
        )

    except Exception as e:
        result.error = f"{type(e).__name__}: {e}"
        result.status = "error"
        print(f"{C.RED}✗ {pdf_path.name}: {result.error}{C.RESET}")
        traceback.print_exc()

    return result


def progress_file_for(pdf_dir: Path) -> Path:
    """PDFディレクトリごとに一意な進捗ファイルパス"""
    slug = re.sub(r"[^\w.-]", "_", pdf_dir.name) or "batch"
    return PROJECT_ROOT / "reports" / f"progress_{slug}.json"


def load_progress(progress_path: Path) -> dict:
    if not progress_path.exists():
        return {"results": {}}
    try:
        with open(progress_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"{C.YELLOW}進捗ファイル読み込み失敗: {e}（最初からやり直します）{C.RESET}")
        return {"results": {}}


def save_progress(progress_path: Path, pdf_dir: Path, progress_map: dict[str, PDFResult]):
    progress_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = progress_path.with_suffix(".tmp")
    payload = {
        "pdf_dir": str(pdf_dir),
        "updated_at": datetime.now().isoformat(),
        "results": {fname: asdict(r) for fname, r in progress_map.items()},
    }
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    tmp.replace(progress_path)


def reset_db():
    """DBをバックアップして削除 → 空で再初期化"""
    from src.config import DATABASE_PATH

    db_path = Path(DATABASE_PATH)
    if db_path.exists():
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup = db_path.with_name(f"{db_path.name}.bak_{timestamp}")
        shutil.copy(db_path, backup)
        db_path.unlink()
        print(f"{C.GREEN}DBリセット: バックアップ → {backup.name}{C.RESET}")
    else:
        print(f"{C.DIM}DBファイルなし。新規作成します。{C.RESET}")
    MonthlyItemsDB()  # 空のテーブルを作成
    print(f"{C.GREEN}空のDBを初期化しました{C.RESET}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pdf_dir", type=str, help="PDFディレクトリ")
    parser.add_argument("--output", type=str, default="", help="レポートJSONパス")
    parser.add_argument(
        "--auto-approve",
        action="store_true",
        help="会社名マッチ不一致・金額異常でも対話せずに進める",
    )
    parser.add_argument(
        "--limit", type=int, default=0, help="処理する最大件数（0=全件）"
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="進捗ファイルから再開（処理済みファイルはスキップ）",
    )
    parser.add_argument(
        "--reset-db",
        action="store_true",
        help="開始前にローカルDBをバックアップして削除する",
    )
    parser.add_argument(
        "--progress-file",
        type=str,
        default="",
        help="進捗ファイルパス（デフォルト: reports/progress_<ディレクトリ名>.json）",
    )
    args = parser.parse_args()

    pdf_dir = Path(args.pdf_dir).expanduser()
    if not pdf_dir.is_dir():
        print(f"{C.RED}ディレクトリが見つかりません: {pdf_dir}{C.RESET}")
        sys.exit(1)

    if args.reset_db and args.resume:
        print(f"{C.RED}--reset-db と --resume は同時指定できません（整合性が壊れます）{C.RESET}")
        sys.exit(1)

    progress_path = (
        Path(args.progress_file).expanduser()
        if args.progress_file
        else progress_file_for(pdf_dir)
    )

    pdfs = sorted(pdf_dir.glob("*.pdf"))
    if args.limit > 0:
        pdfs = pdfs[: args.limit]

    if not pdfs:
        print(f"{C.RED}PDFが見つかりません: {pdf_dir}{C.RESET}")
        sys.exit(1)

    # --resume 処理（エラーは再試行、ok/修正/スキップは飛ばす）
    done_results: dict[str, PDFResult] = {}
    if args.resume:
        prog = load_progress(progress_path)
        all_loaded: dict[str, PDFResult] = {}
        for fname, r_dict in prog.get("results", {}).items():
            try:
                all_loaded[fname] = PDFResult(**r_dict)
            except TypeError:
                pass  # 古いスキーマは無視
        # エラーは再試行対象（done_resultsには入れない）
        retry_count = sum(1 for r in all_loaded.values() if r.status == "error")
        done_results = {
            fname: r for fname, r in all_loaded.items() if r.status != "error"
        }
        skipped_done = sum(1 for p in pdfs if p.name in done_results)
        print(
            f"{C.CYAN}再開モード: {skipped_done}/{len(pdfs)} 件は処理済み。"
            f"エラー {retry_count} 件は再試行します。{C.RESET}"
        )
    elif progress_path.exists():
        print(f"{C.YELLOW}既存の進捗ファイルがあります: {progress_path.name}{C.RESET}")
        if yn_prompt("上書きして最初から始めますか？（Noなら中止）", default="n"):
            progress_path.unlink()
        else:
            print("中止しました。--resume で再開するか、別ディレクトリで実行してください。")
            sys.exit(0)

    # --reset-db
    if args.reset_db:
        print(f"{C.YELLOW}⚠ ローカルDB (data/monthly_items.db) をリセットします{C.RESET}")
        if not yn_prompt("本当にリセットしますか？", default="n"):
            print("中止しました")
            sys.exit(0)
        reset_db()

    print(f"{C.BOLD}対象: {len(pdfs)} ファイル（未処理: {len(pdfs) - len(done_results)}）{C.RESET}")
    print(f"{C.DIM}スプレッドシートへの書き込みは行いません。DB書き込みのみ。{C.RESET}")
    print(f"{C.DIM}進捗ファイル: {progress_path}{C.RESET}")
    if not args.auto_approve:
        print(f"{C.DIM}異常検知時は対話プロンプトで修正できます。{C.RESET}")
    if not yn_prompt("開始しますか？", default="y"):
        print("中止しました")
        sys.exit(0)

    output_dir = PROJECT_ROOT / "output"
    output_dir.mkdir(exist_ok=True)

    extractor = LLMExtractor()
    sheets_client = GoogleSheetsClient()
    invoice_gen = InvoiceGenerator()
    db = MonthlyItemsDB()

    # progress_map: すべての結果を filename→PDFResult で管理（再試行時も消えない）
    progress_map: dict[str, PDFResult] = {}
    if args.resume:
        progress_map.update(all_loaded)  # エラー含む全件をロード

    start = time.time()
    interrupted = False

    try:
        for i, pdf in enumerate(pdfs, 1):
            if pdf.name in done_results:
                print(f"{C.DIM}[{i}/{len(pdfs)}] スキップ（処理済み）: {pdf.name}{C.RESET}")
                continue

            print(f"\n{C.BLUE}[{i}/{len(pdfs)}]{C.RESET}")
            r = process_pdf(
                pdf, extractor, sheets_client, invoice_gen, db, output_dir, args.auto_approve
            )
            progress_map[pdf.name] = r
            save_progress(progress_path, pdf_dir, progress_map)  # 1件処理ごとに保存
    except KeyboardInterrupt:
        interrupted = True
        print(f"\n{C.YELLOW}中断されました。進捗は {progress_path.name} に保存済み。{C.RESET}")
        print(f"{C.DIM}続きから再開するには: --resume を付けて同じコマンドを実行{C.RESET}")

    # 最終サマリ用: 対象PDFのみを results に（処理順序を保つ）
    results: list[PDFResult] = []
    for pdf in pdfs:
        if pdf.name in progress_map:
            results.append(progress_map[pdf.name])

    elapsed = time.time() - start

    # サマリ
    ok = sum(1 for r in results if r.status == "ok")
    fixed = sum(1 for r in results if r.status == "anomaly_fixed")
    skipped = sum(1 for r in results if r.status == "skipped")
    errors = sum(1 for r in results if r.status == "error")

    print(f"\n{C.BOLD}━━━━━━━━━━ サマリ ━━━━━━━━━━{C.RESET}")
    print(f"  総件数    : {len(results)}")
    print(f"  {C.GREEN}✓ 正常完了: {ok}{C.RESET}")
    print(f"  {C.YELLOW}△ 修正あり: {fixed}{C.RESET}")
    print(f"  {C.DIM}- スキップ: {skipped}{C.RESET}")
    print(f"  {C.RED}✗ エラー  : {errors}{C.RESET}")
    print(f"  経過時間  : {elapsed:.1f}秒")

    total_subtotal = sum(r.subtotal for r in results if r.saved_to_db)
    total_tax = sum(r.tax for r in results if r.saved_to_db)
    total_total = sum(r.total for r in results if r.saved_to_db)
    print(f"\n{C.BOLD}DB保存済み合計:{C.RESET}")
    print(f"  小計合計  : ¥{total_subtotal:,}")
    print(f"  税額合計  : ¥{total_tax:,}")
    print(f"  総合計    : ¥{total_total:,}")

    if errors > 0:
        print(f"\n{C.RED}エラー一覧:{C.RESET}")
        for r in results:
            if r.status == "error":
                print(f"  {r.filename}: {r.error}")
    if fixed > 0:
        print(f"\n{C.YELLOW}修正した伝票:{C.RESET}")
        for r in results:
            if r.status == "anomaly_fixed":
                print(f"  {r.filename}:")
                for e in r.user_edits:
                    print(f"    - {e}")
                for a in r.anomalies:
                    print(f"    ⚠ {a}")

    # JSONレポート出力
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_path = (
        Path(args.output).expanduser()
        if args.output
        else PROJECT_ROOT / "reports" / f"e2e_test_{timestamp}.json"
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(
            {
                "timestamp": timestamp,
                "pdf_dir": str(pdf_dir),
                "total_files": len(results),
                "interrupted": interrupted,
                "summary": {"ok": ok, "anomaly_fixed": fixed, "skipped": skipped, "errors": errors},
                "db_totals": {
                    "subtotal": total_subtotal,
                    "tax": total_tax,
                    "total": total_total,
                },
                "elapsed_seconds": elapsed,
                "results": [asdict(r) for r in results],
            },
            f,
            ensure_ascii=False,
            indent=2,
        )
    print(f"\n{C.CYAN}レポート保存: {output_path}{C.RESET}")
    if not interrupted and progress_path.exists():
        if yn_prompt("全件完了しました。進捗ファイルを削除しますか？", default="y"):
            progress_path.unlink()
            print(f"{C.DIM}進捗ファイルを削除しました{C.RESET}")


if __name__ == "__main__":
    main()
