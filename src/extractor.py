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
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Optional

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


# ===== 1 PDF 複数伝票の分割 =====

def _norm_slip(slip: Any) -> str:
    """伝票番号比較用の正規化（全半角・空白・ハイフンの差を吸収）"""
    s = unicodedata.normalize("NFKC", str(slip or ""))
    return re.sub(r"[\s\-_]", "", s).upper()


def _same_slip(a: str, b: str) -> bool:
    """同一伝票とみなすか（OCR で末尾に枝番が付くケースは同一扱い）"""
    if not a or not b:
        return False
    return a == b or a.startswith(b) or b.startswith(a)


def _page_summary(raw: Any) -> tuple[str, bool]:
    """ページ単位の生 JSON → (伝票番号, 内容があるか)"""
    entry = raw
    if isinstance(raw, list):
        entry = next((e for e in raw if isinstance(e, dict)), None)
    if not isinstance(entry, dict):
        return "", False
    slip = str(entry.get("slip_number") or "").strip()
    items = entry.get("items") or []
    total = entry.get("total") or entry.get("subtotal") or 0
    has_content = bool(items) or bool(slip) or bool(total)
    return slip, has_content


def extract_notes_by_slip(
    impl: Any,
    images: list,
    filename: Optional[str] = None,
    max_workers: int = 3,
) -> list[tuple[DeliveryNote, list[int]]]:
    """ページ群を伝票番号で区切り、伝票ごとに DeliveryNote を作る

    手順:
      1. 各ページを個別に抽出して伝票番号を得る（並列）
      2. 連続ページを伝票番号でグルーピング
         - 伝票番号が空のページ（続きページ・白紙）は直前のグループに付ける
         - 伝票番号が変わったら新しいグループ
      3. グループが 1 つなら PDF 全体を従来どおり 1 回で抽出（既存精度を維持）
         複数なら、1 ページのグループはページ抽出結果を再利用、
         複数ページのグループはそのページ群だけをまとめて再抽出

    impl は _extract_raw(images, allow_empty) / _postprocess(raw, filename) /
    extract_from_images(images, filename) を持つ抽出器。
    """
    if len(images) <= 1:
        return [(impl.extract_from_images(images, filename=filename), list(range(len(images))))]

    def _one(img):
        try:
            return impl._extract_raw([img], max_retries=3, allow_empty=True)
        except Exception as e:  # ページ単位の失敗は「不明ページ」として扱う
            print(f"    [multi-slip] ページ抽出失敗（グループ再抽出で補う）: {e}")
            return None

    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        raws = list(ex.map(_one, images))

    groups: list[dict] = []  # {"slip": str, "pages": [idx], "raws": [raw]}
    for idx, raw in enumerate(raws):
        slip, has_content = _page_summary(raw)
        nslip = _norm_slip(slip)
        if not groups:
            groups.append({"slip": nslip, "pages": [idx], "raws": [raw]})
            continue
        cur = groups[-1]
        if nslip and cur["slip"] and not _same_slip(nslip, cur["slip"]):
            groups.append({"slip": nslip, "pages": [idx], "raws": [raw]})
        else:
            if nslip and not cur["slip"]:
                cur["slip"] = nslip
            cur["pages"].append(idx)
            cur["raws"].append(raw)

    summary = " / ".join(
        f"伝票{g['slip'] or '?'}:p{[p + 1 for p in g['pages']]}" for g in groups
    )
    print(f"  [multi-slip] {len(images)}ページ → {len(groups)}伝票 ({summary})")

    if len(groups) == 1:
        # 従来どおり PDF 全体を 1 回で抽出（複数ページ 1 伝票の既存挙動を維持）
        return [(impl.extract_from_images(images, filename=filename), list(range(len(images))))]

    results: list[tuple[DeliveryNote, list[int]]] = []
    for g in groups:
        pages = g["pages"]
        if len(pages) == 1 and g["raws"][0]:
            dn = impl._postprocess(g["raws"][0], filename=filename)
        else:
            dn = impl.extract_from_images([images[i] for i in pages], filename=filename)
        results.append((dn, pages))
    return results


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
        target_name = original_filename or pdf_path.name
        dn = self._impl.extract(pdf_path, filename=target_name)
        dn = apply_filename_unit_price_override(target_name, dn)
        return dn

    def extract_all(
        self,
        pdf_path: Path,
        original_filename: Optional[str] = None,
    ) -> list[tuple[DeliveryNote, list[int]]]:
        """PDF 内の伝票を伝票番号単位で分割して抽出（1 PDF 複数伝票対応）

        Returns:
            [(DeliveryNote, 0-based ページ番号リスト), ...] を PDF 内の出現順で返す。
            1 ページ / 1 伝票の PDF では extract() と同じ結果が 1 件返る。
        """
        target_name = original_filename or pdf_path.name
        images = self._impl._pdf_to_images(pdf_path)
        print(f"  PDF → {len(images)} ページの画像に変換 ({self._backend})")
        notes = extract_notes_by_slip(self._impl, images, filename=target_name)
        return [
            (apply_filename_unit_price_override(target_name, dn), pages)
            for dn, pages in notes
        ]


def extract_delivery_note(
    pdf_path: Path,
    backend: Optional[str] = None,
    original_filename: Optional[str] = None,
) -> DeliveryNote:
    """便利関数: 1行で抽出+補正"""
    return UnifiedExtractor(backend).extract(pdf_path, original_filename)
