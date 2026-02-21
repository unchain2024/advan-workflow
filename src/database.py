"""SQLiteデータベース管理モジュール（正規化3テーブル構造）"""
import sqlite3
import json
from datetime import datetime
from pathlib import Path
from typing import Optional
from contextlib import contextmanager

from .config import DATABASE_PATH, DATA_DIR
from .pdf_extractor import DeliveryNote, DeliveryItem
from .sheets_client import normalize_company_name


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

        # 完全一致がなければ、正規化名で検索
        normalized_search = normalize_company_name(company_name)
        if not normalized_search:
            return None

        cursor.execute("""
            SELECT id, company_name FROM monthly_invoices
            WHERE year_month = ?
        """, (year_month,))
        rows = cursor.fetchall()

        for row in rows:
            normalized_db = normalize_company_name(row["company_name"])
            if normalized_db and (
                normalized_search in normalized_db
                or normalized_db in normalized_search
            ):
                print(f"    正規化マッチ: '{company_name}' → DB内 '{row['company_name']}'")
                return (row["id"], row["company_name"])

        return None

    def save_monthly_items(
        self,
        company_name: str,
        year_month: str,
        delivery_note: DeliveryNote,
        sales_person: str = "",
    ):
        """月次明細DBに納品書データを保存（月+会社キーで集約）

        monthly_invoices をUPSERT → delivery_notes にINSERT → delivery_items にINSERT
        """
        sales_person_clean = "".join(sales_person.split())
        current_time = datetime.now().strftime("%Y/%m/%d %H:%M:%S")

        with self._get_connection() as conn:
            cursor = conn.cursor()

            # monthly_invoices を検索または作成
            result = self._find_invoice_id(cursor, year_month, company_name)

            if result:
                invoice_id, _ = result
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

            # delivery_notes に挿入
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
    ) -> list[DeliveryNote]:
        """月次明細DBから指定した会社・年月のデータを取得

        3テーブルJOINで取得し、DeliveryNote のリストとして返す。
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()

            result = self._find_invoice_id(cursor, year_month, company_name)
            if not result:
                print(f"    月次明細DB: レコードが見つかりません ({company_name}, {year_month})")
                return []

            invoice_id, _ = result

            # delivery_notes を取得
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

    def get_distinct_sales_persons(self) -> list[str]:
        """月次明細DBに保存されているすべての担当者名を取得"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT DISTINCT sales_person
                FROM delivery_notes
                WHERE sales_person != ''
                ORDER BY sales_person
            """)
            return [row["sales_person"] for row in cursor.fetchall()]
