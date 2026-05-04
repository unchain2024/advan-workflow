"""SQLiteデータベース管理モジュール（正規化3テーブル構造）"""
import sqlite3
import json
from datetime import datetime
from pathlib import Path
from typing import Optional
from contextlib import contextmanager

from .config import DATABASE_PATH, DATA_DIR
from .pdf_extractor import DeliveryNote, DeliveryItem
from .purchase_extractor import PurchaseInvoice, PurchaseItem
from .sheets_client import normalize_company_name, match_company_name


class MonthlyItemsDB:
    """月次明細データベース管理クラス"""

    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path or DATABASE_PATH
        self._ensure_db_directory()
        self._init_database()

    def _ensure_db_directory(self):
        """データベースディレクトリが存在することを確認"""
        DATA_DIR.mkdir(exist_ok=True)

    @contextmanager
    def _get_connection(self):
        """データベース接続のコンテキストマネージャー"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _init_database(self):
        """データベーステーブルを初期化（マイグレーション含む）"""
        with self._get_connection() as conn:
            cursor = conn.cursor()

            # 新3テーブルを作成
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS monthly_invoices (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    year_month TEXT NOT NULL,
                    company_name TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(year_month, company_name)
                )
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS delivery_notes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    monthly_invoice_id INTEGER NOT NULL,
                    slip_number TEXT NOT NULL,
                    date TEXT NOT NULL,
                    sales_person TEXT NOT NULL DEFAULT '',
                    subtotal INTEGER NOT NULL,
                    tax INTEGER NOT NULL,
                    total INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY (monthly_invoice_id)
                        REFERENCES monthly_invoices(id) ON DELETE CASCADE
                )
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS delivery_items (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    delivery_note_id INTEGER NOT NULL,
                    product_code TEXT NOT NULL DEFAULT '',
                    product_name TEXT NOT NULL,
                    quantity INTEGER NOT NULL,
                    unit_price INTEGER NOT NULL,
                    amount INTEGER NOT NULL,
                    FOREIGN KEY (delivery_note_id)
                        REFERENCES delivery_notes(id) ON DELETE CASCADE
                )
            """)

            # 冪等性トークン管理テーブル
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS save_requests (
                    request_id TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL
                )
            """)

            # インデックス作成
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_monthly_invoices_ym_company
                ON monthly_invoices(year_month, company_name)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_delivery_notes_invoice_id
                ON delivery_notes(monthly_invoice_id)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_delivery_items_note_id
                ON delivery_items(delivery_note_id)
            """)
            # slip_number ユニークインデックス（同一invoice内で重複防止）
            # 既存の重複データを先にクリーンアップしてからインデックスを作成
            try:
                cursor.execute("""
                    CREATE UNIQUE INDEX IF NOT EXISTS idx_delivery_notes_slip_unique
                    ON delivery_notes(monthly_invoice_id, slip_number)
                """)
            except Exception:
                # 既存データに重複がある場合、古い方を削除してリトライ
                print("    重複slip_numberを検出、クリーンアップ中...")
                cursor.execute("""
                    DELETE FROM delivery_notes
                    WHERE id NOT IN (
                        SELECT MAX(id)
                        FROM delivery_notes
                        GROUP BY monthly_invoice_id, slip_number
                    )
                """)
                cursor.execute("""
                    CREATE UNIQUE INDEX IF NOT EXISTS idx_delivery_notes_slip_unique
                    ON delivery_notes(monthly_invoice_id, slip_number)
                """)

            # --- 仕入れ用テーブル ---
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS purchase_invoices (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    year_month TEXT NOT NULL,
                    company_name TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(year_month, company_name)
                )
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS purchase_notes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    purchase_invoice_id INTEGER NOT NULL,
                    slip_number TEXT NOT NULL,
                    date TEXT NOT NULL,
                    sales_person TEXT NOT NULL DEFAULT '',
                    subtotal INTEGER NOT NULL,
                    tax INTEGER NOT NULL,
                    total INTEGER NOT NULL,
                    is_taxable INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY (purchase_invoice_id)
                        REFERENCES purchase_invoices(id) ON DELETE CASCADE
                )
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS purchase_items (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    purchase_note_id INTEGER NOT NULL,
                    product_code TEXT NOT NULL DEFAULT '',
                    product_name TEXT NOT NULL,
                    quantity INTEGER NOT NULL,
                    unit_price INTEGER NOT NULL,
                    amount INTEGER NOT NULL,
                    FOREIGN KEY (purchase_note_id)
                        REFERENCES purchase_notes(id) ON DELETE CASCADE
                )
            """)

            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_purchase_invoices_ym_company
                ON purchase_invoices(year_month, company_name)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_purchase_notes_invoice_id
                ON purchase_notes(purchase_invoice_id)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_purchase_items_note_id
                ON purchase_items(purchase_note_id)
            """)
            try:
                cursor.execute("""
                    CREATE UNIQUE INDEX IF NOT EXISTS idx_purchase_notes_slip_unique
                    ON purchase_notes(purchase_invoice_id, slip_number)
                """)
            except Exception:
                print("    仕入れ重複slip_numberを検出、クリーンアップ中...")
                cursor.execute("""
                    DELETE FROM purchase_notes
                    WHERE id NOT IN (
                        SELECT MAX(id)
                        FROM purchase_notes
                        GROUP BY purchase_invoice_id, slip_number
                    )
                """)
                cursor.execute("""
                    CREATE UNIQUE INDEX IF NOT EXISTS idx_purchase_notes_slip_unique
                    ON purchase_notes(purchase_invoice_id, slip_number)
                """)

            # --- 売上入金管理用テーブル（消滅・繰越をDBで管理） ---
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS monthly_payments (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    company_name TEXT NOT NULL,
                    year_month TEXT NOT NULL,
                    payment_amount INTEGER NOT NULL DEFAULT 0,
                    opening_balance INTEGER NOT NULL DEFAULT 0,
                    note TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(company_name, year_month)
                )
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_monthly_payments_company_ym
                ON monthly_payments(company_name, year_month)
            """)

            # --- 仕入入金管理テーブル（DB-as-truth Phase 1） ---
            # シート同期の有無に依らず DB に確定値を保持する。
            # add_mode=False（既定）: payment_amount を「上書き」
            # add_mode=True: payment_amount を「加算」
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS purchase_payments (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    company_name TEXT NOT NULL,
                    year_month TEXT NOT NULL,
                    payment_amount INTEGER NOT NULL DEFAULT 0,
                    note TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(company_name, year_month)
                )
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_purchase_payments_company_ym
                ON purchase_payments(company_name, year_month)
            """)

            # 旧テーブルからマイグレーション
            cursor.execute("""
                SELECT name FROM sqlite_master
                WHERE type='table' AND name='monthly_items'
            """)
            if cursor.fetchone():
                self._migrate_from_old_table(cursor)

    def _migrate_from_old_table(self, cursor):
        """旧 monthly_items テーブルからデータを移行"""
        print("旧テーブルからのマイグレーションを開始...")
        cursor.execute("SELECT * FROM monthly_items")
        old_rows = cursor.fetchall()
        current_time = datetime.now().strftime("%Y/%m/%d %H:%M:%S")

        for old_row in old_rows:
            year_month = old_row["year_month"]
            company_name = old_row["company_name"]
            sales_person = old_row["sales_person"] or ""

            # monthly_invoices に挿入
            cursor.execute("""
                INSERT OR IGNORE INTO monthly_invoices
                (year_month, company_name, created_at, updated_at)
                VALUES (?, ?, ?, ?)
            """, (year_month, company_name, old_row["created_at"], old_row["updated_at"]))
            cursor.execute("""
                SELECT id FROM monthly_invoices
                WHERE year_month = ? AND company_name = ?
            """, (year_month, company_name))
            invoice_id = cursor.fetchone()["id"]

            # items_json をパース
            try:
                items_list = json.loads(old_row["items_json"])
            except (json.JSONDecodeError, TypeError):
                items_list = []

            for item_data in items_list:
                slip_number = item_data.get("slip_number", "")
                date = item_data.get("date", "")
                items = item_data.get("items", [])

                # 小計・消費税・合計を計算
                subtotal = sum(it.get("amount", 0) for it in items)
                tax = int(subtotal * 0.1)
                total = subtotal + tax

                # delivery_notes に挿入
                cursor.execute("""
                    INSERT INTO delivery_notes
                    (monthly_invoice_id, slip_number, date, sales_person,
                     subtotal, tax, total, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    invoice_id, slip_number, date, sales_person,
                    subtotal, tax, total, current_time, current_time,
                ))
                note_id = cursor.lastrowid

                # delivery_items に挿入
                for item in items:
                    cursor.execute("""
                        INSERT INTO delivery_items
                        (delivery_note_id, product_code, product_name,
                         quantity, unit_price, amount)
                        VALUES (?, ?, ?, ?, ?, ?)
                    """, (
                        note_id,
                        item.get("product_code", ""),
                        item.get("product_name", ""),
                        item.get("quantity", 0),
                        item.get("unit_price", 0),
                        item.get("amount", 0),
                    ))

        # 旧テーブルを削除
        cursor.execute("DROP TABLE monthly_items")
        print(f"マイグレーション完了: {len(old_rows)}件のレコードを移行")

    def _find_invoice_id(
        self, cursor, year_month: str, company_name: str,
    ) -> Optional[tuple]:
        """正規化した会社名で monthly_invoices レコードを検索

        Returns:
            (id, company_name) tuple、見つからない場合は None
        """
        # まず完全一致を試みる
        cursor.execute("""
            SELECT id, company_name FROM monthly_invoices
            WHERE year_month = ? AND company_name = ?
        """, (year_month, company_name))
        row = cursor.fetchone()
        if row:
            return (row["id"], row["company_name"])

        # 完全一致がなければ、match_company_name で最適マッチ
        cursor.execute("""
            SELECT id, company_name FROM monthly_invoices
            WHERE year_month = ?
        """, (year_month,))
        rows = cursor.fetchall()

        if not rows:
            return None

        db_names = [row["company_name"] for row in rows]
        matched = match_company_name(company_name, db_names)

        if matched:
            for row in rows:
                if row["company_name"] == matched:
                    print(f"    正規化マッチ: '{company_name}' → DB内 '{row['company_name']}'")
                    return (row["id"], row["company_name"])

        return None

    def find_existing_slip_numbers(
        self,
        company_name: str,
        year_month: str,
        slip_numbers: list[str],
    ) -> list[dict]:
        """指定したslip_numbersのうち、既にDBに存在するものを返す

        Returns:
            list[dict]: [{slip_number, date, subtotal, tax, total, sales_person, saved_at}, ...]
        """
        if not slip_numbers:
            return []

        with self._get_connection() as conn:
            cursor = conn.cursor()
            result = self._find_invoice_id(cursor, year_month, company_name)
            if not result:
                return []

            invoice_id, _ = result
            placeholders = ",".join("?" for _ in slip_numbers)
            cursor.execute(f"""
                SELECT slip_number, date, subtotal, tax, total,
                       sales_person, updated_at
                FROM delivery_notes
                WHERE monthly_invoice_id = ?
                  AND slip_number IN ({placeholders})
                ORDER BY slip_number
            """, [invoice_id] + slip_numbers)

            return [
                {
                    "slip_number": row["slip_number"],
                    "date": row["date"],
                    "subtotal": row["subtotal"],
                    "tax": row["tax"],
                    "total": row["total"],
                    "sales_person": row["sales_person"],
                    "saved_at": row["updated_at"],
                }
                for row in cursor.fetchall()
            ]

    def check_request_id(self, request_id: str) -> bool:
        """冪等性トークンが既に処理済みかチェック

        Returns:
            True: 既に処理済み（スキップすべき）
            False: 未処理（実行すべき）
        """
        if not request_id:
            return False
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT 1 FROM save_requests WHERE request_id = ?",
                (request_id,),
            )
            return cursor.fetchone() is not None

    def record_request_id(self, request_id: str, cursor=None):
        """冪等性トークンを記録"""
        if not request_id:
            return
        current_time = datetime.now().strftime("%Y/%m/%d %H:%M:%S")
        if cursor:
            cursor.execute(
                "INSERT OR IGNORE INTO save_requests (request_id, created_at) VALUES (?, ?)",
                (request_id, current_time),
            )
        else:
            with self._get_connection() as conn:
                conn.cursor().execute(
                    "INSERT OR IGNORE INTO save_requests (request_id, created_at) VALUES (?, ?)",
                    (request_id, current_time),
                )

    def save_monthly_items(
        self,
        company_name: str,
        year_month: str,
        delivery_note: DeliveryNote,
        sales_person: str = "",
    ):
        """月次明細DBに納品書データを保存（月+会社キーで集約）

        monthly_invoices をUPSERT → delivery_notes をUPSERT（slip_number重複時はUPDATE）
        → delivery_items を再作成
        """
        sales_person_clean = "".join(sales_person.split())
        current_time = datetime.now().strftime("%Y/%m/%d %H:%M:%S")

        with self._get_connection() as conn:
            cursor = conn.cursor()

            # monthly_invoices を検索または作成
            result = self._find_invoice_id(cursor, year_month, company_name)

            if result:
                invoice_id, db_company_name = result
                # 会社名がシート正規名と異なる場合は更新
                if db_company_name != company_name:
                    cursor.execute("""
                        UPDATE monthly_invoices SET company_name = ?, updated_at = ? WHERE id = ?
                    """, (company_name, current_time, invoice_id))
                    print(f"    月次明細DB会社名更新: '{db_company_name}' → '{company_name}' (ID {invoice_id})")
                else:
                    cursor.execute("""
                        UPDATE monthly_invoices SET updated_at = ? WHERE id = ?
                    """, (current_time, invoice_id))
                print(f"    月次明細DB更新: {company_name} ({year_month}) - ID {invoice_id}")
            else:
                cursor.execute("""
                    INSERT INTO monthly_invoices
                    (year_month, company_name, created_at, updated_at)
                    VALUES (?, ?, ?, ?)
                """, (year_month, company_name, current_time, current_time))
                invoice_id = cursor.lastrowid
                print(f"    月次明細DB新規作成: {company_name} ({year_month})")

            # delivery_notes をUPSERT（slip_number重複時はUPDATE）
            slip = delivery_note.slip_number or ""
            cursor.execute("""
                SELECT id FROM delivery_notes
                WHERE monthly_invoice_id = ? AND slip_number = ?
            """, (invoice_id, slip))
            existing_note = cursor.fetchone()

            if existing_note:
                note_id = existing_note["id"]
                cursor.execute("""
                    UPDATE delivery_notes
                    SET date = ?, sales_person = ?,
                        subtotal = ?, tax = ?, total = ?, updated_at = ?
                    WHERE id = ?
                """, (
                    delivery_note.date or "",
                    sales_person_clean,
                    delivery_note.subtotal,
                    delivery_note.tax,
                    delivery_note.total,
                    current_time,
                    note_id,
                ))
                # 既存items削除して再作成
                cursor.execute(
                    "DELETE FROM delivery_items WHERE delivery_note_id = ?",
                    (note_id,),
                )
                print(f"    月次明細DB: slip_number '{slip}' を上書き更新")
            else:
                cursor.execute("""
                    INSERT INTO delivery_notes
                    (monthly_invoice_id, slip_number, date, sales_person,
                     subtotal, tax, total, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    invoice_id,
                    slip,
                    delivery_note.date or "",
                    sales_person_clean,
                    delivery_note.subtotal,
                    delivery_note.tax,
                    delivery_note.total,
                    current_time,
                    current_time,
                ))
                note_id = cursor.lastrowid

            # delivery_items に挿入
            for item in delivery_note.items:
                cursor.execute("""
                    INSERT INTO delivery_items
                    (delivery_note_id, product_code, product_name,
                     quantity, unit_price, amount)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (
                    note_id,
                    item.product_code or "",
                    item.product_name,
                    item.quantity,
                    item.unit_price,
                    item.amount,
                ))

    def save_monthly_items_batch(
        self,
        company_name: str,
        year_month: str,
        delivery_notes: list[DeliveryNote],
        sales_person: str = "",
        request_id: str = "",
    ):
        """複数の納品書を単一トランザクションでDB保存

        全件成功するか全件ロールバック。冪等性トークンも同一トランザクション内で記録。
        """
        sales_person_clean = "".join(sales_person.split())
        current_time = datetime.now().strftime("%Y/%m/%d %H:%M:%S")

        with self._get_connection() as conn:
            cursor = conn.cursor()

            # 冪等性チェック（トランザクション内で再チェック）
            if request_id:
                cursor.execute(
                    "SELECT 1 FROM save_requests WHERE request_id = ?",
                    (request_id,),
                )
                if cursor.fetchone():
                    print(f"    冪等性トークン '{request_id}' は処理済み。スキップ。")
                    return 0

            # monthly_invoices を検索または作成
            result = self._find_invoice_id(cursor, year_month, company_name)

            if result:
                invoice_id, db_company_name = result
                if db_company_name != company_name:
                    cursor.execute("""
                        UPDATE monthly_invoices SET company_name = ?, updated_at = ? WHERE id = ?
                    """, (company_name, current_time, invoice_id))
                else:
                    cursor.execute("""
                        UPDATE monthly_invoices SET updated_at = ? WHERE id = ?
                    """, (current_time, invoice_id))
            else:
                cursor.execute("""
                    INSERT INTO monthly_invoices
                    (year_month, company_name, created_at, updated_at)
                    VALUES (?, ?, ?, ?)
                """, (year_month, company_name, current_time, current_time))
                invoice_id = cursor.lastrowid

            saved_count = 0
            for delivery_note in delivery_notes:
                slip = delivery_note.slip_number or ""
                cursor.execute("""
                    SELECT id FROM delivery_notes
                    WHERE monthly_invoice_id = ? AND slip_number = ?
                """, (invoice_id, slip))
                existing_note = cursor.fetchone()

                if existing_note:
                    note_id = existing_note["id"]
                    cursor.execute("""
                        UPDATE delivery_notes
                        SET date = ?, sales_person = ?,
                            subtotal = ?, tax = ?, total = ?, updated_at = ?
                        WHERE id = ?
                    """, (
                        delivery_note.date or "",
                        sales_person_clean,
                        delivery_note.subtotal,
                        delivery_note.tax,
                        delivery_note.total,
                        current_time,
                        note_id,
                    ))
                    cursor.execute(
                        "DELETE FROM delivery_items WHERE delivery_note_id = ?",
                        (note_id,),
                    )
                else:
                    cursor.execute("""
                        INSERT INTO delivery_notes
                        (monthly_invoice_id, slip_number, date, sales_person,
                         subtotal, tax, total, created_at, updated_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        invoice_id, slip,
                        delivery_note.date or "",
                        sales_person_clean,
                        delivery_note.subtotal,
                        delivery_note.tax,
                        delivery_note.total,
                        current_time, current_time,
                    ))
                    note_id = cursor.lastrowid

                for item in delivery_note.items:
                    cursor.execute("""
                        INSERT INTO delivery_items
                        (delivery_note_id, product_code, product_name,
                         quantity, unit_price, amount)
                        VALUES (?, ?, ?, ?, ?, ?)
                    """, (
                        note_id,
                        item.product_code or "",
                        item.product_name,
                        item.quantity,
                        item.unit_price,
                        item.amount,
                    ))
                saved_count += 1

            # 冪等性トークンを記録（同一トランザクション内）
            if request_id:
                cursor.execute(
                    "INSERT OR IGNORE INTO save_requests (request_id, created_at) VALUES (?, ?)",
                    (request_id, current_time),
                )

            print(f"    月次明細DB一括保存: {company_name} ({year_month}) - {saved_count}件")
            return saved_count

    def delete_monthly_items(
        self,
        company_name: str,
        year_month: str,
    ):
        """指定した会社・年月の月次明細レコードを削除（CASCADE削除）"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            result = self._find_invoice_id(cursor, year_month, company_name)
            if result:
                invoice_id, _ = result
                # CASCADE で delivery_notes, delivery_items も自動削除
                cursor.execute(
                    "DELETE FROM monthly_invoices WHERE id = ?", (invoice_id,)
                )
                print(f"    月次明細DB削除: {company_name} ({year_month})")

    def get_monthly_items(
        self,
        company_name: str,
        year_month: str,
        sales_person: str = "",
    ) -> list[DeliveryNote]:
        """月次明細DBから指定した会社・年月のデータを取得

        3テーブルJOINで取得し、DeliveryNote のリストとして返す。
        sales_person が指定された場合、その担当者の納品書のみ返す。
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()

            result = self._find_invoice_id(cursor, year_month, company_name)
            if not result:
                print(f"    月次明細DB: レコードが見つかりません ({company_name}, {year_month})")
                return []

            invoice_id, _ = result

            # delivery_notes を取得（担当者フィルター対応）
            if sales_person:
                cursor.execute("""
                    SELECT id, slip_number, date, sales_person,
                           subtotal, tax, total
                    FROM delivery_notes
                    WHERE monthly_invoice_id = ? AND sales_person = ?
                    ORDER BY id
                """, (invoice_id, sales_person))
            else:
                cursor.execute("""
                    SELECT id, slip_number, date, sales_person,
                           subtotal, tax, total
                    FROM delivery_notes
                    WHERE monthly_invoice_id = ?
                    ORDER BY id
                """, (invoice_id,))
            note_rows = cursor.fetchall()

            delivery_notes = []
            for note_row in note_rows:
                # delivery_items を取得
                cursor.execute("""
                    SELECT product_code, product_name, quantity,
                           unit_price, amount
                    FROM delivery_items
                    WHERE delivery_note_id = ?
                    ORDER BY id
                """, (note_row["id"],))
                item_rows = cursor.fetchall()

                items = [
                    DeliveryItem(
                        slip_number=note_row["slip_number"],
                        product_code=row["product_code"],
                        product_name=row["product_name"],
                        quantity=row["quantity"],
                        unit_price=row["unit_price"],
                        amount=row["amount"],
                    )
                    for row in item_rows
                ]

                dn = DeliveryNote(
                    slip_number=note_row["slip_number"],
                    date=note_row["date"],
                    company_name=company_name,
                    items=items,
                    subtotal=note_row["subtotal"],
                    tax=note_row["tax"],
                    total=note_row["total"],
                )
                delivery_notes.append(dn)

            print(f"    月次明細DB取得: {company_name} ({year_month}) - {len(delivery_notes)}件の納品書")
            return delivery_notes

    def update_monthly_item(
        self,
        company_name: str,
        year_month: str,
        delivery_note: DeliveryNote,
        sales_person: str = "",
    ):
        """月次明細DBの特定の納品書データを更新

        slip_numberでdelivery_notesを特定し、UPDATE + delivery_items再作成。
        差分計算が不要（単純なUPDATE/DELETE+INSERT）。
        """
        sales_person_clean = "".join(sales_person.split())
        current_time = datetime.now().strftime("%Y/%m/%d %H:%M:%S")

        with self._get_connection() as conn:
            cursor = conn.cursor()

            result = self._find_invoice_id(cursor, year_month, company_name)
            if not result:
                print(f"    月次明細DB: 更新対象が見つかりません ({company_name}, {year_month})")
                # 見つからない場合は新規保存
                self.save_monthly_items(
                    company_name, year_month, delivery_note, sales_person
                )
                return

            invoice_id, _ = result

            # slip_number で delivery_notes を検索
            cursor.execute("""
                SELECT id, sales_person FROM delivery_notes
                WHERE monthly_invoice_id = ? AND slip_number = ?
            """, (invoice_id, delivery_note.slip_number))
            note_row = cursor.fetchone()

            if note_row:
                note_id = note_row["id"]
                # sales_person が空の場合は既存値を保持（上書き防止）
                effective_sales_person = (
                    sales_person_clean if sales_person_clean
                    else note_row["sales_person"]
                )
                # delivery_notes を更新
                cursor.execute("""
                    UPDATE delivery_notes
                    SET date = ?, sales_person = ?,
                        subtotal = ?, tax = ?, total = ?,
                        updated_at = ?
                    WHERE id = ?
                """, (
                    delivery_note.date or "",
                    effective_sales_person,
                    delivery_note.subtotal,
                    delivery_note.tax,
                    delivery_note.total,
                    current_time,
                    note_id,
                ))

                # delivery_items を全削除して再挿入
                cursor.execute(
                    "DELETE FROM delivery_items WHERE delivery_note_id = ?",
                    (note_id,),
                )
                print(f"    月次明細DB: slip_number '{delivery_note.slip_number}' を更新")
            else:
                # slip_number が見つからない場合は新規追加
                cursor.execute("""
                    INSERT INTO delivery_notes
                    (monthly_invoice_id, slip_number, date, sales_person,
                     subtotal, tax, total, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    invoice_id,
                    delivery_note.slip_number or "",
                    delivery_note.date or "",
                    sales_person_clean,
                    delivery_note.subtotal,
                    delivery_note.tax,
                    delivery_note.total,
                    current_time,
                    current_time,
                ))
                note_id = cursor.lastrowid
                print(f"    月次明細DB: slip_number '{delivery_note.slip_number}' が見つかりません、追加しました")

            # delivery_items を挿入
            for item in delivery_note.items:
                cursor.execute("""
                    INSERT INTO delivery_items
                    (delivery_note_id, product_code, product_name,
                     quantity, unit_price, amount)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (
                    note_id,
                    item.product_code or "",
                    item.product_name,
                    item.quantity,
                    item.unit_price,
                    item.amount,
                ))

            # monthly_invoices の updated_at を更新
            cursor.execute("""
                UPDATE monthly_invoices SET updated_at = ? WHERE id = ?
            """, (current_time, invoice_id))

            print(f"    月次明細DB更新完了: {company_name} ({year_month})")

    def get_all_purchase_monthly_totals(self) -> list[dict]:
        """DB内の全 purchase_invoices の各仕入先・月の合計を課税/非課税別に返す

        Returns:
            list[dict]: [{company_name, year_month, taxable_subtotal, taxable_tax,
                          nontaxable_subtotal, nontaxable_tax}, ...]
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT pi.company_name, pi.year_month,
                       COALESCE(SUM(CASE WHEN pn.is_taxable = 1 THEN pn.subtotal ELSE 0 END), 0) AS taxable_subtotal,
                       COALESCE(SUM(CASE WHEN pn.is_taxable = 1 THEN pn.tax ELSE 0 END), 0) AS taxable_tax,
                       COALESCE(SUM(CASE WHEN pn.is_taxable = 0 THEN pn.subtotal ELSE 0 END), 0) AS nontaxable_subtotal,
                       COALESCE(SUM(CASE WHEN pn.is_taxable = 0 THEN pn.tax ELSE 0 END), 0) AS nontaxable_tax
                FROM purchase_invoices pi
                JOIN purchase_notes pn ON pn.purchase_invoice_id = pi.id
                GROUP BY pi.id
                ORDER BY pi.year_month, pi.company_name
            """)
            return [
                {
                    "company_name": row["company_name"],
                    "year_month": row["year_month"],
                    "taxable_subtotal": row["taxable_subtotal"] or 0,
                    "taxable_tax": row["taxable_tax"] or 0,
                    "nontaxable_subtotal": row["nontaxable_subtotal"] or 0,
                    "nontaxable_tax": row["nontaxable_tax"] or 0,
                }
                for row in cursor.fetchall()
            ]

    def get_all_monthly_totals(self) -> list[dict]:
        """DB内の全 monthly_invoices の各会社・月の合計 subtotal/tax を返す

        Returns:
            list[dict]: [{company_name, year_month, subtotal, tax}, ...]
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT mi.company_name, mi.year_month,
                       SUM(dn.subtotal) as total_subtotal,
                       SUM(dn.tax) as total_tax
                FROM monthly_invoices mi
                JOIN delivery_notes dn ON dn.monthly_invoice_id = mi.id
                GROUP BY mi.id
                ORDER BY mi.year_month, mi.company_name
            """)
            return [
                {
                    "company_name": row["company_name"],
                    "year_month": row["year_month"],
                    "subtotal": row["total_subtotal"],
                    "tax": row["total_tax"],
                }
                for row in cursor.fetchall()
            ]

    def get_distinct_year_months(self) -> list[str]:
        """DB内の全ての年月を取得

        Returns:
            list[str]: ["2025年1月", "2025年2月", ...]
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT DISTINCT year_month
                FROM monthly_invoices
                ORDER BY year_month
            """)
            return [row["year_month"] for row in cursor.fetchall()]

    def update_delivery_note_amounts(
        self, delivery_note_id: int, subtotal: int, tax: int, total: int
    ):
        """指定IDの delivery_note の金額を更新

        Args:
            delivery_note_id: 更新対象のID
            subtotal: 小計
            tax: 消費税
            total: 合計
        """
        current_time = datetime.now().strftime("%Y/%m/%d %H:%M:%S")
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE delivery_notes
                SET subtotal = ?, tax = ?, total = ?, updated_at = ?
                WHERE id = ?
            """, (subtotal, tax, total, current_time, delivery_note_id))

    def get_delivery_notes_with_ids(
        self, company_name: str, year_month: str
    ) -> list[dict]:
        """指定した会社・年月の納品書一覧をID付きで返す（編集画面用）

        Args:
            company_name: 会社名
            year_month: 年月（例: "2025年1月"）

        Returns:
            list[dict]: [{id, slip_number, date, subtotal, tax, total}, ...]
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            result = self._find_invoice_id(cursor, year_month, company_name)
            if not result:
                return []

            invoice_id, _ = result
            cursor.execute("""
                SELECT id, slip_number, date, subtotal, tax, total
                FROM delivery_notes
                WHERE monthly_invoice_id = ?
                ORDER BY id
            """, (invoice_id,))
            return [
                {
                    "id": row["id"],
                    "slip_number": row["slip_number"],
                    "date": row["date"],
                    "subtotal": row["subtotal"],
                    "tax": row["tax"],
                    "total": row["total"],
                }
                for row in cursor.fetchall()
            ]

    def get_distinct_companies(self) -> list[str]:
        """月次明細DBに保存されているすべての会社名を取得"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT DISTINCT company_name
                FROM monthly_invoices
                ORDER BY company_name
            """)
            return [row["company_name"] for row in cursor.fetchall()]

    def get_distinct_sales_persons(self, company_name: str = "") -> list[str]:
        """月次明細DBに保存されている担当者名を取得

        Args:
            company_name: 指定すると、その会社に紐づく担当者のみ返す
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            if company_name:
                cursor.execute("""
                    SELECT DISTINCT dn.sales_person
                    FROM delivery_notes dn
                    JOIN monthly_invoices mi ON mi.id = dn.monthly_invoice_id
                    WHERE dn.sales_person != '' AND mi.company_name = ?
                    ORDER BY dn.sales_person
                """, (company_name,))
            else:
                cursor.execute("""
                    SELECT DISTINCT sales_person
                    FROM delivery_notes
                    WHERE sales_person != ''
                    ORDER BY sales_person
                """)
            return [row["sales_person"] for row in cursor.fetchall()]

    # ========================================
    # 仕入れ用メソッド
    # ========================================

    def _find_purchase_invoice_id(
        self, cursor, year_month: str, company_name: str,
    ) -> Optional[tuple]:
        """正規化した会社名で purchase_invoices レコードを検索

        Returns:
            (id, company_name) tuple、見つからない場合は None
        """
        cursor.execute("""
            SELECT id, company_name FROM purchase_invoices
            WHERE year_month = ? AND company_name = ?
        """, (year_month, company_name))
        row = cursor.fetchone()
        if row:
            return (row["id"], row["company_name"])

        cursor.execute("""
            SELECT id, company_name FROM purchase_invoices
            WHERE year_month = ?
        """, (year_month,))
        rows = cursor.fetchall()

        if not rows:
            return None

        db_names = [row["company_name"] for row in rows]
        matched = match_company_name(company_name, db_names)

        if matched:
            for row in rows:
                if row["company_name"] == matched:
                    print(f"    仕入れ正規化マッチ: '{company_name}' → DB内 '{row['company_name']}'")
                    return (row["id"], row["company_name"])

        return None

    def find_existing_purchase_slip_numbers(
        self,
        company_name: str,
        year_month: str,
        slip_numbers: list[str],
    ) -> list[dict]:
        """指定したslip_numbersのうち、仕入れDBに既に存在するものを返す"""
        if not slip_numbers:
            return []

        with self._get_connection() as conn:
            cursor = conn.cursor()
            result = self._find_purchase_invoice_id(cursor, year_month, company_name)
            if not result:
                return []

            invoice_id, _ = result
            placeholders = ",".join("?" for _ in slip_numbers)
            cursor.execute(f"""
                SELECT slip_number, date, subtotal, tax, total,
                       sales_person, updated_at
                FROM purchase_notes
                WHERE purchase_invoice_id = ?
                  AND slip_number IN ({placeholders})
                ORDER BY slip_number
            """, [invoice_id] + slip_numbers)

            return [
                {
                    "slip_number": row["slip_number"],
                    "date": row["date"],
                    "subtotal": row["subtotal"],
                    "tax": row["tax"],
                    "total": row["total"],
                    "sales_person": row["sales_person"],
                    "saved_at": row["updated_at"],
                }
                for row in cursor.fetchall()
            ]

    def save_purchase_batch(
        self,
        company_name: str,
        year_month: str,
        purchase_invoices: list[PurchaseInvoice],
        sales_person: str = "",
        request_id: str = "",
    ):
        """複数の仕入れ納品書を単一トランザクションでDB保存"""
        sales_person_clean = "".join(sales_person.split())
        current_time = datetime.now().strftime("%Y/%m/%d %H:%M:%S")

        with self._get_connection() as conn:
            cursor = conn.cursor()

            if request_id:
                cursor.execute(
                    "SELECT 1 FROM save_requests WHERE request_id = ?",
                    (request_id,),
                )
                if cursor.fetchone():
                    print(f"    冪等性トークン '{request_id}' は処理済み。スキップ。")
                    return 0

            result = self._find_purchase_invoice_id(cursor, year_month, company_name)

            if result:
                invoice_id, db_company_name = result
                if db_company_name != company_name:
                    cursor.execute("""
                        UPDATE purchase_invoices SET company_name = ?, updated_at = ? WHERE id = ?
                    """, (company_name, current_time, invoice_id))
                else:
                    cursor.execute("""
                        UPDATE purchase_invoices SET updated_at = ? WHERE id = ?
                    """, (current_time, invoice_id))
            else:
                cursor.execute("""
                    INSERT INTO purchase_invoices
                    (year_month, company_name, created_at, updated_at)
                    VALUES (?, ?, ?, ?)
                """, (year_month, company_name, current_time, current_time))
                invoice_id = cursor.lastrowid

            saved_count = 0
            for pi in purchase_invoices:
                slip = pi.slip_number or ""
                cursor.execute("""
                    SELECT id FROM purchase_notes
                    WHERE purchase_invoice_id = ? AND slip_number = ?
                """, (invoice_id, slip))
                existing_note = cursor.fetchone()

                if existing_note:
                    note_id = existing_note["id"]
                    cursor.execute("""
                        UPDATE purchase_notes
                        SET date = ?, sales_person = ?,
                            subtotal = ?, tax = ?, total = ?,
                            is_taxable = ?, updated_at = ?
                        WHERE id = ?
                    """, (
                        pi.date or "",
                        sales_person_clean,
                        pi.subtotal,
                        pi.tax,
                        pi.total,
                        1 if pi.is_taxable else 0,
                        current_time,
                        note_id,
                    ))
                    cursor.execute(
                        "DELETE FROM purchase_items WHERE purchase_note_id = ?",
                        (note_id,),
                    )
                else:
                    cursor.execute("""
                        INSERT INTO purchase_notes
                        (purchase_invoice_id, slip_number, date, sales_person,
                         subtotal, tax, total, is_taxable, created_at, updated_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        invoice_id, slip,
                        pi.date or "",
                        sales_person_clean,
                        pi.subtotal,
                        pi.tax,
                        pi.total,
                        1 if pi.is_taxable else 0,
                        current_time, current_time,
                    ))
                    note_id = cursor.lastrowid

                for item in pi.items:
                    cursor.execute("""
                        INSERT INTO purchase_items
                        (purchase_note_id, product_code, product_name,
                         quantity, unit_price, amount)
                        VALUES (?, ?, ?, ?, ?, ?)
                    """, (
                        note_id,
                        item.product_code or "",
                        item.product_name,
                        item.quantity,
                        item.unit_price,
                        item.amount,
                    ))
                saved_count += 1

            if request_id:
                cursor.execute(
                    "INSERT OR IGNORE INTO save_requests (request_id, created_at) VALUES (?, ?)",
                    (request_id, current_time),
                )

            print(f"    仕入れDB一括保存: {company_name} ({year_month}) - {saved_count}件")
            return saved_count

    def get_purchase_items(
        self,
        company_name: str,
        year_month: str,
        sales_person: str = "",
    ) -> list[dict]:
        """仕入れDBから指定した会社・年月のデータを取得（担当者フィルター対応）"""
        with self._get_connection() as conn:
            cursor = conn.cursor()

            result = self._find_purchase_invoice_id(cursor, year_month, company_name)
            if not result:
                return []

            invoice_id, _ = result

            if sales_person:
                cursor.execute("""
                    SELECT id, slip_number, date, sales_person,
                           subtotal, tax, total, is_taxable
                    FROM purchase_notes
                    WHERE purchase_invoice_id = ? AND sales_person = ?
                    ORDER BY id
                """, (invoice_id, sales_person))
            else:
                cursor.execute("""
                    SELECT id, slip_number, date, sales_person,
                           subtotal, tax, total, is_taxable
                    FROM purchase_notes
                    WHERE purchase_invoice_id = ?
                    ORDER BY id
                """, (invoice_id,))
            note_rows = cursor.fetchall()

            results = []
            for note_row in note_rows:
                cursor.execute("""
                    SELECT product_code, product_name, quantity,
                           unit_price, amount
                    FROM purchase_items
                    WHERE purchase_note_id = ?
                    ORDER BY id
                """, (note_row["id"],))
                item_rows = cursor.fetchall()

                items = [
                    {
                        "product_code": row["product_code"],
                        "product_name": row["product_name"],
                        "quantity": row["quantity"],
                        "unit_price": row["unit_price"],
                        "amount": row["amount"],
                    }
                    for row in item_rows
                ]

                results.append({
                    "id": note_row["id"],
                    "slip_number": note_row["slip_number"],
                    "date": note_row["date"],
                    "sales_person": note_row["sales_person"],
                    "subtotal": note_row["subtotal"],
                    "tax": note_row["tax"],
                    "total": note_row["total"],
                    "is_taxable": bool(note_row["is_taxable"]),
                    "items": items,
                })

            return results

    def get_purchase_companies(self) -> list[str]:
        """仕入れDBに保存されているすべての会社名を取得"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT DISTINCT company_name
                FROM purchase_invoices
                ORDER BY company_name
            """)
            return [row["company_name"] for row in cursor.fetchall()]

    def get_purchase_sales_persons(self, company_name: str = "") -> list[str]:
        """仕入れDBに保存されている担当者名を取得"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            if company_name:
                cursor.execute("""
                    SELECT DISTINCT pn.sales_person
                    FROM purchase_notes pn
                    JOIN purchase_invoices pi ON pi.id = pn.purchase_invoice_id
                    WHERE pn.sales_person != '' AND pi.company_name = ?
                    ORDER BY pn.sales_person
                """, (company_name,))
            else:
                cursor.execute("""
                    SELECT DISTINCT sales_person
                    FROM purchase_notes
                    WHERE sales_person != ''
                    ORDER BY sales_person
                """)
            return [row["sales_person"] for row in cursor.fetchall()]

    def get_purchase_notes_with_ids(
        self, company_name: str, year_month: str
    ) -> list[dict]:
        """仕入れDBの納品書一覧をID付きで返す（編集画面用）"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            result = self._find_purchase_invoice_id(cursor, year_month, company_name)
            if not result:
                return []

            invoice_id, _ = result
            cursor.execute("""
                SELECT id, slip_number, date, subtotal, tax, total, is_taxable
                FROM purchase_notes
                WHERE purchase_invoice_id = ?
                ORDER BY id
            """, (invoice_id,))
            return [
                {
                    "id": row["id"],
                    "slip_number": row["slip_number"],
                    "date": row["date"],
                    "subtotal": row["subtotal"],
                    "tax": row["tax"],
                    "total": row["total"],
                    "is_taxable": bool(row["is_taxable"]),
                }
                for row in cursor.fetchall()
            ]

    def update_purchase_note_amounts(
        self, note_id: int, subtotal: int, tax: int, total: int
    ):
        """指定IDの purchase_note の金額を更新"""
        current_time = datetime.now().strftime("%Y/%m/%d %H:%M:%S")
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE purchase_notes
                SET subtotal = ?, tax = ?, total = ?, updated_at = ?
                WHERE id = ?
            """, (subtotal, tax, total, current_time, note_id))

    # --- 売上入金管理（消滅・繰越） ---

    def upsert_payment(
        self,
        company_name: str,
        year_month: str,
        payment_amount: int = 0,
        opening_balance: Optional[int] = None,
        note: Optional[str] = None,
    ) -> dict:
        """消滅（入金）を登録または更新

        opening_balance/note は None 指定時は既存値を保持。新規行作成時は 0/"" が入る。
        """
        current_time = datetime.now().strftime("%Y/%m/%d %H:%M:%S")
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT id, opening_balance, note FROM monthly_payments
                WHERE company_name = ? AND year_month = ?
            """, (company_name, year_month))
            row = cursor.fetchone()
            if row:
                new_opening = row["opening_balance"] if opening_balance is None else opening_balance
                new_note = row["note"] if note is None else note
                cursor.execute("""
                    UPDATE monthly_payments
                    SET payment_amount = ?, opening_balance = ?, note = ?, updated_at = ?
                    WHERE id = ?
                """, (payment_amount, new_opening, new_note, current_time, row["id"]))
                pid = row["id"]
            else:
                cursor.execute("""
                    INSERT INTO monthly_payments
                    (company_name, year_month, payment_amount, opening_balance, note, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (
                    company_name, year_month, payment_amount,
                    opening_balance or 0, note or "", current_time, current_time,
                ))
                pid = cursor.lastrowid
            return {
                "id": pid,
                "company_name": company_name,
                "year_month": year_month,
                "payment_amount": payment_amount,
            }

    def get_payment(self, company_name: str, year_month: str) -> Optional[dict]:
        """指定会社・年月の消滅エントリを取得"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM monthly_payments
                WHERE company_name = ? AND year_month = ?
            """, (company_name, year_month))
            row = cursor.fetchone()
            if not row:
                return None
            return {
                "id": row["id"],
                "company_name": row["company_name"],
                "year_month": row["year_month"],
                "payment_amount": row["payment_amount"],
                "opening_balance": row["opening_balance"],
                "note": row["note"],
            }

    def get_monthly_amounts(self, company_name: str, year_month: str) -> dict:
        """指定会社・年月の発生(subtotal)・消費税合計を delivery_notes から集計"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT COALESCE(SUM(dn.subtotal), 0) AS subtotal,
                       COALESCE(SUM(dn.tax), 0) AS tax,
                       COUNT(dn.id) AS notes_count
                FROM delivery_notes dn
                JOIN monthly_invoices mi ON dn.monthly_invoice_id = mi.id
                WHERE mi.company_name = ? AND mi.year_month = ?
            """, (company_name, year_month))
            row = cursor.fetchone()
            return {
                "subtotal": row["subtotal"] or 0,
                "tax": row["tax"] or 0,
                "notes_count": row["notes_count"] or 0,
            }

    def get_purchase_amounts(self, company_name: str, year_month: str) -> dict:
        """指定仕入先・年月の発生(subtotal)・消費税合計を purchase_notes から集計

        is_taxable=True/False ごとに分けて集計する（仕入シートの 2-row セクション対応）。
        sync_purchase_sheet で課税/非課税別の sheet 行に書き分けるために使用。
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT
                    COALESCE(SUM(CASE WHEN pn.is_taxable = 1 THEN pn.subtotal ELSE 0 END), 0) AS taxable_subtotal,
                    COALESCE(SUM(CASE WHEN pn.is_taxable = 1 THEN pn.tax ELSE 0 END), 0) AS taxable_tax,
                    COALESCE(SUM(CASE WHEN pn.is_taxable = 0 THEN pn.subtotal ELSE 0 END), 0) AS nontaxable_subtotal,
                    COALESCE(SUM(CASE WHEN pn.is_taxable = 0 THEN pn.tax ELSE 0 END), 0) AS nontaxable_tax,
                    COUNT(pn.id) AS notes_count
                FROM purchase_notes pn
                JOIN purchase_invoices pi ON pn.purchase_invoice_id = pi.id
                WHERE pi.company_name = ? AND pi.year_month = ?
            """, (company_name, year_month))
            row = cursor.fetchone()
            return {
                "taxable_subtotal": row["taxable_subtotal"] or 0,
                "taxable_tax": row["taxable_tax"] or 0,
                "nontaxable_subtotal": row["nontaxable_subtotal"] or 0,
                "nontaxable_tax": row["nontaxable_tax"] or 0,
                "notes_count": row["notes_count"] or 0,
            }

    def compute_ledger(self, company_name: str, year_month: str) -> dict:
        """指定会社・年月の台帳（発生・消費税・消滅・繰越・残高）をDBから計算

        Returns:
            {
              "year_month": str,
              "previous_balance": int,  # 前月残高（前月の carried_over）
              "opening_balance": int,   # 当月の初期残高（通常は 0、必要時手動設定）
              "subtotal": int,          # 発生
              "tax": int,               # 消費税
              "payment_amount": int,    # 消滅（入金）
              "carried_over": int,      # 当月残高 = previous_balance + opening_balance + subtotal + tax - payment_amount
            }
        """
        # 前月の carried_over を取得（再帰は避け、前月データだけ確認）
        prev_ym = _shift_year_month(year_month, -1)
        prev_balance = 0
        if prev_ym:
            prev_amounts = self.get_monthly_amounts(company_name, prev_ym)
            prev_payment = self.get_payment(company_name, prev_ym)
            prev_opening = (prev_payment or {}).get("opening_balance", 0)
            prev_payment_amt = (prev_payment or {}).get("payment_amount", 0)
            # 再帰的に辿らず、前月データだけで近似（単月前月との差分）
            # 厳密に過去全て累積したい場合は compute_ledger を再帰で呼ぶ
            prev_prev_ledger = self._compute_previous_balance(company_name, prev_ym)
            prev_balance = (
                prev_prev_ledger
                + prev_opening
                + prev_amounts["subtotal"]
                + prev_amounts["tax"]
                - prev_payment_amt
            )

        current_amounts = self.get_monthly_amounts(company_name, year_month)
        current_payment = self.get_payment(company_name, year_month)
        opening_balance = (current_payment or {}).get("opening_balance", 0)
        payment_amount = (current_payment or {}).get("payment_amount", 0)

        carried_over = (
            prev_balance
            + opening_balance
            + current_amounts["subtotal"]
            + current_amounts["tax"]
            - payment_amount
        )
        return {
            "year_month": year_month,
            "previous_balance": prev_balance,
            "opening_balance": opening_balance,
            "subtotal": current_amounts["subtotal"],
            "tax": current_amounts["tax"],
            "payment_amount": payment_amount,
            "carried_over": carried_over,
            "notes_count": current_amounts["notes_count"],
        }

    def _compute_previous_balance(self, company_name: str, year_month: str) -> int:
        """指定会社・年月の前月残高を再帰的に計算（履歴を遡る）

        全履歴を辿るとコストが重いため、DB上に存在するエントリのみチェックし
        なければ 0 を返す（初期残高は opening_balance で手動補正）。
        """
        prev_ym = _shift_year_month(year_month, -1)
        if not prev_ym:
            return 0
        with self._get_connection() as conn:
            cursor = conn.cursor()
            # 前月に何かデータ(payment or invoice)が存在するか確認
            cursor.execute("""
                SELECT 1 FROM monthly_payments
                WHERE company_name = ? AND year_month = ? LIMIT 1
            """, (company_name, prev_ym))
            has_payment = cursor.fetchone()
            cursor.execute("""
                SELECT 1 FROM monthly_invoices
                WHERE company_name = ? AND year_month = ? LIMIT 1
            """, (company_name, prev_ym))
            has_invoice = cursor.fetchone()
        if not has_payment and not has_invoice:
            return 0
        # 前月のledgerを再帰計算
        prev_ledger = self.compute_ledger(company_name, prev_ym)
        return prev_ledger["carried_over"]

    def list_payments(
        self, company_name: Optional[str] = None, year_month: Optional[str] = None
    ) -> list[dict]:
        """消滅エントリの一覧を取得"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            conditions = []
            params: list = []
            if company_name:
                conditions.append("company_name = ?")
                params.append(company_name)
            if year_month:
                conditions.append("year_month = ?")
                params.append(year_month)
            where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
            cursor.execute(f"""
                SELECT * FROM monthly_payments
                {where}
                ORDER BY company_name, year_month
            """, params)
            return [
                {
                    "id": row["id"],
                    "company_name": row["company_name"],
                    "year_month": row["year_month"],
                    "payment_amount": row["payment_amount"],
                    "opening_balance": row["opening_balance"],
                    "note": row["note"],
                }
                for row in cursor.fetchall()
            ]

    # --- 仕入入金管理 (Phase 1: DB-as-truth) ---

    def upsert_purchase_payment(
        self,
        company_name: str,
        year_month: str,
        payment_amount: int,
        add_mode: bool = False,
        note: Optional[str] = None,
    ) -> dict:
        """仕入入金を登録または更新

        Args:
            add_mode: True の場合は既存値に加算、False の場合は上書き（既定）
            note: None の場合は既存値を保持（新規行作成時は ""）
        """
        current_time = datetime.now().strftime("%Y/%m/%d %H:%M:%S")
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT id, payment_amount, note FROM purchase_payments
                WHERE company_name = ? AND year_month = ?
            """, (company_name, year_month))
            row = cursor.fetchone()
            if row:
                old_value = row["payment_amount"] or 0
                new_value = old_value + payment_amount if add_mode else payment_amount
                new_note = row["note"] if note is None else note
                cursor.execute("""
                    UPDATE purchase_payments
                    SET payment_amount = ?, note = ?, updated_at = ?
                    WHERE id = ?
                """, (new_value, new_note, current_time, row["id"]))
                pid = row["id"]
            else:
                new_value = payment_amount
                cursor.execute("""
                    INSERT INTO purchase_payments
                    (company_name, year_month, payment_amount, note, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (
                    company_name, year_month, new_value,
                    note or "", current_time, current_time,
                ))
                pid = cursor.lastrowid
            return {
                "id": pid,
                "company_name": company_name,
                "year_month": year_month,
                "payment_amount": new_value,
                "new_value": new_value,
            }

    def get_purchase_payment(self, company_name: str, year_month: str) -> Optional[dict]:
        """指定仕入先・年月の入金エントリを取得"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM purchase_payments
                WHERE company_name = ? AND year_month = ?
            """, (company_name, year_month))
            row = cursor.fetchone()
            if not row:
                return None
            return {
                "id": row["id"],
                "company_name": row["company_name"],
                "year_month": row["year_month"],
                "payment_amount": row["payment_amount"],
                "note": row["note"],
            }

    def list_purchase_payments(
        self, company_name: Optional[str] = None, year_month: Optional[str] = None
    ) -> list[dict]:
        """仕入入金エントリの一覧を取得"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            conditions = []
            params: list = []
            if company_name:
                conditions.append("company_name = ?")
                params.append(company_name)
            if year_month:
                conditions.append("year_month = ?")
                params.append(year_month)
            where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
            cursor.execute(f"""
                SELECT * FROM purchase_payments
                {where}
                ORDER BY company_name, year_month
            """, params)
            return [
                {
                    "id": row["id"],
                    "company_name": row["company_name"],
                    "year_month": row["year_month"],
                    "payment_amount": row["payment_amount"],
                    "note": row["note"],
                }
                for row in cursor.fetchall()
            ]


def _shift_year_month(year_month: str, delta_months: int) -> Optional[str]:
    """'YYYY年M月' を delta_months ずらす。パース失敗時は None"""
    import re as _re
    m = _re.match(r"(\d+)年(\d+)月", year_month or "")
    if not m:
        return None
    y, mo = int(m.group(1)), int(m.group(2))
    idx = (y * 12 + (mo - 1)) + delta_months
    new_y = idx // 12
    new_m = (idx % 12) + 1
    return f"{new_y}年{new_m}月"
