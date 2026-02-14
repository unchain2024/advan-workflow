"""納品書データの構造定義

実際の抽出処理はllm_extractor.pyで行う
"""
from dataclasses import dataclass, field


@dataclass
class DeliveryItem:
    """納品書の明細行"""
    slip_number: str  # 伝票番号
    product_code: str  # 商品コード
    product_name: str  # 品名
    quantity: int  # 数量
    unit_price: int  # 単価
    amount: int  # 金額
    date: str = ""  # 日付（月次請求書で個別の納品日を表示するため）


@dataclass
class DeliveryNote:
    """納品書データ"""
    date: str  # 日付（YYYY/MM/DD）
    company_name: str  # 相手会社名
    slip_number: str  # 伝票番号
    items: list[DeliveryItem] = field(default_factory=list)
    subtotal: int = 0  # 売上額（税抜）
    tax: int = 0  # 消費税額
    total: int = 0  # 合計金額（税込）
    payment_received: int = 0  # 御入金額

    def calculate_totals(self):
        """明細から合計を再計算"""
        if self.items:
            self.subtotal = sum(item.amount for item in self.items)
        if self.subtotal > 0 and self.tax == 0:
            self.tax = int(self.subtotal * 0.1)  # 消費税10%
        if self.total == 0:
            self.total = self.subtotal + self.tax
