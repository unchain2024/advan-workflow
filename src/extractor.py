"""統合抽出器ファクトリ + 後処理

EXTRACTOR_BACKEND 環境変数で Claude/Gemini を切替。
ファイル名 @\\d+ から下代単価を上書きする後処理 (アダストリア対応) も組み込み済み。

使い方:
    from src.extractor import UnifiedExtractor

    extractor = UnifiedExtractor()
    delivery_note = extractor.extract(pdf_path)
    # ファイル名が tmp ファイル等で本来のものと違う場合:
    delivery_note = extractor.extract(tmp_path, original_filename="0218アダストリア岡部@8600.pdf")
"""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Optional

from .claude_extractor import ClaudeExtractor
from .llm_extractor import LLMExtractor
from .pdf_extractor import DeliveryNote


# 既定は claude (実測 97.3% PASS率)
DEFAULT_BACKEND = "claude"


def get_extractor(backend: Optional[str] = None):
    """指定バックエンドの抽出器インスタンスを返す。

    backend を省略すると環境変数 EXTRACTOR_BACKEND を参照。それも無ければ DEFAULT_BACKEND ("claude")。
    """
    if backend is None:
        backend = os.getenv("EXTRACTOR_BACKEND", DEFAULT_BACKEND)
    backend = backend.lower().strip()
    if backend == "claude":
        return ClaudeExtractor()
    if backend == "gemini":
        return LLMExtractor()
    raise ValueError(
        f"未知のバックエンド: '{backend}'. 'claude' or 'gemini' を指定してください"
    )


def apply_filename_unit_price_override(filename: str, dn: DeliveryNote) -> DeliveryNote:
    """ファイル名から '@\\d+' を抽出し、全明細の unit_price と amount を補正する。

    アダストリア納品伝票は PDF 本文に売価18,000等が記載されているが、
    実際の取引単価はファイル名 (例: 0218アダストリア岡部@8600.pdf) の @下代単価。
    アダストリア納品書に限定して適用する。
    """
    m = re.search(r"@(\d+)", filename or "")
    if not m:
        return dn
    if "アダストリア" not in (filename or ""):
        return dn  # 安全のためアダストリア限定
    new_unit = int(m.group(1))
    for it in dn.items:
        it.unit_price = new_unit
        it.amount = int(it.quantity) * new_unit
    # subtotal / tax / total も items 合計に揃える
    if dn.items:
        dn.subtotal = sum(int(i.amount) for i in dn.items)
        dn.tax = int(dn.subtotal * 0.1)
        dn.total = dn.subtotal + dn.tax
    return dn


class UnifiedExtractor:
    """ファクトリ + ファイル名後処理を組み込んだ統合抽出器"""

    def __init__(self, backend: Optional[str] = None):
        self._impl = get_extractor(backend)
        self._backend = backend or os.getenv("EXTRACTOR_BACKEND", DEFAULT_BACKEND)

    @property
    def backend_name(self) -> str:
        return self._backend

    def extract(
        self,
        pdf_path: Path,
        original_filename: Optional[str] = None,
    ) -> DeliveryNote:
        """PDFから DeliveryNote を抽出 + ファイル名@単価補正

        Args:
            pdf_path: 抽出対象のPDFパス（tmp ファイル可）
            original_filename: 元のファイル名（ブラウザアップロード時の名前）
                指定すると @単価判定にこちらを使う。指定しなければ pdf_path.name を使う
        """
        dn = self._impl.extract(pdf_path)
        target_name = original_filename or pdf_path.name
        dn = apply_filename_unit_price_override(target_name, dn)
        return dn


def extract_delivery_note(
    pdf_path: Path,
    backend: Optional[str] = None,
    original_filename: Optional[str] = None,
) -> DeliveryNote:
    """便利関数: 1行で抽出+補正"""
    return UnifiedExtractor(backend).extract(pdf_path, original_filename)
