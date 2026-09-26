"""Anthropic Claude を使った納品書データ抽出モジュール

LLMExtractor (Gemini) と同じインターフェース (extract(pdf_path) -> DeliveryNote)。
比較テスト用に並列に動かせるようにしている。

EXTRACTION_PROMPT は llm_extractor から流用するので、Geminiと同じ条件下での精度比較が可能。
"""
from __future__ import annotations

import base64
import json
import time
from io import BytesIO
from pathlib import Path
from typing import Optional

import anthropic
from pdf2image import convert_from_path
from PIL import Image

from .config import ANTHROPIC_API_KEY, CLAUDE_MODEL
from .company_resolver import resolve_company_name
from .llm_extractor import EXTRACTION_PROMPT
from .pdf_extractor import DeliveryItem, DeliveryNote


class ClaudeExtractor:
    """Claude Messages API (vision) で納品書から情報を抽出するクラス"""

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        max_tokens: int = 16384,
    ):
        self.api_key = api_key or ANTHROPIC_API_KEY
        self.model = model or CLAUDE_MODEL
        self.max_tokens = max_tokens

        if not self.api_key:
            raise ValueError(
                "ANTHROPIC_API_KEY が設定されていません。.env を確認してください。"
            )

        self.client = anthropic.Anthropic(api_key=self.api_key)

    def extract(self, pdf_path: Path, filename: Optional[str] = None) -> DeliveryNote:
        """PDF 全体を 1 枚の納品書として抽出（従来動作）"""
        images = self._pdf_to_images(pdf_path)
        print(f"  PDF → {len(images)} ページの画像に変換 (Claude/{self.model})")
        return self.extract_from_images(images, filename=filename)

    def extract_from_images(
        self, images: list[Image.Image], filename: Optional[str] = None
    ) -> DeliveryNote:
        """画像リスト（= 1 伝票分のページ群）から DeliveryNote を抽出"""
        raw = self._extract_raw(images)
        return self._postprocess(raw, filename=filename)

    def _extract_raw(
        self, images: list[Image.Image], max_retries: int = 6, allow_empty: bool = False
    ):
        """Claude に画像を送り、生 JSON（dict または list）を返す（リトライ付き）

        allow_empty=True のときは空の dict/list も成功扱い（白紙ページ判定用）。
        """
        extracted = None
        for attempt in range(1, max_retries + 1):
            print(
                f"\n=== Claude APIに画像を直接送信中 "
                f"({len(images)}ページ, 試行 {attempt}/{max_retries}) ==="
            )
            extracted = self._extract_with_claude(images)
            ok = extracted is not None if allow_empty else bool(extracted)
            if ok:
                break
            print(f"  ⚠️ 試行 {attempt} 失敗、{'リトライします...' if attempt < max_retries else '全試行失敗'}")

        if extracted is None or (not allow_empty and not extracted):
            raise ValueError(f"データの抽出に失敗しました（{max_retries}回リトライ後）")
        return extracted

    def _postprocess(self, extracted, filename: Optional[str] = None) -> DeliveryNote:
        """生 JSON → 日付検証・会社名解決 → DeliveryNote"""
        if isinstance(extracted, list):
            print(f"  ⚠️ Claudeがリスト({len(extracted)}件)を返却 → 1件にマージ")
            merged: dict = dict(extracted[0]) if extracted else {}
            all_items = []
            all_candidates = []
            for entry in extracted:
                if not isinstance(entry, dict):
                    continue
                all_items.extend(entry.get("items", []) or [])
                all_candidates.extend(entry.get("company_candidates", []) or [])
                for key in [
                    "date",
                    "company_name",
                    "slip_number",
                    "subtotal",
                    "tax",
                    "total",
                    "payment_received",
                ]:
                    if not merged.get(key) and entry.get(key):
                        merged[key] = entry[key]
            merged["items"] = all_items
            merged["company_candidates"] = all_candidates
            extracted = merged
        if not isinstance(extracted, dict):
            extracted = {}

        date_str = extracted.get("date") or ""
        import re as _re

        date_pattern = r"^(20\d{2})/(0[1-9]|1[0-2])/(0[1-9]|[12]\d|3[01])$"
        if date_str and not _re.match(date_pattern, date_str):
            print(f"  ⚠️ 警告: 無効な日付形式: '{date_str}' → null")
            date_str = ""

        # 会社名解決: 候補（company_candidates + company_name）から自社名を除外し、
        # マスタ一致・役割・確信度でスコアリングして 1 件選ぶ
        company_name, _ = resolve_company_name(extracted, domain="sales", filename=filename)

        merged_data = {
            "date": date_str,
            "company_name": company_name,
            "slip_number": extracted.get("slip_number") or "",
            "subtotal": extracted.get("subtotal", 0),
            "tax": extracted.get("tax", 0),
            "total": extracted.get("total", 0),
            "payment_received": extracted.get("payment_received", 0),
            "is_return": extracted.get("is_return", False),
        }
        return self._to_delivery_note(merged_data, extracted.get("items", []) or [])

    def _pdf_to_images(self, pdf_path: Path) -> list[Image.Image]:
        return convert_from_path(str(pdf_path), dpi=300)

    @staticmethod
    def _image_to_b64(image: Image.Image) -> str:
        buf = BytesIO()
        image.save(buf, format="PNG")
        return base64.standard_b64encode(buf.getvalue()).decode("ascii")

    def _extract_with_claude(self, images: list[Image.Image]) -> Optional[dict]:
        try:
            content = []
            for img in images:
                content.append(
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": "image/png",
                            "data": self._image_to_b64(img),
                        },
                    }
                )
            content.append({"type": "text", "text": EXTRACTION_PROMPT})

            resp = self.client.messages.create(
                model=self.model,
                max_tokens=self.max_tokens,
                messages=[{"role": "user", "content": content}],
            )
            text = ""
            for block in resp.content:
                if getattr(block, "type", None) == "text":
                    text += block.text

            if "```json" in text:
                start = text.find("```json") + 7
                end = text.find("```", start)
                text = text[start:end].strip()
            elif "```" in text:
                start = text.find("```") + 3
                end = text.find("```", start)
                text = text[start:end].strip()

            return json.loads(text)
        except json.JSONDecodeError as e:
            print(f"JSON解析エラー: {e}")
            print(f"レスポンス先頭500: {text[:500] if 'text' in locals() else ''}")
            return None
        except anthropic.RateLimitError as e:
            print(f"  🕒 レート制限: {e} → 30秒待機")
            time.sleep(30)
            return None
        except Exception as e:
            err = str(e)
            print(f"Claude API エラー: {e}")
            if "overloaded" in err.lower() or "529" in err:
                print("  🕒 サーバ過負荷 → 30秒待機")
                time.sleep(30)
            else:
                import traceback

                traceback.print_exc()
            return None

    def _to_delivery_note(self, data: dict, items_data: list) -> DeliveryNote:
        is_return = bool(data.get("is_return", False))
        items: list[DeliveryItem] = []
        for it in items_data:
            amount = int(it.get("amount", 0) or 0)
            quantity = int(it.get("quantity", 0) or 0)
            if is_return:
                if amount > 0:
                    amount = -amount
                if quantity > 0:
                    quantity = -quantity
            items.append(
                DeliveryItem(
                    slip_number=str(it.get("slip_number", "") or ""),
                    product_code=str(it.get("product_code", "") or ""),
                    product_name=str(it.get("product_name", "") or ""),
                    quantity=quantity,
                    unit_price=int(it.get("unit_price", 0) or 0),
                    amount=amount,
                )
            )

        subtotal = int(data.get("subtotal", 0) or 0)
        tax = int(data.get("tax", 0) or 0)
        total = int(data.get("total", 0) or 0)
        if is_return:
            if subtotal > 0:
                subtotal = -subtotal
            if tax > 0:
                tax = -tax
            if total > 0:
                total = -total

        if subtotal != 0 and tax == 0:
            tax = int(subtotal * 0.1)
            total = subtotal + tax
        elif total != 0 and subtotal == 0 and tax == 0:
            subtotal = total
            tax = int(subtotal * 0.1)
            total = subtotal + tax
        elif subtotal != 0 and tax != 0 and total == 0:
            total = subtotal + tax

        # パターン4: subtotal/tax/total が全部0 でも items の amount 合計があれば
        # それを subtotal とみなして計算（バロック等の特殊フォーマット対策）
        elif subtotal == 0 and tax == 0 and total == 0 and items:
            items_sum = sum(item.amount for item in items if item.amount)
            if items_sum != 0:
                subtotal = items_sum
                tax = int(subtotal * 0.1)
                total = subtotal + tax
                print(
                    f"    [金額フォールバック Claude] subtotal/tax/total=0 → 明細合計 "
                    f"{items_sum} を採用 → subtotal={subtotal}, tax={tax}, total={total}"
                )

        # 抽出結果のデバッグログ (合算ずれ調査用)
        slip = data.get("slip_number", "")
        print(
            f"    [Claude抽出 結果] slip={slip}, items={len(items)}, "
            f"subtotal={subtotal}, tax={tax}, total={total}"
        )

        return DeliveryNote(
            date=data.get("date", "") or "",
            company_name=data.get("company_name", "") or "",
            slip_number=data.get("slip_number", "") or "",
            items=items,
            subtotal=subtotal,
            tax=tax,
            total=total,
            payment_received=int(data.get("payment_received", 0) or 0),
        )


def extract_delivery_note_with_claude(pdf_path: Path, model: Optional[str] = None) -> DeliveryNote:
    extractor = ClaudeExtractor(model=model)
    return extractor.extract(pdf_path)
