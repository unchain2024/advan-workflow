"""メインスクリプト

納品書PDFから請求書PDFを生成するワークフロー

処理フロー:
1. 納品書PDF → 画像変換 → Claude Vision APIでOCR+構造化
2. 会社マスターから郵便番号・住所を取得
3. 売上集計表から前月の請求情報を取得
4. 請求書PDFを生成
5. 売上集計表に保存（発生・消費税を加算）

使用方法:
    python -m src.main <納品書PDFパス>
    python -m src.main input/delivery_note.pdf
    python -m src.main input/*.pdf  # 複数ファイル処理
"""
import argparse
import sys
from pathlib import Path

from .config import INPUT_DIR, OUTPUT_DIR
from .invoice_generator import InvoiceGenerator
from .llm_extractor import LLMExtractor
from .sheets_client import GoogleSheetsClient


def extract_year_month(date_str: str) -> str:
    """日付文字列からYYYY-MM形式の年月を抽出

    Args:
        date_str: 日付文字列（YYYY/MM/DD形式）

    Returns:
        YYYY-MM形式の年月
    """
    # YYYY/MM/DD -> YYYY-MM
    if "/" in date_str:
        parts = date_str.split("/")
        if len(parts) >= 2:
            return f"{parts[0]}-{parts[1]}"
    return ""


def process_delivery_note(pdf_path: Path, dry_run: bool = False) -> Path:
    """納品書PDFを処理して請求書PDFを生成

    Args:
        pdf_path: 納品書PDFのパス
        dry_run: Trueの場合、Google Sheetsへの書き込みをスキップ

    Returns:
        生成された請求書PDFのパス
    """
    print(f"処理中: {pdf_path}")

    # 1. LLMで画像からデータ抽出
    print("  - 納品書PDFを画像として読み取り中...")
    print("  - Claude Vision APIでOCR+構造化抽出中...")
    extractor = LLMExtractor()
    delivery_note = extractor.extract(pdf_path)

    print(f"    会社名: {delivery_note.company_name}")
    print(f"    日付: {delivery_note.date}")
    print(f"    伝票番号: {delivery_note.slip_number}")
    print(f"    明細数: {len(delivery_note.items)}")
    print(f"    売上: ¥{delivery_note.subtotal:,}")
    print(f"    消費税: ¥{delivery_note.tax:,}")
    print(f"    合計: ¥{delivery_note.total:,}")
    print(f"    入金額: ¥{delivery_note.payment_received:,}")

    # 明細の詳細を表示
    if delivery_note.items:
        print("    明細:")
        for item in delivery_note.items[:5]:  # 最初の5件のみ表示
            print(f"      - {item.product_name}: {item.quantity}個 × ¥{item.unit_price:,} = ¥{item.amount:,}")
        if len(delivery_note.items) > 5:
            print(f"      ... 他 {len(delivery_note.items) - 5} 件")

    # 2. Google Sheets連携
    sheets_client = GoogleSheetsClient()

    # 会社情報を取得
    print("  - 会社マスターから情報を取得中...")
    company_info = sheets_client.get_company_info(delivery_note.company_name)
    if company_info:
        print(f"    会社情報取得: 〒{company_info.postal_code} {company_info.address}")
        if company_info.department:
            print(f"    事業部: {company_info.department}")
    else:
        print("    警告: 会社マスターに該当する会社が見つかりませんでした")

    # 年月を計算
    year_month = extract_year_month(delivery_note.date)

    # 前月の請求情報を取得
    print("  - 前月の請求情報を取得中...")
    previous_billing = sheets_client.get_previous_billing(delivery_note.company_name, year_month)
    print(f"    前回繰越残高: ¥{previous_billing.previous_amount:,}")
    print(f"    御入金額: ¥{previous_billing.payment_received:,}")
    print(f"    差引繰越残高: ¥{previous_billing.carried_over:,}")

    # 3. 請求書PDF生成
    print("  - 請求書PDFを生成中...")
    generator = InvoiceGenerator()
    invoice_path = generator.generate(
        delivery_note=delivery_note,
        company_info=company_info,
        previous_billing=previous_billing,
    )
    print(f"    出力: {invoice_path}")

    # 4. 売上集計表に保存
    if not dry_run:
        print("  - 売上集計表に保存中...")
        sheets_client.save_billing_record(
            company_name=delivery_note.company_name,
            previous_billing=previous_billing,
            delivery_note=delivery_note,
        )
    else:
        print("  - [DRY RUN] 売上集計表への保存をスキップ")

    print(f"完了: {pdf_path}")
    return invoice_path


def main():
    """メイン関数"""
    parser = argparse.ArgumentParser(
        description="納品書PDFから請求書PDFを生成するワークフロー（LLM抽出版）"
    )
    parser.add_argument(
        "pdf_files",
        nargs="*",
        help="処理する納品書PDFファイル（指定がない場合はinputディレクトリ内のPDFを処理）",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Google Sheetsへの書き込みをスキップ（PDF生成のみ）",
    )

    args = parser.parse_args()

    # 処理対象ファイルを決定
    if args.pdf_files:
        pdf_files = [Path(f) for f in args.pdf_files]
    else:
        pdf_files = list(INPUT_DIR.glob("*.pdf"))

    if not pdf_files:
        print("処理対象のPDFファイルが見つかりません")
        print(f"inputディレクトリにPDFを配置するか、引数でファイルを指定してください")
        print(f"  inputディレクトリ: {INPUT_DIR}")
        sys.exit(1)

    print(f"処理対象: {len(pdf_files)} ファイル")
    print(f"出力先: {OUTPUT_DIR}")
    if args.dry_run:
        print("モード: DRY RUN（Google Sheetsへの書き込みなし）")
    print("-" * 50)

    # 出力ディレクトリを作成
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # 各ファイルを処理
    success_count = 0
    error_count = 0
    generated_files = []

    for pdf_file in pdf_files:
        try:
            if not pdf_file.exists():
                print(f"エラー: ファイルが見つかりません: {pdf_file}")
                error_count += 1
                continue

            invoice_path = process_delivery_note(pdf_file, dry_run=args.dry_run)
            generated_files.append(invoice_path)
            success_count += 1

        except Exception as e:
            print(f"エラー: {pdf_file} の処理中にエラーが発生しました: {e}")
            import traceback
            traceback.print_exc()
            error_count += 1

    # サマリー
    print("-" * 50)
    print(f"処理完了: 成功 {success_count}, エラー {error_count}")

    if generated_files:
        print("\n生成された請求書PDF:")
        for path in generated_files:
            print(f"  - {path}")


if __name__ == "__main__":
    main()
