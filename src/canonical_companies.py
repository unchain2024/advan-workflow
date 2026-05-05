"""会社名 canonical マスター（ハードコード）

【設計方針】
- DB を source of truth とするため、シートに依存せず動作する canonical 会社名リスト
- このリストにマッチしない会社は DB に自動追加されず、フロントの会社選択ピッカーに戻される
- 新規取引先が増えたら、このファイルに追加してデプロイ（または将来 DB 管理に拡張）

【生成元】
scripts/dump_canonicals.py を実行して 2025年 / 2026年シートから抽出。
section header（【ライフスタイル】、合計 等）は手動で除外済み。

【ドメイン】
- sales: 売上集計表（請求管理）の会社
- purchase: 仕入れ管理の会社
"""
from __future__ import annotations

from typing import Final, Optional

# ===== 売上 (sales) canonical company list =====
# 売上集計表 Column A の会社名（57件、2026年時点）
# section header と合計行は除外済み
SALES_CANONICALS: Final[tuple[str, ...]] = (
    'ADASTRIA ASIA',
    'ADASTRIA KOREA',
    'ADASTRIA TAIWAN',
    'BASE（会社の自社サイト）',
    'ONELINES',
    'ReeBlue Myanmar',
    'gf.A㈱',
    'アマゾンドットコムジャパン',
    'アークエンタープライズ',
    'カリマーインターナショナル㈱',
    'ジュピターショップチャンネル㈱/BUG',
    'ジュピターショップチャンネル㈱/アパレル',
    'ダックプライスサービス㈱',
    'ナチュラルケミストリーラボ㈱',
    'ファイブトーキョー㈱',
    'フラッグス㈱',
    'プランナイン',
    'マークスタイラー㈱',
    '㈱KAMAKURA',
    '㈱RIH',
    '㈱SIM',
    '㈱カニワトーキョー',
    '㈱シップス',
    '㈱ジュン',
    '㈱デイトナインターナショナル',
    '㈱デイトナインターナショナル/フリークストア',
    '㈱バーンデストローズジャパンリミテッド',
    '㈱プランナーズ21SYJ',
    '㈱マクアケ',
    '㈱ミスターハリウッド',
    '㈱ユナイテッドアローズ',
    '㈱リンチプロダクト',
    '㈱高荘',
    '三井物産インターファッション㈱　上海売り',
    '三菱商事ファッション（株）',
    '北高㈱',
    '太子織物',
    '日鉄住金物産㈱香港',
    '有延商店',
    '機能素材',
    '牧田鉄工㈱',
    '鈴木加工',
    '（株）アダストリア',
    '（株）アダストリア　HARE事業部',
    '（株）アダストリア　ショッパー',
    '（株）アンフィル',
    '（株）インス',
    '（株）インス/非課税',
    '（株）キュー',
    '（株）トリコ',
    '（株）ドン・キホーテ',
    '（株）バロックジャパンリミテッド',
    '（株）バロックジャパンリミテッド/YS/サンプル',
    '（株）バロックジャパンリミテッド/サンプル',
    '（株）バロックジャパンリミテッド/ライセンス',
    '（株）パル/アパレル',
    '（株）パル/ライフスタイル',
)

