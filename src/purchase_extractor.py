"""仕入れ納品書データの構造定義と抽出処理"""
from dataclasses import dataclass, field
from typing import Optional

from .llm_extractor import LLMExtractor


@dataclass
class PurchaseItem:
    """仕入れ納品書の明細行"""
    product_code: str  # 商品コード
    product_name: str  # 品名
    quantity: int  # 数量
    unit_price: int  # 単価
    amount: int  # 金額


@dataclass
class PurchaseInvoice:
    """仕入れ納品書データ"""
    date: str  # 日付（YYYY/MM/DD）
    supplier_name: str  # 仕入先名（発行元）
    slip_number: str  # 伝票番号
    items: list[PurchaseItem] = field(default_factory=list)
    subtotal: int = 0  # 税抜
    tax: int = 0  # 消費税（非課税なら0）
    total: int = 0  # 合計金額（税込）
    is_taxable: bool = True  # 課税かどうか

    def calculate_totals(self):
        """明細から合計を再計算"""
        if self.items:
            self.subtotal = sum(item.amount for item in self.items)
        if self.total == 0:
            self.total = self.subtotal + self.tax


# Gemini用の仕入れ抽出プロンプト（配列で返す）
PURCHASE_EXTRACTION_PROMPT = """
この画像は仕入れ納品書（または請求書）です。**1つのPDFに複数の納品書が含まれる場合があります。**
全ての納品書を抽出し、**JSON配列**で返してください。

**重要な抽出ルール:**

1. **supplier_name（仕入先名）**: 納品書の**下部**に記載されている**発行元**の会社名を抽出してください。
   - 宛先（上部の「御中」がついた会社名）ではなく、**発行元（下部の会社名）**を取得
   - 「出荷元」「配送元」ではなく「発行元」「請求元」の会社名
   - 例: 下部に「株式会社フクイ」と記載されている場合は「株式会社フクイ」

2. **date（日付）**: 納品日または請求日を YYYY/MM/DD 形式で抽出
   - 例: 2025年02月06日 → "2025/02/06"

3. **slip_number（伝票番号）**: 伝票番号や請求書番号を抽出

4. **items（明細）**: 商品の明細行を抽出
   - product_code: 商品コード
   - product_name: 品名
   - quantity: 数量（整数）
   - unit_price: 単価（整数、円）
   - amount: 金額（整数、円）

5. **subtotal（税抜金額）**: 税抜合計金額（整数、円）

6. **tax（消費税額）**: 消費税額（整数、円）。消費税が0円の場合は 0

7. **total（合計金額）**: 税込合計金額（整数、円）

8. **is_taxable（課税判定）**: 消費税が課されているかどうか（真偽値）
   - 消費税額が0円でない場合 → true
   - 消費税額が0円、または「非課税」「免税」と記載されている場合 → false
   - 不明な場合はtrue（デフォルト）

9. **is_return（返品フラグ）**: 返品伝票かどうか（真偽値）
   - 「返品」「返却」「RETURN」などのキーワードが含まれる場合は true
   - **重要**: 返品の場合、金額は正の数で記載されていても、後で自動的にマイナスに変換されます

**出力形式（JSON配列）:**
```json
[
  {
    "date": "2025/02/06",
    "supplier_name": "株式会社フクイ",
    "slip_number": "123456",
    "items": [
      {
        "product_code": "ABC-001",
        "product_name": "商品名",
        "quantity": 10,
        "unit_price": 1000,
        "amount": 10000
      }
    ],
    "subtotal": 10000,
    "tax": 1000,
    "total": 11000,
    "is_taxable": true,
    "is_return": false
  }
]
```

**必ずJSON配列形式で出力してください（納品書が1つだけの場合も配列で返す）。**
値が不明な場合は空文字または0を使用してください。
"""


