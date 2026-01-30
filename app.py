"""納品書処理システム - Webアプリ

機能:
1. 納品書PDFのアップロード・処理
2. 消滅（入金額）の入力
"""
import streamlit as st
from pathlib import Path
import tempfile
from datetime import datetime

from src.llm_extractor import LLMExtractor
from src.sheets_client import GoogleSheetsClient
from src.invoice_generator import InvoiceGenerator
from src.config import (
    BILLING_SPREADSHEET_ID,
    BILLING_SHEET_NAME,
    COMPANY_MASTER_SPREADSHEET_ID,
    COMPANY_MASTER_SHEET_NAME,
    OWN_COMPANY,
    load_company_config,
    save_company_config,
)

# ページ設定
st.set_page_config(
    page_title="納品書処理システム",
    page_icon="📄",
    layout="wide",
)

# セッション状態の初期化
if "sheets_client" not in st.session_state:
    st.session_state.sheets_client = None
if "show_edit_form" not in st.session_state:
    st.session_state.show_edit_form = False
if "spreadsheet_saved" not in st.session_state:
    st.session_state.spreadsheet_saved = False


def get_sheets_client():
    """Google Sheetsクライアントを取得（キャッシュ）"""
    if st.session_state.sheets_client is None:
        st.session_state.sheets_client = GoogleSheetsClient()
    return st.session_state.sheets_client


