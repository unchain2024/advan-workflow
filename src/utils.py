"""ユーティリティ関数"""
from datetime import datetime
from typing import Optional


def calculate_target_month(delivery_date: str, closing_day: str) -> str:
    """締め日に基づいて記入対象月を計算

    ロジック:
    - 「月末」締め: 納品日の月に記入
    - 「N日」締め: 納品日 <= N日 → その月、納品日 > N日 → 翌月

    例（20日締め）:
    - 2月6日 → 2月（1/21-2/20の期間）
    - 2月25日 → 3月（2/21-3/20の期間）

    Args:
        delivery_date: 納品日（YYYY/MM/DD形式）
        closing_day: 締め日（「月末」または「N日」形式）

    Returns:
        str: 記入対象年月（YYYY年M月形式）
    """
    # 納品日をパース
    try:
        date_obj = datetime.strptime(delivery_date, "%Y/%m/%d")
    except ValueError:
        # パースできない場合はそのまま納品月を返す
        try:
            parts = delivery_date.split('/')
            if len(parts) >= 2:
                year = int(parts[0])
                month = int(parts[1])
                return f"{year}年{month}月"
        except:
            pass
        return ""

    year = date_obj.year
    month = date_obj.month
    day = date_obj.day

    # 締め日が「月末」の場合
    if "月末" in closing_day or closing_day == "末日":
        return f"{year}年{month}月"

    # 締め日が「N日」形式の場合
    try:
        # 「20日」→ 20 を抽出
        closing_day_num = int(closing_day.replace("日", "").strip())

        # 納品日が締め日以降の場合は翌月に記入
        if day > closing_day_num:
            # 翌月を計算
            if month == 12:
                year += 1
                month = 1
            else:
                month += 1

        return f"{year}年{month}月"

    except ValueError:
        # パースできない場合は納品月をそのまま返す
        return f"{year}年{month}月"


def parse_year_month(date_str: str) -> str:
    """日付文字列をYYYY年M月形式に変換

    Args:
        date_str: 日付文字列（YYYY/MM/DD形式）

    Returns:
        str: YYYY年M月形式の文字列（例: "2025/03/01" → "2025年3月"）
    """
    parts = date_str.split('/')
    if len(parts) >= 2:
        year = int(parts[0])
        month = int(parts[1])
        return f"{year}年{month}月"
    return ""
