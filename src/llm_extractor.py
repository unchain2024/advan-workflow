"""LLMを使った納品書データ抽出モジュール

PDFから情報抽出する2段階処理：
1. Google Cloud Vision APIでOCR（文字認識）
2. Claude APIで構造化（項目ごとに分解）
"""
import base64
import json
import os
import pickle
from io import BytesIO
from pathlib import Path
from typing import Optional

import anthropic
from google import genai
from google.cloud import vision
from google.oauth2.credentials import Credentials
from google.oauth2.service_account import Credentials as ServiceAccountCredentials
from pdf2image import convert_from_path
from PIL import Image

from .config import GEMINI_API_KEY, GEMINI_MODEL, load_company_config
from .pdf_extractor import DeliveryItem, DeliveryNote

# Streamlit対応
try:
    import streamlit as st
    HAS_STREAMLIT = True
except ImportError:
    HAS_STREAMLIT = False


# LLMに送るプロンプト
EXTRACTION_PROMPT = """以下は納品書からOCRで抽出したテキストです。このテキストから情報をJSON形式で抽出してください。

## 抽出する項目

1. **date**: 納品日または発行日
   - **入力形式（柔軟に対応）**:
     * "2025年1月15日", "2025/1/15", "2025-01-15" などの西暦表記
     * "令和7年1月15日", "R7/1/15" などの和暦表記
     * "2025年1月", "2025/1" などの年月のみの表記（日は01とする）
   - **出力形式（必須）**: **YYYY/MM/DD** 形式に必ず変換
     * YYYY: 4桁の年（2000-2099）
     * MM: 2桁の月（01-12）、1桁の場合は先頭に0を付ける
     * DD: 2桁の日（01-31）、1桁の場合は先頭に0を付ける
   - **和暦変換**: 令和7年 = 2025年, 令和6年 = 2024年, etc.
   - **変換できない、または明らかに不正な日付の場合は null を返す**
   - 例: "2025年3月15日" → "2025/03/15"
   - 例: "令和7年1月5日" → "2025/01/05"
   - 例: "2025/1" → "2025/01/01"

2. **company_name**: 宛先（受取先）の会社名のみ抽出
   - **重要な判別方法**:
     * 納品書の**上部**に記載されている会社名を抽出
     * 「御中」の**直前**または**近くに**記載されている会社名
     * 「株式会社○○」「○○株式会社」などの法人格を含む会社名
   - **除外すべきもの**:
     * 発行元・差出人の会社名は**絶対に除外**
     * 納品書の**下部**に記載されている発行元の会社名
     * 住所・電話番号の近くに記載されている会社名（発行元の可能性が高い）
   - company_name から「御中」「様」「殿」は除去すること

3. **slip_number**: 伝票番号または納品書番号
   - 「納品伝票番号」「伝票番号」などのラベルの後の番号
4. **subtotal**: 小計金額（税抜）（数値のみ、カンマなし）
5. **tax**: 消費税額（数値のみ、カンマなし）
6. **total**: 合計金額（税込）（数値のみ、カンマなし）
7. **payment_received**: 御入金額（入金額が記載されている場合、なければ0）（数値のみ、カンマなし）
8. **items**: 明細行の配列。各行は以下の項目を含む：
   - **slip_number**: 伝票番号（行ごとにある場合）
   - **product_code**: 商品コード
   - **product_name**: 品名・商品名
   - **quantity**: 数量（数値）
   - **unit_price**: 単価（数値）
   - **amount**: 金額（数値）

## 典型的な納品書のレイアウト

```
[宛先会社名（これを抽出）]
[宛先住所]
御中

納品伝票番号: xxxxx
発行日: YYYY/MM/DD

[明細テーブル]

[発行元会社名 - 除外]
[発行元住所]
[発行元電話番号]
```

## 注意事項

- 金額は数値のみ（カンマや円記号は除去）
- 見つからない項目は null または 0 を設定
- 日付は必ず YYYY/MM/DD 形式に変換
- 会社名から「御中」「様」「殿」は除去
- **company_name は必ず宛先（受取人）の会社名のみ抽出**すること（発行元の会社名は含めない）
- テキスト上部に現れる会社名が宛先の可能性が高い

## 出力形式

```json
{
  "date": "2024/10/15",
  "company_name": "株式会社サンプル",
  "slip_number": "D-12345",
  "subtotal": 100000,
  "tax": 10000,
  "total": 110000,
  "payment_received": 50000,
  "items": [
    {
      "slip_number": "D-12345",
      "product_code": "ABC-001",
      "product_name": "商品A",
      "quantity": 10,
      "unit_price": 5000,
      "amount": 50000
    }
  ]
}
```

JSONのみを出力してください。説明は不要です。"""