def process_pdf(pdf_file):
    """PDFを処理して請求書を生成"""
    # 前回の一時ファイルをクリーンアップ
    if "current_delivery_pdf" in st.session_state:
        old_path = st.session_state.current_delivery_pdf
        if old_path and old_path.exists():
            old_path.unlink(missing_ok=True)

    # 前回の請求書PDFもクリーンアップ
    if "current_invoice_path" in st.session_state:
        old_invoice = st.session_state.current_invoice_path
        if old_invoice and old_invoice.exists():
            old_invoice.unlink(missing_ok=True)

    # 一時ファイルに保存
    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp_file:
        tmp_file.write(pdf_file.read())
        tmp_path = Path(tmp_file.name)

    # 納品書PDFもセッション状態に保存（比較表示用）
    st.session_state.current_delivery_pdf = tmp_path

    try:
        # 1. PDF抽出
        with st.spinner("📄 PDFからデータを抽出中..."):
            st.info("🤖 Claude Vision APIで納品書を解析しています...")
            extractor = LLMExtractor()
            delivery_note = extractor.extract(tmp_path)

        st.success(f"✅ **データ抽出完了**: {delivery_note.company_name}")

        # 抽出データを表示
        with st.expander("📋 抽出されたデータ", expanded=True):
            col1, col2, col3 = st.columns(3)
            with col1:
                st.metric("会社名", delivery_note.company_name)
                st.metric("日付", delivery_note.date)
            with col2:
                st.metric("売上", f"¥{delivery_note.subtotal:,}")
                st.metric("消費税", f"¥{delivery_note.tax:,}")
            with col3:
                st.metric("合計", f"¥{delivery_note.total:,}")
                st.metric("明細数", len(delivery_note.items))

            # 明細の詳細も表示
            if delivery_note.items:
                st.write("**明細:**")
                for i, item in enumerate(delivery_note.items[:5], 1):
                    st.text(f"{i}. {item.product_name}: {item.quantity}個 × ¥{item.unit_price:,} = ¥{item.amount:,}")
                if len(delivery_note.items) > 5:
                    st.text(f"... 他 {len(delivery_note.items) - 5} 件")

        # 2. 会社情報取得
        with st.spinner("🏢 会社マスターから情報を取得中..."):
            st.info("📊 **会社マスターシート** から会社情報を検索...")
            sheets_client = get_sheets_client()
            company_info = sheets_client.get_company_info(delivery_note.company_name)

        if company_info:
            st.success(f"✅ **会社情報取得完了**")
            st.info(f"📍 〒{company_info.postal_code} {company_info.address}")
            if company_info.department:
                st.info(f"🏢 事業部: {company_info.department}")
        else:
            st.warning("⚠️ 会社マスターに該当する会社が見つかりませんでした")

        # 3. 前月の請求情報を取得
        with st.spinner("📊 売上集計表から前月情報を取得中..."):
            # 日付から年月を抽出
            if delivery_note.date and '/' in delivery_note.date:
                parts = delivery_note.date.split('/')
                if len(parts) >= 2:
                    year_month = f"{parts[0]}-{parts[1]}"
                else:
                    st.warning("⚠️ 日付形式が不正です。現在の年月を使用します。")
                    from datetime import datetime
                    year_month = datetime.now().strftime("%Y-%m")
            else:
                st.warning("⚠️ 日付が抽出できませんでした。現在の年月を使用します。")
                from datetime import datetime
                year_month = datetime.now().strftime("%Y-%m")

            st.info(f"🔍 **売上集計表** から {year_month} の前月データを検索...")
            previous_billing = sheets_client.get_previous_billing(
                delivery_note.company_name, year_month
            )

        # 前月情報を表示
        if previous_billing:
            with st.expander("💰 前月の請求情報", expanded=False):
                col1, col2, col3 = st.columns(3)
                with col1:
                    st.metric("前回繰越残高", f"¥{previous_billing.previous_amount:,}")
                with col2:
                    st.metric("御入金額", f"¥{previous_billing.payment_received:,}")
                with col3:
                    st.metric("差引繰越残高", f"¥{previous_billing.carried_over:,}")

        # 4. 請求書PDF生成
        with st.spinner("📝 請求書PDFを生成中..."):
            st.info("🖨️ ReportLabで請求書PDFを作成しています...")
            invoice_generator = InvoiceGenerator()
            invoice_path = invoice_generator.generate(
                delivery_note=delivery_note,
                company_info=company_info,
                previous_billing=previous_billing,
            )

        st.success(f"✅ **請求書PDF生成完了**: {invoice_path.name}")

        # データをセッション状態に保存（編集時に使用）
        st.session_state.current_delivery_note = delivery_note
        st.session_state.current_company_info = company_info
        st.session_state.current_previous_billing = previous_billing
        st.session_state.current_invoice_path = invoice_path
        st.session_state.current_year_month = year_month
        # 新しいPDF処理時はスプレッドシート保存フラグをリセット
        st.session_state.spreadsheet_saved = False

        # 請求書の内容サマリー
        total_amount = previous_billing.carried_over + delivery_note.subtotal + delivery_note.tax
        with st.expander("📄 請求書の内容", expanded=False):
            st.write(f"**今回御請求額**: ¥{total_amount:,}")
            st.write(f"- 差引繰越残高: ¥{previous_billing.carried_over:,}")
            st.write(f"- 今回売上: ¥{delivery_note.subtotal:,}")
            st.write(f"- 消費税: ¥{delivery_note.tax:,}")

        st.success("🎉 請求書PDFの生成が完了しました！")

        return True

    except Exception as e:
        st.error(f"❌ エラーが発生しました: {e}")
        import traceback
        st.code(traceback.format_exc())
        return False

    finally:
        # 一時ファイルは削除しない（プレビュー表示で使用するため）
        # セッション状態に保存されているので、次回アップロード時にクリーンアップ
        pass


