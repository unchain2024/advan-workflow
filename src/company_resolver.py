"""会社名候補の解決（自社名除外 + スコアリング）

LLM が伝票から拾った「会社名っぽいもの」を複数受け取り、
自社名を除外した上で、得意先マスタとの一致・伝票上の役割・LLM の確信度から
取引先として最も妥当な 1 件を選ぶ。

背景:
    伝票によっては自社が「仕入先名」欄などに別名義（例: アドバンパートナーズ）で
    載っており、単一の company_name だけ返させると自社名を取引先として拾ってしまう。
    候補を複数出させて後段で比較することで、表記の揺れに強くする。
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Optional

# 自社の別名義（法人格・英字表記のゆれは normalize で吸収するので中核部分だけ書く）
# company_config.json の company_name / own_company_aliases もこれに加えて使う
DEFAULT_OWN_COMPANY_ALIASES: tuple[str, ...] = (
    "アドバンアパレル",
    "アドバンパートナーズ",
    "ADVAN APPAREL",
    "ADVANAPPAREL",
    "ADVAN PARTNERS",
    "ADVANPARTNERS",
)

# 伝票上の役割ごとの基礎点
ROLE_SCORE_RECIPIENT = 30      # 宛先（御中）
ROLE_SCORE_ISSUER_TO_US = 20   # 発行元（宛先が自社のとき）
ROLE_SCORE_ISSUER = 5          # 発行元（宛先が自社でないとき）
ROLE_SCORE_SUPPLIER_BOX = 5    # 仕入先欄
ROLE_SCORE_BRAND = -20         # ブランド名
MASTER_MATCH_SCORE = 100       # 得意先マスタに一致

_LEGAL_FORMS_JP = r"株式会社|有限会社|合同会社|合資会社|合名会社|\(株\)|（株）|\(有\)|（有）|㈱|㈲"
_LEGAL_FORMS_EN = r"CO\.?\s*,?\s*LTD\.?|CORPORATION|LIMITED|INC\.?|CORP\.?|LTD\.?|L\.?L\.?C\.?"
_HONORIFICS = r"御中|様|殿"
_PUNCT = r"[\s\,、。・/／\-‐－_'’\"“”()（）\[\]【】「」『』&＆]"


def normalize_for_similarity(name: str) -> str:
    """類似判定用の正規化

    NFKC → 法人格(日/英)・敬称を除去 → 空白/記号を除去 → 大文字化。
    例:
        "CLANE DESIGN CO.,LTD" → "CLANEDESIGN"
        "gf.A㈱/CLANE DESIGN CO.,LTD" → "GF.ACLANEDESIGN"
        ("." は gf.A / D.O.N のように名前の一部なので残す)
        "（株）アダストリア　HARE事業部" → "アダストリアHARE事業部"
    """
    if not name:
        return ""
    n = unicodedata.normalize("NFKC", str(name))
    n = re.sub(_LEGAL_FORMS_JP, "", n)
    n = re.sub(_LEGAL_FORMS_EN, "", n, flags=re.IGNORECASE)
    n = re.sub(_HONORIFICS, "", n)
    n = re.sub(_PUNCT, "", n)
    return n.strip().upper()


def own_company_names() -> list[str]:
    """自社名（別名義含む）の一覧

    優先順: company_config.json の company_name / own_company_aliases → コード内既定値。
    設定読込に失敗しても既定値は必ず返す。
    """
    names: list[str] = list(DEFAULT_OWN_COMPANY_ALIASES)
    try:
        from .config import load_company_config

        cfg = load_company_config() or {}
        main = cfg.get("company_name")
        if main:
            names.append(str(main))
        extra = cfg.get("own_company_aliases") or []
        if isinstance(extra, (list, tuple)):
            names.extend(str(x) for x in extra if x)
    except Exception as e:  # 設定が読めなくても既定値で動かす
        print(f"    [company_resolver] 自社名設定の読込失敗（既定値で継続）: {e}")
    return names


def is_own_company(name: str, own_names: Optional[list[str]] = None) -> bool:
    """自社名（別名義含む）に該当するか。正規化後の包含で判定（双方向）"""
    n = normalize_for_similarity(name)
    if not n:
        return False
    for own in own_names if own_names is not None else own_company_names():
        o = normalize_for_similarity(own)
        if not o:
            continue
        if n == o:
            return True
        # 包含判定は短い側が 3 文字以上のときだけ（"A" のような断片を巻き込まない）
        if min(len(o), len(n)) >= 3 and (o in n or n in o):
            return True
    return False


@dataclass
class CompanyCandidate:
    name: str
    role: str = "その他"        # 宛先 | 発行元 | 仕入先欄 | ブランド | その他
    confidence: float = 0.5
    is_own: bool = False
    master_match: Optional[str] = None
    score: float = 0.0
    reasons: list[str] = field(default_factory=list)


def _parse_candidates(extracted: dict) -> list[CompanyCandidate]:
    """LLM 出力から候補リストを作る（company_candidates 優先、無ければ company_name）"""
    out: list[CompanyCandidate] = []
    raw = extracted.get("company_candidates")
    if isinstance(raw, list):
        for c in raw:
            if isinstance(c, str):
                name, role, conf = c, "その他", 0.5
            elif isinstance(c, dict):
                name = c.get("name") or c.get("company_name") or ""
                role = str(c.get("role") or "その他")
                try:
                    conf = float(c.get("confidence", 0.5) or 0.0)
                except (TypeError, ValueError):
                    conf = 0.5
            else:
                continue
            name = re.sub(_HONORIFICS + r"\s*$", "", str(name)).strip()
            if name:
                out.append(CompanyCandidate(name=name, role=role, confidence=max(0.0, min(1.0, conf))))

    # 後方互換: 単一 company_name も候補に含める（既に同名があれば加えない）
    single = (extracted.get("company_name") or "").strip()
    if single:
        n = normalize_for_similarity(single)
        if n and all(normalize_for_similarity(c.name) != n for c in out):
            out.append(CompanyCandidate(name=single, role="その他", confidence=0.6))
    return out


def resolve_company_name(
    extracted: dict,
    domain: str = "sales",
    filename: Optional[str] = None,
    master_names: Optional[list[str]] = None,
) -> tuple[str, list[CompanyCandidate]]:
    """候補から取引先名を 1 件選ぶ

    Args:
        extracted: LLM の生 JSON（company_candidates / company_name を含む）
        domain: 'sales' | 'purchase'（マスタ照合先）
        filename: 元ファイル名（親/子 disambiguation のヒント）
        master_names: マスタ候補（テスト用に差し替え可。None なら DB から取得）

    Returns:
        (選ばれた会社名, スコア付き全候補)。候補が全て自社名なら ("", 候補)
    """
    candidates = _parse_candidates(extracted)
    if not candidates:
        return "", []

    own_names = own_company_names()
    for c in candidates:
        c.is_own = is_own_company(c.name, own_names)

    # 宛先が自社か（= 相手が発行した伝票か）
    addressed_to_us = any(c.is_own and c.role in ("宛先", "仕入先欄") for c in candidates)

    from .sheets_client import match_company_name_with_filename

    # マスタ照合: master_names 指定時（テスト用）はそのリストで、未指定なら
    # DB の正式名＋別名（aliases）を見る sheets_client の getter で照合する
    if master_names is None:
        from .sheets_client import (
            get_canonical_company_name,
            get_canonical_purchase_company_name,
        )

        _getter = (
            get_canonical_purchase_company_name if domain == "purchase" else get_canonical_company_name
        )

        def _match(name: str) -> Optional[str]:
            try:
                return _getter(name, filename=filename)
            except Exception as e:
                print(f"    [company_resolver] マスタ照合失敗（照合なしで継続）: {e}")
                return None
    else:
        def _match(name: str) -> Optional[str]:
            return match_company_name_with_filename(name, master_names, filename=filename)

    # 正規化後に同名の候補は 1 つにまとめる（先頭を残し、確信度は最大値）
    merged: dict[str, CompanyCandidate] = {}
    for c in candidates:
        key = normalize_for_similarity(c.name)
        if key in merged:
            merged[key].confidence = max(merged[key].confidence, c.confidence)
            if merged[key].role == "その他" and c.role != "その他":
                merged[key].role = c.role
        else:
            merged[key] = c
    candidates = list(merged.values())

    for c in candidates:
        if c.is_own:
            c.score = float("-inf")
            c.reasons.append("自社名")
            continue
        score = 0.0
        m = _match(c.name)
        if m:
            c.master_match = m
            score += MASTER_MATCH_SCORE
            c.reasons.append(f"マスタ一致:{m}")
        if c.role == "宛先":
            score += ROLE_SCORE_RECIPIENT
        elif c.role == "発行元":
            score += ROLE_SCORE_ISSUER_TO_US if addressed_to_us else ROLE_SCORE_ISSUER
        elif c.role == "仕入先欄":
            score += ROLE_SCORE_SUPPLIER_BOX
        elif c.role == "ブランド":
            score += ROLE_SCORE_BRAND
        c.reasons.append(f"役割:{c.role}")
        score += c.confidence * 10
        c.score = score

    viable = [c for c in candidates if not c.is_own]
    if not viable:
        print("    [company_resolver] 候補が全て自社名 → 会社名なし")
        return "", candidates

    # 安定ソート（同点は出現順）
    best = max(viable, key=lambda c: c.score)
    summary = ", ".join(
        f"{c.name}({'自社' if c.is_own else int(c.score)})" for c in candidates
    )
    print(f"    [company_resolver] 候補: {summary} → '{best.name}'")
    return best.name, candidates