class LLMExtractor:
    """Google Cloud Vision API + Gemini APIで納品書から情報を抽出するクラス"""

    def __init__(self, api_key: Optional[str] = None, model: Optional[str] = None):
        self.api_key = api_key or GEMINI_API_KEY
        self.model = model or GEMINI_MODEL
        # Gemini Client作成
        self.gemini_client = genai.Client(api_key=self.api_key)
        self.vision_client = self._get_vision_client()

    def _get_vision_client(self):
        """Vision APIクライアントを取得（OAuth認証またはサービスアカウント）"""
        # Streamlit Cloudの場合はsecretsから読み込む
        if HAS_STREAMLIT and hasattr(st, 'secrets') and 'gcp_service_account' in st.secrets:
            credentials = ServiceAccountCredentials.from_service_account_info(
                dict(st.secrets['gcp_service_account'])
            )
            return vision.ImageAnnotatorClient(credentials=credentials)

        # ローカルではOAuth認証を使用
        token_path = Path("token.pickle")
        if token_path.exists():
            with open(token_path, "rb") as token:
                credentials = pickle.load(token)
                # Vision APIクライアントを作成
                return vision.ImageAnnotatorClient(credentials=credentials)

        raise RuntimeError("OAuth認証が必要です。先にSheets APIを使用して認証してください。")

    def extract(self, pdf_path: Path) -> DeliveryNote:
        """PDFから納品書データを抽出

        Args:
            pdf_path: 納品書PDFのパス

        Returns:
            DeliveryNote: 抽出された納品書データ
        """
        # PDFを画像に変換
        images = self._pdf_to_images(pdf_path)

        # 各ページからOCRでテキスト抽出
        all_text = []
        for i, image in enumerate(images):
            text = self._extract_text_with_vision(image)
            print(f"\n=== ページ {i + 1} OCR結果 ===")
            print(f"抽出文字数: {len(text)} 文字")
            print(f"先頭200文字: {text[:200]}")
            all_text.append(f"--- ページ {i + 1} ---\n{text}")

        # 全ページのテキストを結合
        combined_text = "\n\n".join(all_text)
        print(f"\n=== 合計テキスト ===")
        print(f"合計文字数: {len(combined_text)} 文字")

        # Geminiで構造化抽出
        print(f"\n=== Gemini APIに送信中 ===")
        extracted = self._extract_with_gemini(combined_text)
        print(f"Gemini応答: {extracted}")

        if not extracted:
            raise ValueError("データの抽出に失敗しました")

        # 日付の検証（YYYY/MM/DD形式のみ許可）
        date_str = extracted.get("date", "")
        import re
        date_pattern = r'^(20\d{2})/(0[1-9]|1[0-2])/(0[1-9]|[12]\d|3[01])$'

        if date_str:
            print(f"  抽出された日付: {date_str}")
            # YYYY/MM/DD形式かチェック
            if not re.match(date_pattern, date_str):
                print(f"  ⚠️ 警告: 無効な日付形式を検出: '{date_str}' → null に設定")
                print(f"  正しい形式: YYYY/MM/DD (例: 2025/03/15)")
                date_str = None
            else:
                print(f"  ✓ 日付検証OK: {date_str}")
        else:
            print(f"  ⚠️ 警告: 日付が抽出されませんでした")
            date_str = None

        # 会社名のフィルタリング（自社名を除外）
        company_name = extracted.get("company_name", "")
        if company_name:
            # 自社名と比較
            own_company = load_company_config()
            own_company_name = own_company.get("company_name", "")

            # 自社名が含まれている場合は除外
            if own_company_name and own_company_name in company_name:
                print(f"警告: 自社名が会社名として検出されました: {company_name}")
                company_name = ""  # 空にする

        # データを整形
        merged_data = {
            "date": date_str or "",  # 検証済みの日付を使用
            "company_name": company_name,
            "slip_number": extracted.get("slip_number", ""),
            "subtotal": extracted.get("subtotal", 0),
            "tax": extracted.get("tax", 0),
            "total": extracted.get("total", 0),
            "payment_received": extracted.get("payment_received", 0),
        }
        all_items = extracted.get("items", [])

        # DeliveryNoteオブジェクトに変換
        return self._to_delivery_note(merged_data, all_items)

    def _pdf_to_images(self, pdf_path: Path) -> list[Image.Image]:
        """PDFを画像に変換"""
        images = convert_from_path(
            str(pdf_path),
            dpi=150,  # 解像度（高すぎるとAPI制限に引っかかる可能性）
        )
        return images

    def _image_to_base64(self, image: Image.Image) -> str:
        """PIL ImageをBase64エンコード"""
        buffer = BytesIO()
        image.save(buffer, format="PNG")
        return base64.standard_b64encode(buffer.getvalue()).decode("utf-8")

    def _extract_text_with_vision(self, image: Image.Image) -> str:
        """Google Cloud Vision APIで画像からテキストを抽出"""
        try:
            print("  Vision API呼び出し中...")
            # PIL ImageをバイトデータとしてVision APIに送信
            buffer = BytesIO()
            image.save(buffer, format="PNG")
            content = buffer.getvalue()
            print(f"  画像サイズ: {len(content)} バイト")

            vision_image = vision.Image(content=content)
            response = self.vision_client.document_text_detection(image=vision_image)

            # レスポンスの詳細をデバッグ出力
            print(f"  Response type: {type(response)}")
            print(f"  Has error: {bool(response.error.message) if hasattr(response, 'error') else 'No error field'}")
            print(f"  Has full_text_annotation: {hasattr(response, 'full_text_annotation')}")

            if hasattr(response, 'full_text_annotation') and response.full_text_annotation:
                print(f"  full_text_annotation.text length: {len(response.full_text_annotation.text) if response.full_text_annotation.text else 0}")

            if response.error.message:
                raise Exception(f"Vision API エラー: {response.error.message}")

            # 全テキストを取得
            text = response.full_text_annotation.text if response.full_text_annotation else ""
            print(f"  Vision API成功: {len(text)} 文字抽出")
            return text

        except Exception as e:
            print(f"Vision API エラー: {e}")
            import traceback
            traceback.print_exc()
            return ""

    def _extract_with_gemini(self, text: str) -> Optional[dict]:
        """Geminiでテキストから構造化データを抽出"""
        try:
            # プロンプトにテキストを埋め込む
            full_prompt = f"{EXTRACTION_PROMPT}\n\n# 納品書テキスト\n\n{text}"

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

    def _to_delivery_note(self, data: dict, items_data: list) -> DeliveryNote:
        """辞書データをDeliveryNoteオブジェクトに変換"""
        items = []
        for item in items_data:
            items.append(
                DeliveryItem(
                    slip_number=str(item.get("slip_number", "")),
                    product_code=str(item.get("product_code", "")),
                    product_name=str(item.get("product_name", "")),
                    quantity=int(item.get("quantity", 0) or 0),
                    unit_price=int(item.get("unit_price", 0) or 0),
                    amount=int(item.get("amount", 0) or 0),
                )
            )

        subtotal = int(data.get("subtotal", 0) or 0)
        tax = int(data.get("tax", 0) or 0)
        total = int(data.get("total", 0) or 0)

        # 小計と消費税が0の場合、合計から逆算（消費税10%として計算）
        if total > 0 and subtotal == 0 and tax == 0:
            subtotal = int(total / 1.1)
            tax = total - subtotal

        return DeliveryNote(
            date=data.get("date", ""),
            company_name=data.get("company_name", ""),
            slip_number=data.get("slip_number", ""),
            items=items,
            subtotal=subtotal,
            tax=tax,
            total=total,
            payment_received=int(data.get("payment_received", 0) or 0),
        )


def extract_delivery_note(pdf_path: Path) -> DeliveryNote:
    """納品書PDFからデータを抽出する便利関数

    Args:
        pdf_path: 納品書PDFのパス

    Returns:
        DeliveryNote: 抽出された納品書データ
    """
    extractor = LLMExtractor()
    return extractor.extract(pdf_path)