def show_pdf_preview_and_edit():
    """PDFプレビューと編集機能を表示"""
    if "current_invoice_path" not in st.session_state:
        return

    invoice_path = st.session_state.current_invoice_path
    delivery_note = st.session_state.current_delivery_note
    company_info = st.session_state.current_company_info
    previous_billing = st.session_state.current_previous_billing
    year_month = st.session_state.current_year_month
    delivery_pdf_path = st.session_state.get("current_delivery_pdf")

    # PDFプレビュー表示（左右比較）
    st.markdown("---")
    st.subheader("📄 PDF比較プレビュー")

    # PDFを画像に変換
    from pdf2image import convert_from_path

    # 納品書（入力）
    if delivery_pdf_path and delivery_pdf_path.exists():
        delivery_images = convert_from_path(str(delivery_pdf_path), dpi=100)
    else:
        delivery_images = []

    # 請求書（生成）
    invoice_images = convert_from_path(str(invoice_path), dpi=100)

    # 左右に並べて表示
    max_pages = max(len(delivery_images), len(invoice_images))

    for i in range(max_pages):
        col1, col2 = st.columns(2)

        with col1:
            if i < len(delivery_images):
                st.image(delivery_images[i], caption=f"📥 納品書（入力） - ページ {i+1}", width="stretch")
            else:
                st.info("納品書: このページはありません")

        with col2:
            if i < len(invoice_images):
                st.image(invoice_images[i], caption=f"📤 請求書（生成） - ページ {i+1}", width="stretch")
            else:
                st.info("請求書: このページはありません")

    # 編集ボタン
    col1, col2 = st.columns([1, 3])
    with col1:
        edit_mode = st.button("✏️ 内容を編集", type="secondary", use_container_width=True)

    # 編集モード
    if edit_mode or st.session_state.get("show_edit_form", False):
        st.session_state.show_edit_form = True

        st.markdown("---")
        st.subheader("✏️ 請求書内容の編集")

        with st.form("edit_invoice_form"):
            st.write("### 基本情報")

            # 日付の妥当性チェック
            import re
            current_date = delivery_note.date or ""
            date_pattern = r'^(20\d{2})/(0[1-9]|1[0-2])/(0[1-9]|[12]\d|3[01])$'

            if current_date and not re.match(date_pattern, current_date):
                st.warning(f"⚠️ 無効な日付形式が検出されました: `{current_date}` → 正しい形式（YYYY/MM/DD）で入力してください")
                current_date = ""  # 無効な場合は空にする

            col1, col2 = st.columns(2)
            with col1:
                edited_date = st.text_input("日付 (YYYY/MM/DD)", value=current_date, placeholder="2025/03/15")
                edited_company = st.text_input("会社名", value=delivery_note.company_name or "")
                edited_slip = st.text_input("伝票番号", value=delivery_note.slip_number or "")
            with col2:
                edited_subtotal = st.number_input("小計（税抜）", value=delivery_note.subtotal, step=1000)
                edited_tax = st.number_input("消費税", value=delivery_note.tax, step=100)
                edited_payment = st.number_input("御入金額", value=delivery_note.payment_received, step=1000)

            st.write("### 前月情報")
            col3, col4 = st.columns(2)
            with col3:
                edited_prev_amount = st.number_input("前回繰越残高", value=previous_billing.previous_amount, step=1000)
                edited_prev_payment = st.number_input("前月御入金額", value=previous_billing.payment_received, step=1000)

            st.write("### 明細情報")
            st.caption("※ 明細を編集できます。空白行は削除されます。")

            # 日付表示（妥当性チェック済み）
            if edited_date and re.match(date_pattern, edited_date):
                st.info(f"📅 日付: **{edited_date}** （上の基本情報で変更できます）")
            else:
                st.warning(f"⚠️ 日付が未設定または無効です。上の基本情報で正しい日付を入力してください。")

            edited_items = []
            for idx, item in enumerate(delivery_note.items):
                with st.expander(f"明細 {idx + 1}: {item.product_name}", expanded=False):
                    item_col1, item_col2, item_col3 = st.columns(3)
                    with item_col1:
                        item_slip = st.text_input(f"伝票番号", value=item.slip_number or "", key=f"item_slip_{idx}")
                        item_code = st.text_input(f"商品コード", value=item.product_code or "", key=f"item_code_{idx}")
                    with item_col2:
                        item_name = st.text_input(f"品名", value=item.product_name or "", key=f"item_name_{idx}")
                        item_qty = st.number_input(f"数量", value=item.quantity, step=1, key=f"item_qty_{idx}")
                    with item_col3:
                        item_price = st.number_input(f"単価", value=item.unit_price, step=100, key=f"item_price_{idx}")
                        item_amount = st.number_input(f"金額", value=item.amount, step=100, key=f"item_amount_{idx}")

                    edited_items.append({
                        "slip_number": item_slip,
                        "product_code": item_code,
                        "product_name": item_name,
                        "quantity": item_qty,
                        "unit_price": item_price,
                        "amount": item_amount,
                    })

            submit_col1, submit_col2 = st.columns([1, 3])
            with submit_col1:
                regenerate = st.form_submit_button("🔄 PDFを再生成", type="primary", use_container_width=True)
            with submit_col2:
                cancel = st.form_submit_button("キャンセル", use_container_width=True)

            if regenerate:
                # 編集された明細を DeliveryItem に変換（空白行を除外）
                from src.pdf_extractor import DeliveryNote, DeliveryItem
                final_items = []
                for item_data in edited_items:
                    # 品名が空でない明細のみ追加
                    if item_data["product_name"].strip():
                        final_items.append(DeliveryItem(
                            slip_number=item_data["slip_number"],
                            product_code=item_data["product_code"],
                            product_name=item_data["product_name"],
                            quantity=item_data["quantity"],
                            unit_price=item_data["unit_price"],
                            amount=item_data["amount"],
                        ))

                # 編集されたデータでDeliveryNoteを再構築
                edited_delivery_note = DeliveryNote(
                    date=edited_date,
                    company_name=edited_company,
                    slip_number=edited_slip,
                    items=final_items,  # 編集された明細を使用
                    subtotal=edited_subtotal,
                    tax=edited_tax,
                    total=edited_subtotal + edited_tax,
                    payment_received=edited_payment,
                )

                # PreviousBillingを再構築
                from src.sheets_client import PreviousBilling
                edited_previous_billing = PreviousBilling(
                    previous_amount=edited_prev_amount,
                    payment_received=edited_prev_payment,
                    carried_over=edited_prev_amount - edited_prev_payment,
                )

                # PDF再生成
                with st.spinner("🔄 PDFを再生成中..."):
                    invoice_generator = InvoiceGenerator()
                    new_invoice_path = invoice_generator.generate(
                        delivery_note=edited_delivery_note,
                        company_info=company_info,
                        previous_billing=edited_previous_billing,
                    )
                    # 新しいパスをセッション状態に保存
                    st.session_state.current_invoice_path = new_invoice_path
                    st.session_state.current_delivery_note = edited_delivery_note
                    st.session_state.current_previous_billing = edited_previous_billing
                    # PDF再生成時はスプレッドシート保存フラグをリセット
                    st.session_state.spreadsheet_saved = False

                st.success("✅ PDFを再生成しました！スプレッドシートへの書き込みをやり直してください。")
                st.session_state.show_edit_form = False
                st.rerun()

            if cancel:
                st.session_state.show_edit_form = False
                st.rerun()

    # スプレッドシート書き込みボタン
    st.markdown("---")

    # 書き込み済みかチェック
    is_saved = st.session_state.get("spreadsheet_saved", False)

    if not is_saved:
        st.subheader("📊 売上集計表への書き込み")
        st.info("内容を確認後、スプレッドシートに書き込んでください。")

        # 更新内容のプレビュー
        col1, col2 = st.columns(2)
        with col1:
            st.metric("発生（売上）", f"¥{delivery_note.subtotal:,}")
        with col2:
            st.metric("消費税", f"¥{delivery_note.tax:,}")

        if st.button("📝 スプレッドシートに書き込む", type="primary", use_container_width=True):
            with st.spinner("📈 売上集計表に保存中..."):
                try:
                    # Google Sheetsに保存
                    sheets_client = get_sheets_client()
                    sheets_client.save_billing_record(
                        company_name=delivery_note.company_name,
                        previous_billing=previous_billing,
                        delivery_note=delivery_note,
                    )

                    st.session_state.spreadsheet_saved = True
                    st.success(f"✅ **売上集計表** の {delivery_note.company_name} ({year_month}) を更新しました")
                    st.rerun()

                except Exception as e:
                    st.error(f"❌ 書き込みエラー: {e}")
                    import traceback
                    st.code(traceback.format_exc())
    else:
        st.success("✅ スプレッドシートへの書き込みが完了しています")

    # PDFダウンロードボタン（書き込み完了後のみ表示）
    if is_saved:
        st.markdown("---")
        st.subheader("📥 請求書PDFダウンロード")
        with open(invoice_path, "rb") as f:
            st.download_button(
                label="📥 請求書PDFをダウンロード",
                data=f.read(),
                file_name=invoice_path.name,
                mime="application/pdf",
                use_container_width=True,
            )
    else:
        st.markdown("---")
        st.warning("⚠️ スプレッドシートへの書き込みを完了すると、ダウンロードボタンが表示されます")


