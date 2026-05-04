import React from 'react';
import { Button } from '../Common/Button';
import { Message } from '../Common/Message';
import { ProcessingResult } from './ProcessingResult';
import { PDFPreviewImage } from '../Preview/PDFPreviewImage';
import { EditForm } from '../Preview/EditForm';
import { SpreadsheetSave } from '../Preview/SpreadsheetSave';
import type {
  DeliveryNote,
  CompanyInfo,
  PreviousBilling,
  CompanyNotMatchedError,
} from '../../types';

export interface CompanyGroup {
  // 識別子（再レンダリング・キー用に安定なものを使う。最初の slip_number ベース）
  id: string;
  // canonical 化された会社名（または mismatch 時の raw 抽出名）
  companyName: string;
  // このグループに属する納品書（複数枚）
  deliveryNotes: DeliveryNote[];
  // process-pdf レスポンス由来
  companyInfo: CompanyInfo | null;
  previousBilling: PreviousBilling;
  invoicePath: string; // 直近の invoice PDF
  deliveryPdfUrls: string[];
  // canonical 不一致時のピッカー
  companyMismatch: boolean;
  extractedCompanyName: string;
  companyCandidates: string[];
  suggestedCandidates: string[];
  showAllCandidates: boolean;
  // 保存・編集状態
  isSaved: boolean;
  showEditForm: boolean;
  editingNoteIndex: number;
  // idempotency
  requestId: string;
}

interface Props {
  group: CompanyGroup;
  groupIndex: number;
  totalGroups: number;
  selectedYear: number;
  selectedMonth: number;
  salesPerson: string;
  onSelectCompany: (groupIndex: number, name: string) => void;
  onSetShowAllCandidates: (groupIndex: number, show: boolean) => void;
  onRegenerate: (
    groupIndex: number,
    data: {
      deliveryNote: DeliveryNote;
      companyInfo: CompanyInfo | null;
      previousBilling: PreviousBilling;
    }
  ) => void;
  onSaveCompanyMismatch: (groupIndex: number, info: CompanyNotMatchedError) => void;
  onSaveComplete: (groupIndex: number) => void;
  onSetEditingNoteIndex: (groupIndex: number, idx: number) => void;
  onSetShowEditForm: (groupIndex: number, show: boolean) => void;
}

