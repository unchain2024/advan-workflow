"""仕入れ納品書データの構造定義と抽出処理"""
from dataclasses import dataclass, field
from typing import Optional
import re

from .llm_extractor import LLMExtractor


@dataclass
class PurchaseItem:
    """仕入れ納品書の明細行"""
    slip_number: str  # 伝票番号
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
    supplier_address: str  # 仕入先住所
    slip_number: str  # 伝票番号
    items: list[PurchaseItem] = field(default_factory=list)
    subtotal: int = 0  # 税抜
    tax: int = 0  # 消費税
    total: int = 0  # 合計金額（税込）
    customs_duty: int = 0  # 関税額
    is_overseas: bool = False  # 海外輸入フラグ

    def calculate_totals(self):
        """明細から合計を再計算"""
        if self.items:
            self.subtotal = sum(item.amount for item in self.items)
        if self.total == 0:
            self.total = self.subtotal + self.tax


# Gemini用の仕入れ抽出プロンプト
PURCHASE_EXTRACTION_PROMPT = """
この画像は仕入れ納品書（または請求書）です。以下の情報を抽出してください。

**重要な抽出ルール:**
1. **supplier_name（仕入先名）**: 納品書の**下部**に記載されている発行元の会社名を抽出してください。
   - 宛先（上部の「御中」などがついた会社名）ではなく、発行元（下部の会社名）を取得してください。
   - 例: 下部に「株式会社フクイ」と記載されている場合は「株式会社フクイ」

2. **supplier_address（仕入先住所）**: 発行元（下部）の住所を抽出してください。
   - 海外住所の場合は、国名・都市名も含めてください。
   - 例: "中国広東省東莞市虎門鎮..." のように記載

3. **date（日付）**: 納品日または請求日を YYYY/MM/DD 形式で抽出してください。
   - 例: 2025年02月06日 → "2025/02/06"

4. **slip_number（伝票番号）**: 伝票番号や請求書番号を抽出してください。

5. **items（明細）**: 商品の明細行を抽出してください。
   - slip_number: 明細ごとの伝票番号（なければ空文字）
   - product_code: 商品コード
   - product_name: 品名
   - quantity: 数量（整数）
   - unit_price: 単価（整数、円）
   - amount: 金額（整数、円）

6. **subtotal（税抜金額）**: 税抜合計金額を抽出してください（整数、円）。

7. **tax（消費税額）**: 消費税額を抽出してください（整数、円）。
   - 消費税が0円の場合は 0 を返してください。

8. **total（合計金額）**: 税込合計金額を抽出してください（整数、円）。

9. **customs_duty（関税額）**: 関税が記載されている場合は抽出してください（整数、円）。
   - 「関税」「関税込」などのキーワードで金額を探してください。
   - 記載がない場合は 0 を返してください。

10. **is_overseas（海外輸入フラグ）**: 海外からの輸入かどうかを判定してください（真偽値）。
    - 発行元住所に海外地名（中国、韓国、USA、台湾など）が含まれる場合は true
    - 消費税が0円の場合は true の可能性が高い
    - それ以外は false

11. **is_return（返品フラグ）**: 返品伝票かどうかを判定してください（真偽値）。
    - テキストに「返品」「返却」「RETURN」などのキーワードが含まれる場合は true
    - 通常の納品書の場合は false
    - **重要**: 返品の場合、金額は正の数で記載されていても、後で自動的にマイナスに変換されます

**出力形式（JSON）:**
```json
{
  "date": "2025/02/06",
  "supplier_name": "株式会社フクイ",
  "supplier_address": "中国広東省東莞市虎門鎮...",
  "slip_number": "123456",
  "items": [
    {
      "slip_number": "",
      "product_code": "ABC-001",
      "product_name": "商品名",
      "quantity": 10,
      "unit_price": 1000,
      "amount": 10000
    }
  ],
  "subtotal": 10000,
  "tax": 0,
  "total": 10000,
  "customs_duty": 0,
  "is_overseas": true,
  "is_return": false
}
```

必ず上記のJSON形式で出力してください。値が不明な場合は空文字または0を使用してください。
"""