def get_companies_and_months():
    """会社リストと年月リストを取得"""
    sheets_client = get_sheets_client()
    sheet = sheets_client.client.open_by_key(BILLING_SPREADSHEET_ID).worksheet(
        BILLING_SHEET_NAME
    )

    # 会社リスト（A列）
    col_a = sheet.col_values(1)
    companies = [c for c in col_a[2:] if c]  # ヘッダー除外

    # 年月リスト（1行目）
    row1 = sheet.row_values(1)
    year_months = [ym for ym in row1 if "年" in ym and "月" in ym]

    return companies, year_months


def update_payment(company_name, year_month, payment_amount, add_mode=False):
    """消滅（入金額）を更新または加算

    Args:
        company_name: 会社名
        year_month: 年月
        payment_amount: 入金額
        add_mode: Trueの場合は既存値に加算、Falseの場合は上書き
    """
    try:
        sheets_client = get_sheets_client()
        sheet = sheets_client.client.open_by_key(BILLING_SPREADSHEET_ID).worksheet(
            BILLING_SHEET_NAME
        )

        # 年月の列を検索
        row1_values = sheet.row_values(1)
        month_col_index = None
        for i, cell_value in enumerate(row1_values):
            if year_month in str(cell_value):
                month_col_index = i + 1
                break

        if month_col_index is None:
            st.error(f"❌ 年月 '{year_month}' が見つかりません")
            return False

        # 会社の行を検索（正規化マッチング）
        from src.sheets_client import normalize_company_name
        col_a_values = sheet.col_values(1)
        normalized_search = normalize_company_name(company_name)

        company_row = None
        for i, cell_value in enumerate(col_a_values[2:], start=3):
            normalized_cell = normalize_company_name(str(cell_value))
            if normalized_search in normalized_cell or normalized_cell in normalized_search:
                company_row = i
                break

        if company_row is None:
            st.error(f"❌ 会社 '{company_name}' が見つかりません")
            return False

        # 消滅列（年月列 + 2）
        shoumetsu_col = month_col_index + 2

        # 現在の値を取得
        current_value_str = sheet.cell(company_row, shoumetsu_col).value or ""

        # 既存値をパース
        def parse_amount(value_str: str) -> int:
            if not value_str:
                return 0
            cleaned = str(value_str).replace(',', '').replace(' ', '').replace('¥', '').replace('円', '')
            try:
                return int(float(cleaned))
            except ValueError:
                return 0

        current_value = parse_amount(current_value_str)

        # 新しい値を計算
        if add_mode:
            new_value = current_value + payment_amount
            action = "加算"
        else:
            new_value = payment_amount
            action = "更新"

        # 更新
        sheet.update_cell(company_row, shoumetsu_col, new_value)

        st.success(f"✅ {action}完了: {company_name} の {year_month} 消滅")
        if add_mode:
            st.info(f"前の値: ¥{current_value:,} + ¥{payment_amount:,} = ¥{new_value:,}")
        else:
            st.info(f"前の値: {current_value_str} → 新しい値: ¥{new_value:,}")

        return True

    except Exception as e:
        st.error(f"❌ エラー: {e}")
        import traceback
        st.code(traceback.format_exc())
        return False




