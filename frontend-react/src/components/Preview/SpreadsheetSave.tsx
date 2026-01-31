import React, { useState } from 'react';
import { Button } from '../Common/Button';
import { Message } from '../Common/Message';
import { MetricCard } from '../Common/MetricCard';
import { saveBilling } from '../../api/client';
import type { DeliveryNote, PreviousBilling } from '../../types';

interface SpreadsheetSaveProps {
  deliveryNote: DeliveryNote;
  previousBilling: PreviousBilling;
  yearMonth: string;
  isSaved: boolean;
  onSaveComplete: () => void;
  invoicePath: string;
}

export const SpreadsheetSave: React.FC<SpreadsheetSaveProps> = ({
  deliveryNote,
  previousBilling,
  yearMonth,
  isSaved,
  onSaveComplete,
  invoicePath,
}) => {
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSave = async () => {
    setIsLoading(true);
    setError(null);

    try {
      const response = await saveBilling({
        company_name: deliveryNote.company_name,
        year_month: yearMonth,
        delivery_note: deliveryNote,
        previous_billing: previousBilling,
      });

      alert(response.message);
      onSaveComplete();
    } catch (err) {
      setError(err instanceof Error ? err.message : '書き込みエラーが発生しました');
    } finally {
      setIsLoading(false);
    }
  };

  const handleDownload = () => {
    // PDFファイルをダウンロード
    const link = document.createElement('a');
    link.href = invoicePath;
    link.download = invoicePath.split('/').pop() || 'invoice.pdf';
    link.target = '_blank';
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  };

  return (
    <div className="mt-8">
      <div className="border-t-2 border-gray-200 mb-8"></div>

      {!isSaved ? (
        <>
          <h2 className="text-3xl font-semibold text-gray-700 mb-4">
            📊 売上集計表への書き込み
          </h2>

          <Message type="info" className="mb-6">
            内容を確認後、スプレッドシートに書き込んでください。
          </Message>

          <div className="grid grid-cols-2 gap-4 mb-6">
            <MetricCard
              label="発生（売上）"
              value={`¥${deliveryNote.subtotal.toLocaleString()}`}
            />
            <MetricCard
              label="消費税"
              value={`¥${deliveryNote.tax.toLocaleString()}`}
            />
          </div>

          {error && (
            <Message type="error" className="mb-4">
              {error}
            </Message>
          )}

          <Button
            onClick={handleSave}
            variant="primary"
            fullWidth
            loading={isLoading}
          >
            📝 スプレッドシートに書き込む
          </Button>
        </>
      ) : (
        <>
          <Message type="success" className="mb-6">
            スプレッドシートへの書き込みが完了しています
          </Message>

          <div className="border-t-2 border-gray-200 my-8"></div>

          <h2 className="text-3xl font-semibold text-gray-700 mb-4">
            📥 請求書PDFダウンロード
          </h2>

          <Button
            onClick={handleDownload}
            variant="success"
            fullWidth
          >
            📥 請求書PDFをダウンロード
          </Button>
        </>
      )}

      {!isSaved && (
        <Message type="warning" className="mt-6">
          スプレッドシートへの書き込みを完了すると、ダウンロードボタンが表示されます
        </Message>
      )}
    </div>
  );
};
