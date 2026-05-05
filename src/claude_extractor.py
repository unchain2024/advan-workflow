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

from .config import ANTHROPIC_API_KEY, CLAUDE_MODEL, load_company_config
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

    def extract(self, pdf_path: Path) -> DeliveryNote:
        """PDFから納品書データを抽出"""
        images = self._pdf_to_images(pdf_path)
        print(f"  PDF → {len(images)} ページの画像に変換 (Claude/{self.model})")

        max_retries = 6
        extracted = None
        for attempt in range(1, max_retries + 1):
            print(f"\n=== Claude APIに画像を直接送信中 (試行 {attempt}/{max_retries}) ===")
            extracted = self._extract_with_claude(images)
            if extracted is not None:
                break
            print(f"  ⚠️ 試行 {attempt} 失敗、{'リトライします...' if attempt < max_retries else '全試行失敗'}")

        if not extracted:
            raise ValueError(f"データの抽出に失敗しました（{max_retries}回リトライ後）")

        if isinstance(extracted, list):
            print(f"  ⚠️ Claudeがリスト({len(extracted)}件)を返却 → 1件にマージ")
            merged: dict = extracted[0] if extracted else {}
            all_items = []
            for entry in extracted:
                all_items.extend(entry.get("items", []))
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
            extracted = merged

        date_str = extracted.get("date") or ""
        import re as _re

        date_pattern = r"^(20\d{2})/(0[1-9]|1[0-2])/(0[1-9]|[12]\d|3[01])$"
        if date_str and not _re.match(date_pattern, date_str):
            print(f"  ⚠️ 警告: 無効な日付形式: '{date_str}' → null")
            date_str = ""

        # 自社名フィルタ
        company_name = extracted.get("company_name", "") or ""
        if company_name:
            own = load_company_config()
            own_name = own.get("company_name", "")

            def _norm(name: str) -> str:
                name = _re.sub(r"株式会社|有限会社|合同会社|合資会社|合名会社", "", name)
                name = _re.sub(
                    r"\bCO\.?\s*,?\s*LTD\.?\b|\bINC\.?\b|\bCORP\.?\b",
                    "",
                    name,
                    flags=_re.IGNORECASE,
                )
                name = _re.sub(r"御中|様|殿", "", name)
                return (
                    name.replace(" ", "")
                    .replace("　", "")
                    .replace(".", "")
                    .replace(",", "")
                    .strip()
                    .upper()
                )

            n_own = _norm(own_name) if own_name else ""
            n_ext = _norm(company_name)
            if n_own and n_ext and (n_own in n_ext or n_ext in n_own):
                print(f"警告: 自社名と一致 → 除外: {company_name}")
                company_name = ""

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
        return self._to_delivery_note(merged_data, extracted.get("items", []))

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