# ===== 仕入 (purchase) canonical company list =====
# 仕入れ管理表 Column A の会社名（94件、2026年時点）
# section header（課税事業者、課税仕入れ合計、相手方、繰越 等）は除外済み
PURCHASE_CANONICALS: Final[tuple[str, ...]] = (
    'Cherry',
    'DALIAN',
    'DALIAN TRADE',
    'DONGGUAN HANDBAG',
    'HongJunFan/Jiayichen',
    'KaStone',
    'Kagawa',
    'LIAONING/HUARONG',
    'LIYONG',
    'Nantong Worldrun',
    'QIANZHUO TRADING',
    'REAL MARKETING',
    'RIHO(CHIC K.S.)',
    'SHANGHAI FEI CHUAN',
    'SUZHOU TEBGFEI',
    'TEXPRO（検品）',
    'Teamplan',
    "Y's 青島（検品）",
    "Y's 香港国際物流（検品）",
    'アパレルエンドー(有)',
    'エイコー㈱',
    'カイハラ㈱',
    'キャブ㈱',
    'コスモテキスタイル㈱',
    'スタイレム瀧定大阪（株）',
    'ダックプライスサービス㈱',
    'テンタック（株）',
    'ナクシス㈱',
    'マツダ紙工業㈱',
    'ミュウソンクールブ',
    'リーウェイジャパン㈱',
    'ログズ㈱',
    '㈱D.O.N',
    '㈱RIH/ライセンス料',
    '㈱SEVEN',
    '㈱WHOVAL',
    '㈱アサヒリンク',
    '㈱エーコー商会',
    '㈱オアシスライフスタイルグループ',
    '㈱カケン検品センター',
    '㈱カゲヤマ',
    '㈱クラウンクリエイティブ',
    '㈱セブンプラス',
    '㈱ツーゴッツ',
    '㈱トセジマガーメント',
    '㈱トリップモード',
    '㈱ネオインターナショナル',
    '㈱フクイ',
    '㈱フラッグスインク',
    '㈱ミライアクト',
    '㈱リンクタキセイ',
    '㈱ロジック',
    '㈱晃立',
    '㈱有延商店',
    '㈱植山テキスタイル　　　（丸和商事㈱）',
    '㈱滝口商店',
    '㈱鈴木加工',
    '㈲ファーイーストコネクション',
    '㈲リーベル',
    '㈲ﾌｧｯｼｮﾝﾌﾟﾚｽｶﾈﾀﾞ',
    '三浦　勇太',
    '北高㈱',
    '双日ファッション（株）',
    '吉岡（株）東京',
    '大川容器㈱',
    '天鷹（検品）',
    '宇仁繊維㈱',
    '岩崎朋彦',
    '島田商事㈱',
    '新栄物流㈱',
    '日ノ出産業㈱',
    '日新運輸（検品）',
    '日本マート㈱',
    '東京吉岡（株）',
    '桑原',
    '桑村繊維㈱',
    '機能素材㈱',
    '浪速運送㈱',
    '清原（株）',
    '瀧定名古屋（株）',
    '菱友商事㈱',
    '西巻印刷㈱',
    '青島天星源（ＴＸＹ）',
    '香栄興業㈱',
    '（有)リオン',
    '（有）ウィズユウ',
    '（有）オーク物流',
    '（有）ﾌｧｯｼｮﾝｳｨﾝ',
    '（株）サンウェル',
    '（株）ビーエムマーク',
    '（株）マテックス',
    '（株）ヴェスト',
    '（株）三景東京',
    'ＹＫＫスナップファスナー（株）',
)