# メインUI
st.title("📄 納品書処理システム")

# サイドバーでページ選択
page = st.sidebar.radio(
    "機能を選択",
    ["📤 納品書アップロード", "💰 入金額入力", "⚙️ 自社情報設定"],
)

if page == "📤 納品書アップロード":
    st.header("📤 納品書PDFをアップロード")

    st.markdown("""
    納品書PDFをアップロードすると、以下の処理が自動実行されます：
    1. PDFから情報を抽出（Claude Vision API）
    2. 会社マスターから住所などを取得
    3. 売上集計表から前月の請求情報を取得
    4. 請求書PDFを生成
    5. 売上集計表を更新（発生・消費税を加算）
    """)

    # ファイルアップロード
    uploaded_files = st.file_uploader(
        "納品書PDFを選択（複数可）",
        type=["pdf"],
        accept_multiple_files=True,
    )

    # ファイルが削除された場合、セッション状態をクリア
    if not uploaded_files:
        if "current_invoice_path" in st.session_state:
            # 一時ファイルをクリーンアップ
            if "current_delivery_pdf" in st.session_state:
                old_path = st.session_state.current_delivery_pdf
                if old_path and old_path.exists():
                    old_path.unlink(missing_ok=True)

            # 請求書PDFもクリーンアップ
            if "current_invoice_path" in st.session_state:
                invoice_path = st.session_state.current_invoice_path
                if invoice_path and invoice_path.exists():
                    invoice_path.unlink(missing_ok=True)

            # セッション状態をクリア
            st.session_state.current_invoice_path = None
            st.session_state.current_delivery_note = None
            st.session_state.current_company_info = None
            st.session_state.current_previous_billing = None
            st.session_state.current_year_month = None
            st.session_state.current_delivery_pdf = None
            st.session_state.spreadsheet_saved = False
            st.session_state.show_edit_form = False

    if uploaded_files:
        st.write(f"選択されたファイル: {len(uploaded_files)}件")

        if st.button("🚀 処理を開始", type="primary"):
            progress_bar = st.progress(0)
            status_text = st.empty()

            for i, uploaded_file in enumerate(uploaded_files):
                status_text.text(f"処理中: {uploaded_file.name} ({i+1}/{len(uploaded_files)})")

                st.subheader(f"📄 {uploaded_file.name}")
                success = process_pdf(uploaded_file)

                if not success:
                    st.error(f"❌ {uploaded_file.name} の処理に失敗しました")

                progress_bar.progress((i + 1) / len(uploaded_files))

            status_text.text("✅ 全ての処理が完了しました")

    # PDFプレビューと編集機能を表示（処理完了後）
    show_pdf_preview_and_edit()

