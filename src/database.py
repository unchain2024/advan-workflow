"""SQLiteデータベース管理モジュール（正規化3テーブル構造）"""
import sqlite3
import json
from datetime import datetime
from pathlib import Path
from typing import Optional
from contextlib import contextmanager

from .config import DATABASE_PATH, DATA_DIR
from .pdf_extractor import DeliveryNote, DeliveryItem
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
            cursor.execute("""
                CREATE UNIQUE INDEX IF NOT EXISTS idx_delivery_notes_slip_unique
                ON delivery_notes(monthly_invoice_id, slip_number)
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
