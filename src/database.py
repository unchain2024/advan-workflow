"""SQLiteデータベース管理モジュール"""
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
        """
        Args:
            db_path: データベースファイルパス（Noneの場合はDATABASE_PATHを使用）
        """
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
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _init_database(self):
        """データベーステーブルを初期化"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS monthly_items (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    year_month TEXT NOT NULL,
                    company_name TEXT NOT NULL,
                    items_json TEXT NOT NULL,
                    subtotal INTEGER NOT NULL,
                    tax INTEGER NOT NULL,
                    total INTEGER NOT NULL,
                    slip_numbers TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(year_month, company_name)
                )
            """)
            # インデックス作成
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_year_month_company
                ON monthly_items(year_month, company_name)
            """)

    def save_monthly_items(
        self,
        company_name: str,
        year_month: str,
        delivery_note: DeliveryNote,
    ):
        """月次明細DBに納品書データを保存（月+会社キーで集約）

        処理:
        1. 年月+会社名をキーとして既存レコードを検索
        2. 既存レコードがある場合:
           - 明細JSONに新しい納品書データを追加
           - 小計・消費税・合計を累積加算
           - 納品書リストに伝票番号を追加
        3. 既存レコードがない場合:
           - 新規レコードを作成

        Args:
            company_name: 会社名
            year_month: 年月（YYYY年M月形式）
            delivery_note: 納品書データ
        """
        # 会社名を正規化
        normalized_company = normalize_company_name(company_name)

        # 新しい明細データを作成
        new_item = {
            "date": delivery_note.date,
            "slip_number": delivery_note.slip_number,
            "items": [
                {
                    "product_code": item.product_code,
                    "product_name": item.product_name,
                    "quantity": item.quantity,
                    "unit_price": item.unit_price,
                    "amount": item.amount,
                }
                for item in delivery_note.items
            ],
        }

        current_time = datetime.now().strftime("%Y/%m/%d %H:%M:%S")

        with self._get_connection() as conn:
            cursor = conn.cursor()

            # 既存レコードを検索（正規化した会社名でマッチング）
            cursor.execute("""
                SELECT id, items_json, subtotal, tax, total, slip_numbers
                FROM monthly_items
                WHERE year_month = ? AND company_name = ?
            """, (year_month, company_name))

            existing_row = cursor.fetchone()

            if existing_row:
                # 既存レコードを更新
                existing_json = existing_row["items_json"]
                existing_subtotal = existing_row["subtotal"]
                existing_tax = existing_row["tax"]
                existing_total = existing_row["total"]
                existing_slips = existing_row["slip_numbers"]

                # 明細JSONに追加
                try:
                    items_list = json.loads(existing_json)
                except json.JSONDecodeError:
                    items_list = []

                items_list.append(new_item)
                updated_json = json.dumps(items_list, ensure_ascii=False)

                # 納品書リストに追加
                slip_list = [s.strip() for s in existing_slips.split(",") if s.strip()]
                if delivery_note.slip_number and delivery_note.slip_number not in slip_list:
                    slip_list.append(delivery_note.slip_number)
                updated_slips = ", ".join(slip_list)

                # 更新
                cursor.execute("""
                    UPDATE monthly_items
                    SET items_json = ?,
                        subtotal = ?,
                        tax = ?,
                        total = ?,
                        slip_numbers = ?,
                        updated_at = ?
                    WHERE id = ?
                """, (
                    updated_json,
                    existing_subtotal + delivery_note.subtotal,
                    existing_tax + delivery_note.tax,
                    existing_total + delivery_note.total,
                    updated_slips,
                    current_time,
                    existing_row["id"],
                ))

                print(f"    月次明細DB更新: {company_name} ({year_month}) - ID {existing_row['id']}")
            else:
                # 新規レコード作成
                items_json = json.dumps([new_item], ensure_ascii=False)

                cursor.execute("""
                    INSERT INTO monthly_items
                    (year_month, company_name, items_json, subtotal, tax, total, slip_numbers, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    year_month,
                    company_name,
                    items_json,
                    delivery_note.subtotal,
                    delivery_note.tax,
                    delivery_note.total,
                    delivery_note.slip_number or "",
                    current_time,
                    current_time,
                ))

                print(f"    月次明細DB新規作成: {company_name} ({year_month})")

    def get_monthly_items(
        self,
        company_name: str,
        year_month: str,
    ) -> list[DeliveryNote]:
        """月次明細DBから指定した会社・年月のデータを取得

        Args:
            company_name: 会社名
            year_month: 年月（YYYY年M月形式）

        Returns:
            list[DeliveryNote]: 納品書データのリスト（見つからない場合は空リスト）
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()

            # レコードを検索
            cursor.execute("""
                SELECT items_json
                FROM monthly_items
                WHERE year_month = ? AND company_name = ?
            """, (year_month, company_name))

            row = cursor.fetchone()

            if row:
                # 明細JSONをパース
                try:
                    items_json = row["items_json"]
                    items_list = json.loads(items_json)
                    delivery_notes = []

                    for item_data in items_list:
                        # DeliveryNoteオブジェクトを作成
                        slip_number = item_data["slip_number"]
                        items = [
                            DeliveryItem(
                                slip_number=slip_number,
                                product_code=item["product_code"],
                                product_name=item["product_name"],
                                quantity=item["quantity"],
                                unit_price=item["unit_price"],
                                amount=item["amount"],
                            )
                            for item in item_data.get("items", [])
                        ]

                        # 小計・消費税・合計を計算
                        subtotal = sum(item.amount for item in items)
                        tax = int(subtotal * 0.1)
                        total = subtotal + tax

                        delivery_note = DeliveryNote(
                            slip_number=item_data["slip_number"],
                            date=item_data["date"],
                            company_name=company_name,
                            items=items,
                            subtotal=subtotal,
                            tax=tax,
                            total=total,
                        )
                        delivery_notes.append(delivery_note)

                    print(f"    月次明細DB取得: {company_name} ({year_month}) - {len(delivery_notes)}件の納品書")
                    return delivery_notes

                except (json.JSONDecodeError, KeyError) as e:
                    print(f"    エラー: 明細JSONのパースに失敗: {e}")
                    return []

            print(f"    月次明細DB: レコードが見つかりません ({company_name}, {year_month})")
            return []

    def get_monthly_summary(
        self,
        company_name: str,
        year_month: str,
    ) -> Optional[dict]:
        """月次集計情報を取得

        Args:
            company_name: 会社名
            year_month: 年月（YYYY年M月形式）

        Returns:
            dict: 集計情報（subtotal, tax, total, slip_count, slip_numbers）
                  見つからない場合はNone
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()

            cursor.execute("""
                SELECT subtotal, tax, total, slip_numbers
                FROM monthly_items
                WHERE year_month = ? AND company_name = ?
            """, (year_month, company_name))

            row = cursor.fetchone()

            if row:
                slip_numbers = [s.strip() for s in row["slip_numbers"].split(",") if s.strip()]
                return {
                    "subtotal": row["subtotal"],
                    "tax": row["tax"],
                    "total": row["total"],
                    "slip_count": len(slip_numbers),
                    "slip_numbers": slip_numbers,
                }

            return None
