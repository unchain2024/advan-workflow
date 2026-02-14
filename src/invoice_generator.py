"""請求書PDF生成モジュール

画像サンプルに基づいた日本式請求書フォーマット
"""
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

from .config import OUTPUT_DIR, PDF_FONT_PATH, load_company_config
from .pdf_extractor import DeliveryNote, DeliveryItem
from .sheets_client import CompanyInfo, PreviousBilling


@dataclass
class InvoiceData:
    """請求書データ"""
    # 金額関連
    previous_amount: int  # 前回繰越残高 (1)
    payment_received: int  # 御入金額 (2)
    carried_over: int  # 差引繰越残高 (3)
    subtotal: int  # 売上 (4)
    tax: int  # 消費税額 (5)
    current_amount: int  # 今回御請求額 (6)

    # 日付・番号
    date: str
    closing_date: str  # 締切日
    invoice_number: str  # 請求書番号

    # 相手先情報
    customer_postal_code: str
    customer_address: str
    customer_company_name: str

    # 明細
    items: list  # DeliveryItem のリスト


class InvoiceGenerator:
    """請求書PDF生成クラス（日本式フォーマット）"""

    FONT_NAME = "JapaneseFont"
    PAGE_WIDTH, PAGE_HEIGHT = A4  # 縦向きA4
    ITEMS_PER_PAGE = 18  # 1ページあたりの最大明細行数（ページ累計行を含まない）

    def __init__(self, font_path: Optional[str] = None):
        self.font_path = font_path or PDF_FONT_PATH
        self._font_registered = False

    def _register_font(self):
        """日本語フォントを登録"""
        if self._font_registered:
            return

        try:
            print(f"[DEBUG] Attempting to register font: {self.font_path}")
            from pathlib import Path
            font_file = Path(self.font_path)
            print(f"[DEBUG] Font file exists: {font_file.exists()}")
            print(f"[DEBUG] Font file absolute path: {font_file.absolute()}")

            pdfmetrics.registerFont(TTFont(self.FONT_NAME, str(self.font_path)))
            self._font_registered = True
            print(f"[DEBUG] Font '{self.FONT_NAME}' registered successfully")
        except Exception as e:
            # フォントが見つからない場合はデフォルトフォントを使用
            print(f"❌ フォント登録エラー: {type(e).__name__}: {e}")
            print(f"   フォントパス: {self.font_path}")
            print(f"   Helvetica フォントにフォールバックします（日本語表示不可）")
            self.FONT_NAME = "Helvetica"
            self._font_registered = True

    def generate(
        self,
        delivery_note: DeliveryNote,
        company_info: Optional[CompanyInfo],
        previous_billing: PreviousBilling,
        output_path: Optional[Path] = None,
        invoice_number: str = "",
        is_monthly: bool = False,
    ) -> Path:
        """請求書PDFを生成

        Args:
            delivery_note: 納品書データ（月次の場合は複数納品書を含む）
            company_info: 会社情報
            previous_billing: 前月の請求情報
            output_path: 出力パス
            invoice_number: 請求書番号
            is_monthly: 月次請求書モードの場合True
        """
        self._register_font()

        # デバッグ: 入力データを出力
        print(f"DEBUG: delivery_note.date = {delivery_note.date}")
        print(f"DEBUG: delivery_note.company_name = {delivery_note.company_name}")

        # 締切日を計算
        date_str = delivery_note.date or datetime.now().strftime("%Y/%m/%d")
        try:
            date_parts = date_str.split("/")
            year = int(date_parts[0])
            month = int(date_parts[1])

            if is_monthly:
                # 月次請求書モード: 「YYYY年M月分 (月次請求書)」
                closing_date = f"{year}年{month}月分 (月次請求書)"
            else:
                # 通常モード: 月末締切
                if month == 12:
                    next_month = datetime(year + 1, 1, 1)
                else:
                    next_month = datetime(year, month + 1, 1)
                last_day = (next_month - timedelta(days=1)).day
                closing_date = f"{year}年{month}月{last_day}日締切分"
        except (ValueError, IndexError):
            closing_date = f"{date_str} 締切分"

        # 請求書データを構築
        invoice_data = InvoiceData(
            previous_amount=previous_billing.previous_amount,
            payment_received=previous_billing.payment_received,
            carried_over=previous_billing.carried_over,
            subtotal=delivery_note.subtotal,
            tax=delivery_note.tax,
            current_amount=(
                previous_billing.carried_over + delivery_note.subtotal + delivery_note.tax
            ),
            date=date_str,
            closing_date=closing_date,
            invoice_number=invoice_number or self._generate_invoice_number(),
            customer_postal_code=company_info.postal_code if company_info else "",
            customer_address=company_info.address if company_info else "",
            customer_company_name=delivery_note.company_name,
            items=delivery_note.items,
        )

        # 出力パス（一時ファイルとして生成）
        if output_path is None:
            import tempfile
            safe_name = (delivery_note.company_name or "unknown").replace("/", "_").replace("\\", "_")
            date_str = (invoice_data.date or "").replace('/', '')
            filename = f"invoice_{safe_name}_{date_str}.pdf"
            # 一時ディレクトリに保存（セッション終了時に自動削除）
            temp_dir = Path(tempfile.gettempdir()) / "invoice_temp"
            temp_dir.mkdir(exist_ok=True)
            output_path = temp_dir / filename

        # PDF生成（複数ページ対応）
        self._create_pdf(invoice_data, output_path)

        return output_path

    def _generate_invoice_number(self) -> str:
        """請求書番号を生成"""
        now = datetime.now()
        return f"{now.strftime('%y%m%d')}-001"

    def generate_monthly(
        self,
        delivery_notes: list[DeliveryNote],
        company_name: str,
        year_month: str,
        company_info: Optional[CompanyInfo],
        previous_billing: PreviousBilling,
        output_path: Optional[Path] = None,
        invoice_number: str = "",
    ) -> Path:
        """月次請求書PDFを生成（複数の納品書をまとめる）

        Args:
            delivery_notes: 納品書データのリスト
            company_name: 会社名
            year_month: 年月（YYYY年M月形式）
            company_info: 会社情報
            previous_billing: 前月の請求情報
            output_path: 出力パス
            invoice_number: 請求書番号

        Returns:
            Path: 生成されたPDFファイルのパス
        """
        # 明細を納品日ごとにグループ化してセパレーター付きで結合
        all_items = []

        for note in delivery_notes:
            # セパレーター行を追加
            separator = DeliveryItem(
                slip_number="",
                product_code="",
                product_name=f"=== 納品日: {note.date} (伝票番号: {note.slip_number}) ===",
                quantity=0,
                unit_price=0,
                amount=0,
                date=note.date,
            )
            all_items.append(separator)

            # 納品書の明細を追加（各アイテムに納品日を設定）
            for item in note.items:
                item_with_date = DeliveryItem(
                    slip_number=item.slip_number,
                    product_code=item.product_code,
                    product_name=item.product_name,
                    quantity=item.quantity,
                    unit_price=item.unit_price,
                    amount=item.amount,
                    date=note.date,
                )
                all_items.append(item_with_date)

        # 全納品書の合計を計算
        total_subtotal = sum(note.subtotal for note in delivery_notes)
        total_tax = sum(note.tax for note in delivery_notes)
        total_amount = total_subtotal + total_tax

        # 代表の納品書データを作成（明細は結合したもの）
        from .utils import get_month_end_date
        month_end_date = get_month_end_date(year_month)

        combined_note = DeliveryNote(
            slip_number=f"月次-{year_month}",
            date=month_end_date,
            company_name=company_name,
            items=all_items,
            subtotal=total_subtotal,
            tax=total_tax,
            total=total_amount,
        )

        # 通常のgenerate()を呼び出し（is_monthly=True）
        return self.generate(
            delivery_note=combined_note,
            company_info=company_info,
            previous_billing=previous_billing,
            output_path=output_path,
            invoice_number=invoice_number,
            is_monthly=True,
        )

    def _create_pdf(self, data: InvoiceData, output_path: Path):
        """PDFを作成（複数ページ対応）"""
        # デバッグ: 日付を出力
        print(f"DEBUG: PDF生成 - data.date = {data.date}")

        c = canvas.Canvas(str(output_path), pagesize=A4)
        width, height = A4

        # 明細を準備（前回請求額を先頭に追加）
        all_items = []

        # 前回請求額がある場合、先頭に追加
        if data.previous_amount > 0:
            prev_item = DeliveryItem(
                slip_number="",
                product_code="",
                product_name="*** 前回請求額 ***",
                quantity=0,
                unit_price=0,
                amount=data.previous_amount,
            )
            all_items.append(prev_item)

        # 実際の明細を追加
        all_items.extend(data.items)

        # ページ分割
        total_pages = (len(all_items) + self.ITEMS_PER_PAGE - 1) // self.ITEMS_PER_PAGE
        if total_pages == 0:
            total_pages = 1

        for page_num in range(total_pages):
            if page_num > 0:
                c.showPage()  # 新しいページ

            start_idx = page_num * self.ITEMS_PER_PAGE
            end_idx = min(start_idx + self.ITEMS_PER_PAGE, len(all_items))
            page_items = all_items[start_idx:end_idx]

            self._draw_page(c, data, page_items, page_num + 1, total_pages, width, height)

        c.save()

    def _draw_page(self, c, data: InvoiceData, page_items: list, page_num: int, total_pages: int, width, height):
        """1ページを描画"""
        # マージン設定
        margin_left = 15 * mm
        margin_right = 15 * mm
        margin_top = 15 * mm
        margin_bottom = 15 * mm

        # 1ページ目のみヘッダー情報を表示
        if page_num == 1:
            # ===== ヘッダー部分 =====
            self._draw_header(c, data, width, height, margin_left, margin_top)

            # ===== 相手先情報（左側）=====
            self._draw_customer_info(c, data, margin_left, height - margin_top - 25 * mm)

            # ===== 自社情報（右側）=====
            self._draw_own_info(c, width - margin_right, height - margin_top - 15 * mm)

            # ===== 請求文言 =====
            c.setFont(self.FONT_NAME, 11)
            billing_text = f"下記の通りご請求申し上げます　{data.closing_date}"
            billing_y = height - margin_top - 56 * mm
            c.drawString(margin_left + 5 * mm, billing_y, billing_text)

            # ===== サマリー部分（金額集計）=====
            summary_y = height - margin_top - 64 * mm
            self._draw_summary(c, data, margin_left + 5 * mm, summary_y)

            # 明細テーブルの開始Y位置
            table_y = height - margin_top - 90 * mm
        else:
            # 2ページ目以降はテーブルだけ
            table_y = height - margin_top - 20 * mm

        # ===== 明細テーブル =====
        self._draw_detail_table(c, data, page_items, margin_left, table_y, width - margin_left - margin_right, page_num)

        # ===== ページ番号とNo =====
        self._draw_page_info(c, data, width - margin_right - 5 * mm, height - margin_top - 3 * mm, page_num)

    def _draw_header(self, c, data: InvoiceData, width, height, margin_left, margin_top):
        """ヘッダー（タイトル）を描画"""
        c.setFont(self.FONT_NAME, 24)
        # タイトルを中央に配置
        title = "請  求  書"
        title_width = c.stringWidth(title, self.FONT_NAME, 24)
        c.drawString((width - title_width) / 2, height - margin_top - 15 * mm, title)

    def _draw_customer_info(self, c, data: InvoiceData, x, y):
        """相手先情報を描画"""
        c.setFont(self.FONT_NAME, 10)
        line_height = 5 * mm

        # 郵便番号
        c.drawString(x, y, f"〒 {data.customer_postal_code}")
        y -= line_height

        # 住所
        c.drawString(x, y, data.customer_address)
        y -= line_height * 1.5

        # 会社名
        c.setFont(self.FONT_NAME, 12)
        c.drawString(x, y, f"{data.customer_company_name}  御中")

    def _draw_own_info(self, c, x, y):
        """自社情報を描画（右寄せ）"""
        # 最新の自社情報を読み込む
        own_company = load_company_config()

        c.setFont(self.FONT_NAME, 9)
        line_height = 4.5 * mm

        # 登録番号
        text = f"登録番号: {own_company['registration_number']}"
        c.drawRightString(x, y, text)
        y -= line_height * 1.5

        # 会社名
        c.setFont(self.FONT_NAME, 12)
        c.drawRightString(x, y, own_company["company_name"])
        y -= line_height * 1.5

        # 郵便番号・住所
        c.setFont(self.FONT_NAME, 9)
        c.drawRightString(x, y, f"〒 {own_company['postal_code']}")
        y -= line_height
        c.drawRightString(x, y, own_company["address"])
        y -= line_height

        # 電話番号
        c.drawRightString(x, y, f"TEL {own_company['phone']}")
        y -= line_height * 1.5

        # 振込銀行
        c.drawRightString(x, y, f"振込銀行: {own_company['bank_info']}")

    def _draw_summary(self, c, data: InvoiceData, x, y):
        """金額サマリーをテーブル形式で描画"""
        c.setFont(self.FONT_NAME, 9)
        c.setStrokeColor(colors.black)
        c.setLineWidth(0.5)

        # 列定義（6列）
        columns = [
            ("前回繰越残高", data.previous_amount),
            ("御入金額", data.payment_received),
            ("差引繰越残高", data.carried_over),
            ("売上", data.subtotal),
            ("消費税額", data.tax),
            ("今回御請求額", data.current_amount),
        ]

        col_width = 28 * mm
        row_height = 8 * mm

        # ヘッダー行（列名）
        current_x = x
        for col_name, _ in columns:
            c.rect(current_x, y - row_height, col_width, row_height)
            # テキストを中央に配置
            text_width = c.stringWidth(col_name, self.FONT_NAME, 9)
            c.drawString(current_x + (col_width - text_width) / 2, y - row_height + 2.5 * mm, col_name)
            current_x += col_width

        # データ行（金額）
        y -= row_height
        current_x = x
        for i, (_, value) in enumerate(columns):
            # 今回御請求額は太枠
            if i == len(columns) - 1:
                c.setLineWidth(1.5)
            else:
                c.setLineWidth(0.5)

            c.rect(current_x, y - row_height, col_width, row_height)

            # 金額を右寄せで表示
            c.drawRightString(current_x + col_width - 2 * mm, y - row_height + 2.5 * mm, f"{value:,}")
            current_x += col_width

    def _draw_detail_table(self, c, data: InvoiceData, page_items: list, x, y, table_width, page_num: int):
        """明細テーブルを描画（ページ累計列なし、ページ累計行あり）"""
        # カラム定義（ページ累計列を削除）
        columns = [
            ("日付", 18 * mm),
            ("伝票番号", 18 * mm),
            ("商品コード", 25 * mm),
            ("品      名", 50 * mm),
            ("数量", 12 * mm),
            ("単価", 18 * mm),
            ("金額", 20 * mm),
        ]

        row_height = 6 * mm
        header_height = 8 * mm

        # ヘッダー描画
        c.setFont(self.FONT_NAME, 9)
        c.setStrokeColor(colors.black)
        c.setLineWidth(0.5)

        current_x = x
        for col_name, col_width in columns:
            # ヘッダーセル
            c.rect(current_x, y - header_height, col_width, header_height)
            # テキストを中央に
            text_width = c.stringWidth(col_name, self.FONT_NAME, 9)
            c.drawString(current_x + (col_width - text_width) / 2, y - header_height + 2.5 * mm, col_name)
            current_x += col_width

        # データ行描画
        data_y = y - header_height
        page_total_quantity = 0
        page_total_amount = 0
        c.setFont(self.FONT_NAME, 8)

        for item in page_items:
            data_y -= row_height
            current_x = x

            # 日付（アイテムにdateがあればそれを使用、なければdata.dateを使用）
            item_date = getattr(item, 'date', '') or data.date
            date_str = ""
            if item_date:
                try:
                    # YYYY/MM/DD → YY/MM/DD に変換
                    parts = item_date.split("/")
                    if len(parts) == 3:
                        # YYYYが4桁の場合のみ下2桁を取得
                        year = parts[0]
                        if len(year) == 4:
                            date_str = f"{year[2:]}/{parts[1].zfill(2)}/{parts[2].zfill(2)}"
                        else:
                            date_str = f"{year}/{parts[1].zfill(2)}/{parts[2].zfill(2)}"
                    else:
                        date_str = item_date
                except Exception as e:
                    print(f"日付変換エラー: {item_date} -> {e}")
                    date_str = item_date

            c.rect(current_x, data_y, columns[0][1], row_height)
            c.drawString(current_x + 1 * mm, data_y + 1.5 * mm, date_str)
            current_x += columns[0][1]

            # 伝票番号（明細行の伝票番号を使用、"None"の場合は空欄に）
            # 伝票番号がない場合は日付列を空欄にする
            slip_num = ""
            if item.slip_number and item.slip_number != "None" and len(item.slip_number.strip()) > 0:
                slip_num = item.slip_number[:10]
            c.rect(current_x, data_y, columns[1][1], row_height)
            c.drawString(current_x + 1 * mm, data_y + 1.5 * mm, slip_num)
            current_x += columns[1][1]

            # 商品コード（"None"の場合は空欄に）
            prod_code = item.product_code[:15] if item.product_code and item.product_code != "None" else ""
            c.rect(current_x, data_y, columns[2][1], row_height)
            c.drawString(current_x + 1 * mm, data_y + 1.5 * mm, prod_code)
            current_x += columns[2][1]

            # 品名（短く切り詰める）
            c.rect(current_x, data_y, columns[3][1], row_height)
            c.drawString(current_x + 1 * mm, data_y + 1.5 * mm, item.product_name[:30])
            current_x += columns[3][1]

            # 数量
            c.rect(current_x, data_y, columns[4][1], row_height)
            if item.quantity > 0:  # 数量が0の場合は表示しない（前回請求額など）
                c.drawRightString(current_x + columns[4][1] - 1 * mm, data_y + 1.5 * mm, str(item.quantity))
                page_total_quantity += item.quantity
            current_x += columns[4][1]

            # 単価
            c.rect(current_x, data_y, columns[5][1], row_height)
            if item.unit_price > 0:
                c.drawRightString(current_x + columns[5][1] - 1 * mm, data_y + 1.5 * mm, f"{item.unit_price:,}")
            current_x += columns[5][1]

            # 金額
            c.rect(current_x, data_y, columns[6][1], row_height)
            c.drawRightString(current_x + columns[6][1] - 1 * mm, data_y + 1.5 * mm, f"{item.amount:,}")
            page_total_amount += item.amount
            current_x += columns[6][1]

        # ページ累計行を追加
        data_y -= row_height
        current_x = x

        for j, (_, col_width) in enumerate(columns):
            c.rect(current_x, data_y, col_width, row_height)
            if j == 3:  # 品名列に「ページ累計」
                c.setFont(self.FONT_NAME, 9)
                c.drawString(current_x + 1 * mm, data_y + 1.5 * mm, "ページ累計")
                c.setFont(self.FONT_NAME, 8)
            elif j == 4:  # 数量列
                if page_total_quantity > 0:
                    c.drawRightString(current_x + col_width - 1 * mm, data_y + 1.5 * mm, str(page_total_quantity))
            elif j == 6:  # 金額列
                c.drawRightString(current_x + col_width - 1 * mm, data_y + 1.5 * mm, f"{page_total_amount:,}")
            current_x += col_width

        # 空行を追加して表を埋める（必要に応じて）
        remaining_rows = self.ITEMS_PER_PAGE - len(page_items)
        for _ in range(max(0, remaining_rows)):
            data_y -= row_height
            current_x = x
            for _, col_width in columns:
                c.rect(current_x, data_y, col_width, row_height)
                current_x += col_width

    def _draw_page_info(self, c, data: InvoiceData, x, y, page_num: int):
        """ページ番号と請求書番号を描画（右上）"""
        c.setFont(self.FONT_NAME, 9)

        # "No." の文字列
        no_text = "No."
        no_width = c.stringWidth(no_text, self.FONT_NAME, 9)

        # 1行目: ページ番号
        page_text = f"No.     {page_num}"
        c.drawRightString(x, y, page_text)

        # "No." に下線を引く
        c.setLineWidth(0.5)
        # 右端からページ番号全体の幅を引き、さらに "No." の幅を足して位置を調整
        page_text_width = c.stringWidth(page_text, self.FONT_NAME, 9)
        underline_x_start = x - page_text_width
        underline_x_end = underline_x_start + no_width
        c.line(underline_x_start, y - 1 * mm, underline_x_end, y - 1 * mm)

        # 2行目: 請求書番号
        c.drawRightString(x, y - 5 * mm, data.invoice_number)

    def _format_currency(self, amount: int) -> str:
        """金額をフォーマット"""
        return f"{amount:,}"