class PurchaseExtractor(LLMExtractor):
    """仕入れ納品書抽出クラス（Geminiに直接画像を送信）"""

    def extract_from_pdf(self, pdf_path: str) -> list[PurchaseInvoice]:
        """PDFから仕入れ納品書データを抽出（配列で返す）

        Args:
            pdf_path: PDFファイルのパス

        Returns:
            list[PurchaseInvoice]: 抽出されたデータのリスト、失敗時は空リスト
        """
        from pathlib import Path

        try:
            # PDFを画像に変換
            images = self._pdf_to_images(Path(pdf_path))
            print(f"  PDF → {len(images)} ページの画像に変換")

            # Geminiに直接画像を送信して構造化抽出
            print(f"\n=== Gemini APIに画像を直接送信中（仕入れ抽出） ===")
            result_data = self._extract_purchase_with_gemini(images)

            if not result_data:
                print("    エラー: Gemini抽出に失敗")
                return []

            # 配列でない場合は配列に変換
            if isinstance(result_data, dict):
                result_data = [result_data]

            invoices = []
            for entry in result_data:
                invoice = self._parse_purchase_entry(entry)
                if invoice:
                    invoices.append(invoice)

            print(f"  抽出完了: {len(invoices)}件の納品書")
            return invoices

        except Exception as e:
            print(f"    エラー: データ抽出に失敗: {e}")
            import traceback
            traceback.print_exc()
            return []

    def _parse_purchase_entry(self, entry: dict) -> Optional[PurchaseInvoice]:
        """1件分の抽出データをPurchaseInvoiceに変換"""
        try:
            is_return = entry.get("is_return", False)

            items = []
            for item_data in entry.get("items", []):
                amount = int(item_data.get("amount", 0) or 0)
                if is_return and amount > 0:
                    amount = -amount
                items.append(PurchaseItem(
                    product_code=str(item_data.get("product_code", "")),
                    product_name=str(item_data.get("product_name", "")),
                    quantity=int(item_data.get("quantity", 0) or 0),
                    unit_price=int(item_data.get("unit_price", 0) or 0),
                    amount=amount,
                ))

            subtotal = int(entry.get("subtotal", 0) or 0)
            tax = int(entry.get("tax", 0) or 0)
            total = int(entry.get("total", 0) or 0)

            if is_return:
                if subtotal > 0:
                    subtotal = -subtotal
                if tax > 0:
                    tax = -tax
                if total > 0:
                    total = -total

            invoice = PurchaseInvoice(
                date=entry.get("date", ""),
                supplier_name=entry.get("supplier_name", ""),
                slip_number=entry.get("slip_number", ""),
                items=items,
                subtotal=subtotal,
                tax=tax,
                total=total,
                is_taxable=entry.get("is_taxable", True),
            )

            invoice.calculate_totals()
            return invoice

        except Exception as e:
            print(f"    エラー: エントリのパースに失敗: {e}")
            return None

    def _extract_purchase_with_gemini(self, images) -> Optional[list]:
        """Geminiに画像を直接送信して仕入れ納品書の構造化データを抽出（配列で返す）"""
        import json
        from io import BytesIO
        from google.genai import types

        try:
            # 画像パーツを作成
            contents = []
            for image in images:
                buffer = BytesIO()
                image.save(buffer, format="PNG")
                image_part = types.Part.from_bytes(
                    data=buffer.getvalue(),
                    mime_type="image/png",
                )
                contents.append(image_part)

            # プロンプトを追加
            contents.append(PURCHASE_EXTRACTION_PROMPT)

            # Gemini APIに送信
            response = self.gemini_client.models.generate_content(
                model=self.model,
                contents=contents,
            )
            response_text = response.text

            # JSONブロックを抽出（```json ... ``` の場合）
            if "```json" in response_text:
                json_start = response_text.find("```json") + 7
                json_end = response_text.find("```", json_start)
                response_text = response_text[json_start:json_end].strip()
            elif "```" in response_text:
                json_start = response_text.find("```") + 3
                json_end = response_text.find("```", json_start)
                response_text = response_text[json_start:json_end].strip()

            parsed = json.loads(response_text)

            # dictの場合はlistに変換
            if isinstance(parsed, dict):
                return [parsed]
            return parsed

        except json.JSONDecodeError as e:
            print(f"JSON解析エラー: {e}")
            print(f"レスポンス: {response_text[:500]}")
            return None
        except Exception as e:
            print(f"Gemini API エラー: {e}")
            import traceback
            traceback.print_exc()
            return None