class PurchaseExtractor(LLMExtractor):
    """仕入れ納品書抽出クラス（Vision API + Geminiを使用）"""

    def extract_from_pdf(self, pdf_path: str) -> Optional[PurchaseInvoice]:
        """PDFから仕入れ納品書データを抽出

        Args:
            pdf_path: PDFファイルのパス

        Returns:
            PurchaseInvoice: 抽出されたデータ、失敗時はNone
        """
        from pathlib import Path

        try:
            # PDFを画像に変換
            images = self._pdf_to_images(Path(pdf_path))

            # 各ページからOCRでテキスト抽出
            all_text = []
            for i, image in enumerate(images):
                text = self._extract_text_with_vision(image)
                print(f"\n=== ページ {i + 1} OCR結果 ===")
                print(f"抽出文字数: {len(text)} 文字")
                all_text.append(f"--- ページ {i + 1} ---\n{text}")

            # 全ページのテキストを結合
            combined_text = "\n\n".join(all_text)
            print(f"\n=== 合計テキスト ===")
            print(f"合計文字数: {len(combined_text)} 文字")

            # Geminiで構造化抽出（仕入れ用プロンプト）
            print(f"\n=== Gemini APIに送信中（仕入れ抽出） ===")
            result_data = self._extract_purchase_with_gemini(combined_text)

            if not result_data:
                print("    エラー: Gemini抽出に失敗")
                return None

            # 返品フラグを取得
            is_return = result_data.get("is_return", False)

            # PurchaseInvoiceオブジェクトに変換
            items = []
            for item_data in result_data.get("items", []):
                amount = item_data.get("amount", 0)
                # 返品の場合、金額を強制的にマイナスに
                if is_return and amount > 0:
                    amount = -amount
                    item_data["amount"] = amount
                items.append(PurchaseItem(**item_data))

            # 金額を取得
            subtotal = result_data.get("subtotal", 0)
            tax = result_data.get("tax", 0)
            total = result_data.get("total", 0)
            customs_duty = result_data.get("customs_duty", 0)

            # 返品の場合、金額をマイナスに
            if is_return:
                if subtotal > 0:
                    subtotal = -subtotal
                if tax > 0:
                    tax = -tax
                if total > 0:
                    total = -total
                if customs_duty > 0:
                    customs_duty = -customs_duty

            invoice = PurchaseInvoice(
                date=result_data.get("date", ""),
                supplier_name=result_data.get("supplier_name", ""),
                supplier_address=result_data.get("supplier_address", ""),
                slip_number=result_data.get("slip_number", ""),
                items=items,
                subtotal=subtotal,
                tax=tax,
                total=total,
                customs_duty=customs_duty,
                is_overseas=result_data.get("is_overseas", False),
            )

            # 海外判定ロジック（補助的なチェック）
            invoice.is_overseas = self._detect_overseas(invoice)

            # 合計値の再計算
            invoice.calculate_totals()

            return invoice

        except Exception as e:
            print(f"    エラー: データ抽出に失敗: {e}")
            import traceback
            traceback.print_exc()
            return None

    def _extract_purchase_with_gemini(self, text: str) -> Optional[dict]:
        """Geminiでテキストから仕入れ納品書の構造化データを抽出"""
        import json

        try:
            # プロンプトにテキストを埋め込む
            full_prompt = f"{PURCHASE_EXTRACTION_PROMPT}\n\n# 仕入れ納品書テキスト\n\n{text}"

            # Gemini APIに送信
            response = self.gemini_client.models.generate_content(
                model=self.model,
                contents=full_prompt
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

            return json.loads(response_text)

        except json.JSONDecodeError as e:
            print(f"JSON解析エラー: {e}")
            print(f"レスポンス: {response_text[:500]}")
            return None
        except Exception as e:
            print(f"Gemini API エラー: {e}")
            import traceback
            traceback.print_exc()
            return None

    def _detect_overseas(self, invoice: PurchaseInvoice) -> bool:
        """海外輸入を判定

        判定基準:
        1. Geminiの判定結果（is_overseas）が true の場合
        2. 住所に海外キーワードが含まれる場合
        3. 消費税が0円の場合

        Args:
            invoice: 抽出された納品書データ

        Returns:
            bool: 海外輸入ならTrue
        """
        # Geminiの判定を優先
        if invoice.is_overseas:
            return True

        # 海外キーワードチェック
        overseas_keywords = [
            "中国", "韓国", "台湾", "香港", "USA", "米国", "アメリカ",
            "China", "Korea", "Taiwan", "Hong Kong", "United States",
            "ベトナム", "Vietnam", "タイ", "Thailand", "インド", "India",
        ]

        address = invoice.supplier_address.lower()
        for keyword in overseas_keywords:
            if keyword.lower() in address:
                return True

        # 消費税が0円かつ金額が存在する場合
        if invoice.tax == 0 and invoice.subtotal > 0:
            return True

        return False
