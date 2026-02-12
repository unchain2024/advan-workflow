import React, { useState } from 'react';
import { MetricCard } from '../Common/MetricCard';
import { Accordion } from '../Common/Accordion';
import { Message } from '../Common/Message';
import type { DeliveryNote, DeliveryItem, CompanyInfo, PreviousBilling } from '../../types';

interface ProcessingResultProps {
  deliveryNote: DeliveryNote;
  companyInfo: CompanyInfo | null;
  previousBilling: PreviousBilling;
  cumulativeSubtotal?: number;
  cumulativeTax?: number;
  cumulativeTotal?: number;
  cumulativeItemsCount?: number;
  cumulativeItems?: DeliveryItem[];
}

export const ProcessingResult: React.FC<ProcessingResultProps> = ({
  deliveryNote,
  companyInfo,
  previousBilling,
  cumulativeSubtotal,
  cumulativeTax,
  cumulativeTotal,
  cumulativeItemsCount,
  cumulativeItems,
}) => {
  // 累積値があればそれを使用、なければ単一ファイルの値を使用
  const displaySubtotal = cumulativeSubtotal ?? deliveryNote.subtotal;
  const displayTax = cumulativeTax ?? deliveryNote.tax;
  const displayTotal = cumulativeTotal ?? deliveryNote.total;
  const displayItemsCount = cumulativeItemsCount ?? deliveryNote.items.length;
  const [itemsExpanded, setItemsExpanded] = useState(false);

  const totalAmount = previousBilling.carried_over + displaySubtotal + displayTax;

  return (
    <div className="space-y-6">
      {/* 成功メッセージ */}
      <Message type="success">
        <strong>データ抽出完了:</strong> {deliveryNote.company_name}
      </Message>

      {/* 抽出されたデータ */}
      <Accordion title="📋 抽出されたデータ" defaultOpen={true}>
        <div className="grid grid-cols-3 gap-4">
          {/* 列1 */}
          <div>
            <MetricCard label="会社名" value={deliveryNote.company_name} />
            <MetricCard label="日付" value={deliveryNote.date} />
          </div>

          {/* 列2 */}
          <div>
            <MetricCard label="売上" value={`¥${displaySubtotal.toLocaleString()}`} />
            <MetricCard label="消費税" value={`¥${displayTax.toLocaleString()}`} />
          </div>

          {/* 列3 */}
          <div>
            <MetricCard label="合計" value={`¥${displayTotal.toLocaleString()}`} />
            <MetricCard label="明細数" value={displayItemsCount} />
          </div>
        </div>

        {/* 明細の詳細 */}
        {(() => {
          const displayItems = cumulativeItems && cumulativeItems.length > 0 ? cumulativeItems : deliveryNote.items;
          const visibleItems = itemsExpanded ? displayItems : displayItems.slice(0, 5);
          return displayItems.length > 0 && (
            <div className="mt-4 p-4 bg-gray-50 rounded">
              <p className="font-bold mb-2">明細:</p>
              <div className="font-mono text-sm space-y-1">
                {visibleItems.map((item, index) => (
                  <div key={index}>
                    {index + 1}. {item.product_name}: {item.quantity}個 × ¥{item.unit_price.toLocaleString()} = ¥{item.amount.toLocaleString()}
                  </div>
                ))}
              </div>
              {displayItems.length > 5 && (
                <button
                  onClick={() => setItemsExpanded(!itemsExpanded)}
                  className="mt-2 text-sm text-blue-600 hover:text-blue-800 cursor-pointer font-medium"
                >
                  {itemsExpanded ? '▲ 折りたたむ' : `▼ 他 ${displayItems.length - 5} 件を表示`}
                </button>
              )}
            </div>
          );
        })()}
      </Accordion>

      {/* 会社情報 */}
      {companyInfo ? (
        <>
          <Message type="success">
            <strong>会社情報取得完了</strong>
          </Message>
          <Message type="info">
            〒{companyInfo.postal_code} {companyInfo.address}
          </Message>
          {companyInfo.department && (
            <Message type="info">
              事業部: {companyInfo.department}
            </Message>
          )}
        </>
      ) : (
        <Message type="warning">
          会社マスターに該当する会社が見つかりませんでした
        </Message>
      )}

      {/* 前月の請求情報 */}
      <Accordion title="💰 前月の請求情報" defaultOpen={false}>
        <div className="grid grid-cols-3 gap-4">
          <MetricCard
            label="前回繰越残高"
            value={`¥${previousBilling.previous_amount.toLocaleString()}`}
          />
          <MetricCard
            label="御入金額"
            value={`¥${previousBilling.payment_received.toLocaleString()}`}
          />
          <MetricCard
            label="差引繰越残高"
            value={`¥${previousBilling.carried_over.toLocaleString()}`}
          />
        </div>
      </Accordion>

      {/* 請求書生成完了 */}
      <Message type="success">
        <strong>請求書PDF生成完了</strong>
      </Message>

      {/* 請求書の内容サマリー */}
      <Accordion title="📄 請求書の内容" defaultOpen={false}>
        <div className="space-y-2">
          <p className="font-bold">今回御請求額: ¥{totalAmount.toLocaleString()}</p>
          <ul className="ml-4 space-y-1 text-gray-700">
            <li>- 差引繰越残高: ¥{previousBilling.carried_over.toLocaleString()}</li>
            <li>- 今回売上: ¥{displaySubtotal.toLocaleString()}</li>
            <li>- 消費税: ¥{displayTax.toLocaleString()}</li>
          </ul>
        </div>
      </Accordion>

      <Message type="success">
        請求書PDFの生成が完了しました！
      </Message>
    </div>
  );
};