# ===== 仕入の課税/非課税デフォルト (Phase 5a) =====
# 出典: 仕入シートの A 列セクション構造
#   行 4-75   = 課税仕入 (生地屋系メイン)         → True
#   行 79-95  = 非課税仕入 (海外直送系)           → False
#   行 100-173 = 課税外注 (検品/サービス系)       → True
#   行 177-181 = 非課税検品 (海外検品業務)        → False
#
# 注意: シートの分類は完璧ではない (業務側の確認で確認済)。
# - 同じ会社でも国内分=課税、海外直送分=非課税が混在するケースあり (主に付属系)
# - そのような場合は LLM 抽出 + ユーザ手動編集 (Phase 5d) に委ねる
# - ここに登録された会社は LLM 抽出値を上書きする (Phase 5b)
PURCHASE_TAXABILITY: Final[dict[str, bool]] = {
    # 課税仕入 (生地屋系メイン, 行 4-75)
    '菱友商事㈱': True,
    'カイハラ㈱': True,
    '双日ファッション（株）': True,
    '（株）サンウェル': True,
    '瀧定名古屋（株）': True,
    'スタイレム瀧定大阪（株）': True,
    '㈱ミライアクト': True,
    '桑村繊維㈱': True,
    '㈱カゲヤマ': True,
    '㈱オアシスライフスタイルグループ': True,
    '㈱植山テキスタイル　　　（丸和商事㈱）': True,
    '宇仁繊維㈱': True,
    'コスモテキスタイル㈱': True,
    '北高㈱': True,
    '㈱有延商店': True,
    '㈱ネオインターナショナル': True,
    'ナクシス㈱': True,
    'ＹＫＫスナップファスナー（株）': True,
    '（株）ヴェスト': True,
    '㈱セブンプラス': True,
    '（株）三景東京': True,
    '吉岡（株）東京': True,
    '（株）ビーエムマーク': True,
    '東京吉岡（株）': True,
    '清原（株）': True,
    '㈱フクイ': True,
    'テンタック（株）': True,
    '（株）マテックス': True,
    'リーウェイジャパン㈱': True,
    '日本マート㈱': True,
    'エイコー㈱': True,
    '日ノ出産業㈱': True,
    '㈱リンクタキセイ': True,
    '島田商事㈱': True,
    '㈱SEVEN': True,
    # 課税外注 (検品/サービス系, 行 100-173)
    '桑原': True,
    '㈲ファーイーストコネクション': True,
    '㈱鈴木加工': True,
    '㈱晃立': True,
    '㈱WHOVAL': True,
    '香栄興業㈱': True,
    '浪速運送㈱': True,
    '三浦　勇太': True,
    '㈲ﾌｧｯｼｮﾝﾌﾟﾚｽｶﾈﾀﾞ': True,
    '㈱トセジマガーメント': True,
    '㈱カケン検品センター': True,
    '㈱ロジック': True,
    '大川容器㈱': True,
    '西巻印刷㈱': True,
    '㈱RIH/ライセンス料': True,
    'ログズ㈱': True,
    '㈱エーコー商会': True,
    '機能素材㈱': True,
    'ダックプライスサービス㈱': True,
    '㈱クラウンクリエイティブ': True,
    '㈲リーベル': True,
    'アパレルエンドー(有)': True,
    '岩崎朋彦': True,
    '㈱ツーゴッツ': True,
    '（有)リオン': True,
    'ミュウソンクールブ': True,
    '（有）ﾌｧｯｼｮﾝｳｨﾝ': True,
    '㈱フラッグスインク': True,
    '㈱滝口商店': True,
    '（有）ウィズユウ': True,
    '新栄物流㈱': True,
    'マツダ紙工業㈱': True,
    '（有）オーク物流': True,
    'キャブ㈱': True,
    '㈱アサヒリンク': True,
    '㈱D.O.N': True,
    '㈱トリップモード': True,
    # 非課税仕入 (海外直送系, 行 79-95)
    'Teamplan': False,
    '青島天星源（ＴＸＹ）': False,
    'DALIAN': False,
    'LIAONING/HUARONG': False,
    'REAL MARKETING': False,
    'DONGGUAN HANDBAG': False,
    'RIHO(CHIC K.S.)': False,
    'KaStone': False,
    'DALIAN TRADE': False,
    'SUZHOU TEBGFEI': False,
    'LIYONG': False,
    'Kagawa': False,
    'HongJunFan/Jiayichen': False,
    'Cherry': False,
    'SHANGHAI FEI CHUAN': False,
    'Nantong Worldrun': False,
    'QIANZHUO TRADING': False,
    # 非課税検品 (海外検品業務, 行 177-181)
    '天鷹（検品）': False,
    '日新運輸（検品）': False,
    "Y's 香港国際物流（検品）": False,
    "Y's 青島（検品）": False,
    'TEXPRO（検品）': False,
}


def get_purchase_taxability_hint(canonical_name: str) -> Optional[bool]:
    """canonical 名から課税/非課税のデフォルトを取得

    Returns:
        True: 課税が確定している会社
        False: 非課税が確定している会社
        None: 曖昧（混在しうる、付属系等）→ LLM 抽出値を尊重 + ユーザ手動編集に委ねる
    """
    return PURCHASE_TAXABILITY.get(canonical_name)


def list_canonicals(domain: str = "sales") -> list[str]:
    """canonical 会社名リストを取得

    Args:
        domain: 'sales' | 'purchase'
    """
    if domain == "sales":
        return list(SALES_CANONICALS)
    if domain == "purchase":
        return list(PURCHASE_CANONICALS)
    raise ValueError(f"未知のドメイン: {domain}. 'sales' or 'purchase' を指定してください")
