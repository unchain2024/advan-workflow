import React, { useState, useRef } from 'react';
import { Button } from '../Common/Button';
import { Message } from '../Common/Message';
import { MetricCard } from '../Common/MetricCard';
import { saveBilling, checkDiscrepancy } from '../../api/client';
import { useAppStore } from '../../store/useAppStore';
import type { DeliveryNote, PreviousBilling, ExistingNoteInfo } from '../../types';

interface SpreadsheetSaveProps {
  allDeliveryNotes: DeliveryNote[];
  deliveryNote: DeliveryNote;
  previousBilling: PreviousBilling;
  yearMonth: string;
  isSaved: boolean;
  onSaveComplete: () => void;
  invoicePath: string;
  cumulativeSubtotal?: number;
  cumulativeTax?: number;
  salesPerson: string;
}

export const SpreadsheetSave: React.FC<SpreadsheetSaveProps> = ({
  allDeliveryNotes,
  deliveryNote,
  previousBilling,
  yearMonth,
  isSaved,
  onSaveComplete,
  invoicePath,
  cumulativeSubtotal,
  cumulativeTax,
  salesPerson,
}) => {
  const setDiscrepancies = useAppStore((s) => s.setDiscrepancies);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const requestIdRef = useRef(crypto.randomUUID());

  // 重複確認ポップアップ
  const [showDuplicateDialog, setShowDuplicateDialog] = useState(false);
  const [duplicateNotes, setDuplicateNotes] = useState<ExistingNoteInfo[]>([]);

  // 表示用は累積値、書き込み用は個別値
  const displaySubtotal = cumulativeSubtotal ?? deliveryNote.subtotal;
  const displayTax = cumulativeTax ?? deliveryNote.tax;

  // シート既存値
  const existingSales = previousBilling.sales_amount ?? 0;
  const existingTax = previousBilling.tax_amount ?? 0;

  // 書き込み後の合計
  const afterSales = existingSales + displaySubtotal;
  const afterTax = existingTax + displayTax;

  const doSave = async (forceOverwrite: boolean) => {
    setIsLoading(true);
    setError(null);

    try {
      const notesToSend = allDeliveryNotes.length > 0 ? allDeliveryNotes : [deliveryNote];
      const response = await saveBilling({
        company_name: deliveryNote.company_name,
        year_month: yearMonth,
        delivery_notes: notesToSend,
        previous_billing: previousBilling,
        sales_person: salesPerson,
        request_id: requestIdRef.current,
        force_overwrite: forceOverwrite,
      });

      // 重複検出 → ポップアップ表示
      if (response.duplicate_conflict && response.existing_notes) {
        setDuplicateNotes(response.existing_notes);
        setShowDuplicateDialog(true);
        setIsLoading(false);
        return;
      }

      alert(response.message);
      onSaveComplete();

      // 乖離チェックを再実行
      try {
        const discResult = await checkDiscrepancy();
        setDiscrepancies(discResult.discrepancies);
      } catch (discErr) {
        console.error('乖離チェックエラー:', discErr);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : '書き込みエラーが発生しました');
    } finally {
      setIsLoading(false);
    }
  };

  const handleSave = () => doSave(false);

  const handleForceOverwrite = () => {
    setShowDuplicateDialog(false);
    doSave(true);
  };

  const handleCancelOverwrite = () => {
    setShowDuplicateDialog(false);
    setDuplicateNotes([]);
  };

  const handleDownload = () => {
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

      {/* 重複確認ポップアップ */}
      {showDuplicateDialog && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
          <div className="bg-white rounded-xl shadow-2xl max-w-2xl w-full mx-4 max-h-[80vh] overflow-y-auto">
            <div className="p-6">
              <h3 className="text-xl font-bold text-amber-700 mb-4">
                この伝票番号は既に保存されています
              </h3>

              <p className="text-gray-600 mb-4">
                以下のデータが既にDBに存在します。上書きしますか？
              </p>

              <div className="space-y-3 mb-6">
                {duplicateNotes.map((note) => (
                  <div
                    key={note.slip_number}
                    className="bg-amber-50 border border-amber-200 rounded-lg p-4"
                  >
                    <div className="flex justify-between items-start mb-2">
                      <span className="font-semibold text-gray-800">
                        伝票番号: {note.slip_number}
                      </span>
                      <span className="text-xs text-gray-500">
                        保存日時: {note.saved_at}
                      </span>
                    </div>
                    <div className="grid grid-cols-2 gap-x-4 gap-y-1 text-sm text-gray-700">
                      <div>日付: {note.date}</div>
                      <div>担当者: {note.sales_person || '—'}</div>
                      <div>小計: ¥{note.subtotal.toLocaleString()}</div>
                      <div>消費税: ¥{note.tax.toLocaleString()}</div>
                      <div className="font-semibold">
                        合計: ¥{note.total.toLocaleString()}
                      </div>
                    </div>
                  </div>
                ))}
              </div>

              <div className="flex gap-3">
                <Button
                  onClick={handleForceOverwrite}
                  variant="primary"
                  loading={isLoading}
                >
                  上書き保存する
                </Button>
                <Button
                  onClick={handleCancelOverwrite}
                  variant="secondary"
                  fullWidth
                >
                  キャンセル
                </Button>
              </div>
            </div>
          </div>
        </div>
      )}

      {!isSaved ? (
        <>
          <h2 className="text-3xl font-semibold text-gray-700 mb-4">
            売上集計表への書き込み
          </h2>

          <Message type="info" className="mb-6">
            内容を確認後、スプレッドシートに書き込んでください。
          </Message>

          {/* 既存値がある場合は内訳を表示 */}
          {existingSales > 0 || existingTax > 0 ? (
            <div className="mb-6 space-y-3">
              <div className="grid grid-cols-2 gap-4">
                <MetricCard
                  label="シート既存（発生）"
                  value={`¥${existingSales.toLocaleString()}`}
                />
                <MetricCard
                  label="シート既存（消費税）"
                  value={`¥${existingTax.toLocaleString()}`}
                />
              </div>
              <div className="grid grid-cols-2 gap-4">
                <MetricCard
                  label="＋ 今回追加（発生）"
                  value={`¥${displaySubtotal.toLocaleString()}`}
                />
                <MetricCard
                  label="＋ 今回追加（消費税）"
                  value={`¥${displayTax.toLocaleString()}`}
                />
              </div>
              <div className="border-t border-gray-300 pt-3">
                <div className="grid grid-cols-2 gap-4">
                  <MetricCard
                    label="書き込み後（発生）"
                    value={`¥${afterSales.toLocaleString()}`}
                    highlight
                  />
                  <MetricCard
                    label="書き込み後（消費税）"
                    value={`¥${afterTax.toLocaleString()}`}
                    highlight
                  />
                </div>
              </div>
            </div>
          ) : (
            <div className="grid grid-cols-2 gap-4 mb-6">
              <MetricCard
                label="発生（売上）"
                value={`¥${displaySubtotal.toLocaleString()}`}
              />
              <MetricCard
                label="消費税"
                value={`¥${displayTax.toLocaleString()}`}
              />
            </div>
          )}

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
            スプレッドシートに書き込む
          </Button>
        </>
      ) : (
        <>
          <Message type="success" className="mb-6">
            スプレッドシートへの書き込みが完了しています
          </Message>

          <div className="border-t-2 border-gray-200 my-8"></div>

          <h2 className="text-3xl font-semibold text-gray-700 mb-4">
            請求書PDFダウンロード
          </h2>

          <Button
            onClick={handleDownload}
            variant="success"
            fullWidth
          >
            請求書PDFをダウンロード
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