export const CompanyGroupSection: React.FC<Props> = ({
  group,
  groupIndex,
  totalGroups,
  selectedYear,
  selectedMonth,
  salesPerson,
  onSelectCompany,
  onSetShowAllCandidates,
  onRegenerate,
  onSaveCompanyMismatch,
  onSaveComplete,
  onSetEditingNoteIndex,
  onSetShowEditForm,
}) => {
  // グループ内累積（複数納品書の合計）
  const cumulativeSubtotal = group.deliveryNotes.reduce((s, n) => s + n.subtotal, 0);
  const cumulativeTax = group.deliveryNotes.reduce((s, n) => s + n.tax, 0);
  const cumulativeTotal = group.deliveryNotes.reduce((s, n) => s + n.subtotal + n.tax, 0);
  const cumulativeItemsCount = group.deliveryNotes.reduce((s, n) => s + n.items.length, 0);
  const cumulativeItems = group.deliveryNotes.flatMap((n) => n.items);

  const editTargetNote =
    group.deliveryNotes.length > 1
      ? group.deliveryNotes[group.editingNoteIndex] ?? group.deliveryNotes[0]
      : group.deliveryNotes[0];

  const isMultiGroup = totalGroups > 1;

  return (
    <div className={isMultiGroup ? 'mt-8 border-2 border-gray-300 rounded-xl p-6 bg-gray-50' : 'mt-8'}>
      {isMultiGroup && (
        <div className="mb-4 pb-3 border-b border-gray-300">
          <h2 className="text-2xl font-bold text-gray-800">
            グループ {groupIndex + 1} / {totalGroups}: {group.companyName || group.extractedCompanyName}
          </h2>
          <p className="text-sm text-gray-600 mt-1">
            {group.deliveryNotes.length} 件の納品書 / 合計 ¥{cumulativeTotal.toLocaleString()}
            {group.isSaved && <span className="ml-3 text-green-600 font-medium">✓ 保存済</span>}
          </p>
        </div>
      )}

      {/* 会社ピッカー (canonical 不一致時) */}
      {group.companyMismatch && group.companyCandidates.length > 0 && (
        <div className="mb-6">
          <Message type="error">
            <p className="font-semibold mb-2">
              会社名「{group.extractedCompanyName}」がスプレッドシートに見つかりません。正しい会社名を選択してください：
            </p>

            {group.suggestedCandidates.length > 0 && (
              <div className="mt-3">
                <p className="text-sm font-medium text-gray-600 mb-1">類似する会社名：</p>
                <div className="space-y-2">
                  {group.suggestedCandidates.map((name) => (
                    <button
                      key={name}
                      onClick={() => onSelectCompany(groupIndex, name)}
                      className="block w-full text-left px-4 py-2 bg-blue-50 border-2 border-blue-400 rounded-lg hover:bg-blue-100 transition-colors text-gray-800 font-medium"
                    >
                      {name}
                    </button>
                  ))}
                </div>
              </div>
            )}

            <div className="mt-3">
              <button
                onClick={() => onSetShowAllCandidates(groupIndex, !group.showAllCandidates)}
                className="text-sm text-blue-600 hover:text-blue-800 font-medium cursor-pointer"
              >
                {group.showAllCandidates
                  ? '▲ 閉じる'
                  : `▼ すべての会社名を表示（${group.companyCandidates.length}件）`}
              </button>
              {group.showAllCandidates && (
                <div className="space-y-2 mt-2 max-h-96 overflow-y-auto">
                  {group.companyCandidates
                    .filter((name) => !group.suggestedCandidates.includes(name))
                    .map((name) => (
                      <button
                        key={name}
                        onClick={() => onSelectCompany(groupIndex, name)}
                        className="block w-full text-left px-4 py-2 bg-white border border-gray-300 rounded-lg hover:bg-blue-50 hover:border-blue-400 transition-colors text-gray-800"
                      >
                        {name}
                      </button>
                    ))}
                </div>
              )}
            </div>
          </Message>
        </div>
      )}

      {editTargetNote && (
        <>
          <ProcessingResult
            deliveryNote={editTargetNote}
            companyInfo={group.companyInfo}
            previousBilling={group.previousBilling}
            cumulativeSubtotal={cumulativeSubtotal}
            cumulativeTax={cumulativeTax}
            cumulativeTotal={cumulativeTotal}
            cumulativeItemsCount={cumulativeItemsCount}
            cumulativeItems={cumulativeItems}
          />

          {group.invoicePath && (
            <PDFPreviewImage
              deliveryPdfUrls={group.deliveryPdfUrls}
              invoicePdfUrl={group.invoicePath}
            />
          )}

          {group.invoicePath && !group.showEditForm && (
            <div className="mt-6 grid grid-cols-4 gap-4">
              <Button
                onClick={() => {
                  onSetEditingNoteIndex(groupIndex, group.deliveryNotes.length - 1);
                  onSetShowEditForm(groupIndex, true);
                }}
                variant="secondary"
              >
                内容を編集
              </Button>
            </div>
          )}

          {group.showEditForm && (
            <div>
              {group.deliveryNotes.length > 1 && (
                <div className="mt-6 mb-4">
                  <label className="block text-sm font-semibold text-gray-700 mb-2">
                    編集する納品書を選択:
                  </label>
                  <select
                    value={group.editingNoteIndex}
                    onChange={(e) => onSetEditingNoteIndex(groupIndex, Number(e.target.value))}
                    className="border border-gray-300 rounded-lg px-3 py-2 text-gray-700 focus:outline-none focus:ring-2 focus:ring-red-400 focus:border-transparent"
                  >
                    {group.deliveryNotes.map((note, idx) => (
                      <option key={idx} value={idx}>
                        {idx + 1}. 伝票 {note.slip_number || '不明'} - ¥{note.subtotal.toLocaleString()}
                      </option>
                    ))}
                  </select>
                </div>
              )}

              <EditForm
                key={editTargetNote.slip_number}
                deliveryNote={editTargetNote}
                companyInfo={group.companyInfo}
                previousBilling={group.previousBilling}
                onRegenerate={async (data) => {
                  await onRegenerate(groupIndex, {
                    deliveryNote: data.deliveryNote!,
                    companyInfo: data.companyInfo,
                    previousBilling: data.previousBilling!,
                  });
                }}
                onCancel={() => onSetShowEditForm(groupIndex, false)}
              />
            </div>
          )}

          {group.invoicePath && !group.showEditForm && !group.companyMismatch && (
            <SpreadsheetSave
              key={group.requestId}
              allDeliveryNotes={group.deliveryNotes}
              deliveryNote={editTargetNote}
              previousBilling={group.previousBilling}
              yearMonth={`${selectedYear}-${String(selectedMonth).padStart(2, '0')}`}
              isSaved={group.isSaved}
              onSaveComplete={() => onSaveComplete(groupIndex)}
              invoicePath={group.invoicePath}
              cumulativeSubtotal={cumulativeSubtotal}
              cumulativeTax={cumulativeTax}
              salesPerson={salesPerson}
              onCompanyMismatch={(info) => onSaveCompanyMismatch(groupIndex, info)}
            />
          )}
        </>
      )}
    </div>
  );
};