elif page == "💰 入金額入力":
    st.header("💰 入金額（消滅）を入力")

    st.markdown("""
    各会社の入金額を手動で入力します。
    入力すると、売上集計表の「消滅」列が更新され、残高が自動計算されます。
    """)

    try:
        # 会社と年月のリストを取得
        with st.spinner("📊 データを読み込み中..."):
            companies, year_months = get_companies_and_months()

        col1, col2, col3 = st.columns(3)

        with col1:
            selected_company = st.selectbox(
                "会社名を選択",
                companies,
                help="売上集計表のA列から選択",
            )

        with col2:
            selected_year_month = st.selectbox(
                "年月を選択",
                year_months,
                help="売上集計表の1行目から選択",
            )

        with col3:
            payment_amount = st.number_input(
                "入金額（円）",
                min_value=0,
                step=1000,
                help="入金された金額を入力",
            )

        # ボタンを2つ並べて配置
        btn_col1, btn_col2 = st.columns(2)

        with btn_col1:
            if st.button("💾 入金額を更新", type="primary", use_container_width=True):
                if selected_company and selected_year_month and payment_amount >= 0:
                    update_payment(selected_company, selected_year_month, payment_amount, add_mode=False)
                else:
                    st.warning("⚠️ すべての項目を入力してください")

        with btn_col2:
            if st.button("➕ 加算", type="secondary", use_container_width=True):
                if selected_company and selected_year_month and payment_amount >= 0:
                    update_payment(selected_company, selected_year_month, payment_amount, add_mode=True)
                else:
                    st.warning("⚠️ すべての項目を入力してください")

        # 現在の状態を常時表示
        st.markdown("---")
        st.subheader("📊 現在の売上集計表")
        sheets_client = get_sheets_client()
        sheet = sheets_client.client.open_by_key(BILLING_SPREADSHEET_ID).worksheet(
            BILLING_SHEET_NAME
        )

        # 全ての行を表示
        data = sheet.get_all_values()

        # DataFrameに変換（列名をユニークにする）
        import pandas as pd

        if data and len(data) > 0:
            headers = data[0]
            # 列名をユニークにする
            unique_headers = []
            for i, header in enumerate(headers):
                if header:
                    unique_headers.append(f"{header}_{i}")
                else:
                    unique_headers.append(f"col_{i}")

            df = pd.DataFrame(data[1:], columns=unique_headers)

            # 列幅設定
            column_config = {}
            pinned_columns = []  # ピン留めする列

            for i, (original_header, unique_header) in enumerate(zip(headers, unique_headers)):
                # 年月が含まれている列は約2倍の幅
                if "年" in str(original_header) and "月" in str(original_header):
                    column_config[unique_header] = st.column_config.TextColumn(
                        original_header,  # 表示名は元の名前
                        width=140,
                    )
                elif original_header == "繰越":
                    # 繰越列は固定
                    column_config[unique_header] = st.column_config.TextColumn(
                        original_header,
                        pinned=True,
                    )
                    pinned_columns.append(unique_header)
                elif "前半合計" in str(original_header) or "後半合計" in str(original_header) or "年間合計" in str(original_header):
                    # 合計列を右側に固定
                    column_config[unique_header] = st.column_config.TextColumn(
                        original_header,
                        pinned="right",
                    )
                    pinned_columns.append(unique_header)
                else:
                    column_config[unique_header] = st.column_config.TextColumn(
                        original_header if original_header else "",
                        width=70,
                    )

            # 表を縦に大きく表示（高さを800pxに）
            st.dataframe(
                df,
                use_container_width=True,
                column_config=column_config,
                height=800,  # 縦の高さを大きく
                hide_index=True,  # 行インデックスを非表示
            )
        else:
            st.info("データがありません")

    except Exception as e:
        st.error(f"❌ エラー: {e}")
        import traceback
        st.code(traceback.format_exc())

elif page == "⚙️ 自社情報設定":
    st.header("⚙️ 自社情報設定")

    st.markdown("""
    請求書PDFに記載される自社情報を設定できます。
    設定は `company_config.json` に保存され、即座に反映されます。
    """)

    # 最新の設定を読み込む
    current_config = load_company_config()

    with st.form("company_info_form"):
        st.subheader("📝 自社情報")

        registration_number = st.text_input(
            "適格請求書発行事業者登録番号",
            value=current_config.get("registration_number", ""),
            help="例: T1234567890123",
        )

        company_name = st.text_input(
            "会社名",
            value=current_config.get("company_name", ""),
            help="例: 株式会社サンプル",
        )

        postal_code = st.text_input(
            "郵便番号",
            value=current_config.get("postal_code", ""),
            help="例: 123-4567",
        )

        address = st.text_input(
            "住所",
            value=current_config.get("address", ""),
            help="例: 東京都千代田区〇〇1-2-3",
        )

        phone = st.text_input(
            "電話番号",
            value=current_config.get("phone", ""),
            help="例: 03-1234-5678",
        )

        bank_info = st.text_input(
            "銀行口座情報",
            value=current_config.get("bank_info", ""),
            help="例: 〇〇銀行 △△支店 普通 1234567",
        )

        submitted = st.form_submit_button("💾 保存", type="primary", use_container_width=True)

        if submitted:
            # 新しい設定を作成
            new_config = {
                "registration_number": registration_number,
                "company_name": company_name,
                "postal_code": postal_code,
                "address": address,
                "phone": phone,
                "bank_info": bank_info,
            }

            # JSONファイルに保存
            if save_company_config(new_config):
                st.success("✅ 自社情報を保存しました")
                st.info("💡 変更は次回のPDF生成から反映されます")
                # 設定を再読み込み
                st.rerun()
            else:
                st.error("❌ 保存に失敗しました")

    # 現在の設定を表示
    st.markdown("---")
    st.subheader("📋 現在の設定")
    st.json(current_config)

# フッター
st.sidebar.markdown("---")
st.sidebar.markdown("### ℹ️ システム情報")
st.sidebar.markdown(f"バージョン: 1.0.0")
st.sidebar.markdown(f"最終更新: {datetime.now().strftime('%Y-%m-%d')}")
