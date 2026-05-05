import React from 'react';
import { Button } from '../Common/Button';
import { Message } from '../Common/Message';
import type { PurchaseInvoice, ExistingPurchaseNoteInfo } from '../../types';

export interface PurchaseGroup {
  // 識別子
  id: string;
  // canonical 化された仕入先名（または mismatch 時の raw 抽出名）
  supplierName: string;
  // このグループに属する仕入納品書（複数枚）
  invoices: PurchaseInvoice[];
  // 抽出された PDF プレビュー URL（per invoice）
  pdfUrls: string[];
  // 保存状態
  isSaved: boolean;
  isSaving: boolean;
  // 重複ダイアログ
  showDuplicateDialog: boolean;
  duplicateNotes: ExistingPurchaseNoteInfo[];
  // canonical 不一致 picker
  supplierMismatch: boolean;
  extractedSupplierName: string;
  supplierCandidates: string[];
  showAllSupplierCandidates: boolean;
  supplierFilter: string;
  // インライン編集
  editingSupplierIndex: number | null;
  // idempotency
  requestId: string;
  // エラー（per group）
  error: string | null;
  // Phase C: マージ/canonical 解決中フラグ (ピッカー連打抑制)
  isMerging?: boolean;
}

interface Props {
  group: PurchaseGroup;
  groupIndex: number;
  totalGroups: number;
  onSave: (groupIndex: number, forceOverwrite: boolean) => void;
  onCancelDuplicate: (groupIndex: number) => void;
  onSelectSupplier: (groupIndex: number, name: string) => void;
  onSetShowAllSupplierCandidates: (groupIndex: number, show: boolean) => void;
  onSetSupplierFilter: (groupIndex: number, filter: string) => void;
  onSetEditingSupplierIndex: (groupIndex: number, idx: number | null) => void;
  onEditSupplierNameForGroup: (groupIndex: number, newName: string) => void;
  // Phase 5d: 手動編集 + 行削除
  onUpdateInvoiceField: (
    groupIndex: number,
    invoiceIndex: number,
    field: 'date' | 'slip_number' | 'subtotal' | 'tax' | 'total' | 'is_taxable',
    value: string | number | boolean,
  ) => void;
  onDeleteInvoice: (groupIndex: number, invoiceIndex: number) => void;
  // Phase 5d': 明細1行ずつ削除
  onDeleteItem: (groupIndex: number, invoiceIndex: number, itemIndex: number) => void;
}

export const SupplierGroupSection: React.FC<Props> = ({
  group,
  groupIndex,
  totalGroups,
  onSave,
  onCancelDuplicate,
  onSelectSupplier,
  onSetShowAllSupplierCandidates,
  onSetSupplierFilter,
  onSetEditingSupplierIndex,
  onEditSupplierNameForGroup,
  onUpdateInvoiceField,
  onDeleteInvoice,
  onDeleteItem,
}) => {
  const totalSubtotal = group.invoices.reduce((s, i) => s + i.subtotal, 0);
  const totalTax = group.invoices.reduce((s, i) => s + i.tax, 0);
  const totalAmount = group.invoices.reduce((s, i) => s + i.total, 0);

  const isMultiGroup = totalGroups > 1;

  return (
    <div className={isMultiGroup ? 'mt-8 border-2 border-gray-300 rounded-xl p-6 bg-gray-50' : 'mt-8'}>
      {isMultiGroup && (
        <div className="mb-4 pb-3 border-b border-gray-300">
          <h2 className="text-2xl font-bold text-gray-800">
            グループ {groupIndex + 1} / {totalGroups}: {group.supplierName || group.extractedSupplierName}
          </h2>
          <p className="text-sm text-gray-600 mt-1">
            {group.invoices.length} 件の仕入納品書 / 合計 ¥{totalAmount.toLocaleString()}
            {group.isSaved && <span className="ml-3 text-green-600 font-medium">✓ 保存済</span>}
          </p>
        </div>
      )}

      {/* グループ内エラー */}
      {group.error && (
        <div className="mb-4">
          <Message type="error">{group.error}</Message>
        </div>
      )}

      {/* 仕入先ピッカー (canonical 不一致時) */}
      {group.supplierMismatch && group.supplierCandidates.length > 0 && (
        <div className="mb-6">
          <Message type="error">
            <p className="font-semibold mb-2">
              仕入先「{group.extractedSupplierName}」がマスターに登録されていません。正しい仕入先を選択してください：
            </p>

            {group.isMerging && (
              <p className="text-sm text-blue-700 font-medium">処理中...</p>
            )}

            <div className="mt-3">
              <input
                type="text"
                value={group.supplierFilter}
                onChange={(e) => onSetSupplierFilter(groupIndex, e.target.value)}
                placeholder="仕入先名で絞り込み..."
                disabled={group.isMerging}
                className="w-full border border-gray-300 rounded-lg px-3 py-2 text-gray-700 focus:outline-none focus:ring-2 focus:ring-blue-400 disabled:opacity-50"
              />
            </div>

            <div className="mt-3">
              <button
                type="button"
                onClick={() => onSetShowAllSupplierCandidates(groupIndex, !group.showAllSupplierCandidates)}
                disabled={group.isMerging}
                className="text-sm text-blue-600 hover:text-blue-800 font-medium cursor-pointer disabled:opacity-50"
              >
                {group.showAllSupplierCandidates
                  ? '▲ 折りたたむ'
                  : `▼ 候補を表示（${group.supplierCandidates.length}件）`}
              </button>
              {group.showAllSupplierCandidates && (
                <div className="space-y-2 mt-2 max-h-96 overflow-y-auto border border-gray-200 rounded-lg p-2 bg-white">
                  {group.supplierCandidates
                    .filter((name) =>
                      group.supplierFilter
                        ? name.toLowerCase().includes(group.supplierFilter.toLowerCase())
                        : true
                    )
                    .map((name) => (
                      <button
                        key={name}
                        type="button"
                        onClick={() => onSelectSupplier(groupIndex, name)}
                        disabled={group.isMerging}
                        className="block w-full text-left px-4 py-2 bg-white border border-gray-300 rounded-lg hover:bg-blue-50 hover:border-blue-400 transition-colors text-gray-800 disabled:opacity-50 disabled:cursor-not-allowed"
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

      {/* 重複確認ポップアップ (per group) */}
      {group.showDuplicateDialog && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
          <div className="bg-white rounded-xl shadow-2xl max-w-2xl w-full mx-4 max-h-[80vh] overflow-y-auto">
            <div className="p-6">
              <h3 className="text-xl font-bold text-amber-700 mb-4">
                この伝票番号は既に保存されています ({group.supplierName})
              </h3>
              <p className="text-gray-600 mb-4">
                以下のデータが既にDBに存在します。上書きしますか？
              </p>
              <div className="space-y-3 mb-6">
                {group.duplicateNotes.map((note) => (
                  <div
                    key={note.slip_number}
                    className="bg-amber-50 border border-amber-200 rounded-lg p-4"
                  >
                    <div className="flex justify-between items-start mb-2">
                      <span className="font-semibold text-gray-800">伝票番号: {note.slip_number}</span>
                      <span className="text-xs text-gray-500">保存日時: {note.saved_at}</span>
                    </div>
                    <div className="grid grid-cols-2 gap-x-4 gap-y-1 text-sm text-gray-700">
                      <div>日付: {note.date}</div>
                      <div>担当者: {note.sales_person || '—'}</div>
                      <div>小計: ¥{note.subtotal.toLocaleString()}</div>
                      <div>消費税: ¥{note.tax.toLocaleString()}</div>
                      <div className="font-semibold">合計: ¥{note.total.toLocaleString()}</div>
                    </div>
                  </div>
                ))}
              </div>
              <div className="flex gap-3">
                <Button onClick={() => onSave(groupIndex, true)} variant="primary" loading={group.isSaving}>
                  上書き保存する
                </Button>
                <Button onClick={() => onCancelDuplicate(groupIndex)} variant="secondary" fullWidth>
                  キャンセル
                </Button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* 抽出結果リスト */}
      <h3 className="text-xl font-semibold text-gray-700 mb-4">
        抽出結果（{group.invoices.length}件）
      </h3>

      <div className="space-y-6">
        {group.invoices.map((invoice, idx) => (
          <div key={idx} className="bg-white border border-gray-200 rounded-lg p-6">
            <div className="flex items-center justify-between mb-4">
              <div className="flex items-center gap-3">
                <span className="text-lg font-semibold text-gray-700">#{idx + 1}</span>
                {group.editingSupplierIndex === idx ? (
                  <input
                    type="text"
                    value={invoice.supplier_name}
                    onChange={(e) => onEditSupplierNameForGroup(groupIndex, e.target.value)}
                    onBlur={() => onSetEditingSupplierIndex(groupIndex, null)}
                    onKeyDown={(e) =>
                      e.key === 'Enter' && onSetEditingSupplierIndex(groupIndex, null)
                    }
                    className="border border-blue-400 rounded px-2 py-1 text-gray-800 font-medium focus:outline-none focus:ring-2 focus:ring-blue-400"
                    autoFocus
                  />
                ) : (
                  <span
                    className="font-medium text-gray-800 cursor-pointer hover:text-blue-600"
                    onClick={() => onSetEditingSupplierIndex(groupIndex, idx)}
                    title="クリックして仕入先名を編集（グループ全体に反映されます）"
                  >
                    {invoice.supplier_name || '（仕入先名なし）'}
                  </span>
                )}
              </div>
              <div className="flex items-center gap-2">
                {/* Phase 5b': 検出されたキーワード表示（透明性のため） */}
                {invoice.detected_indicators && invoice.detected_indicators.length > 0 && (
                  <span
                    className="px-2 py-0.5 rounded text-xs font-mono text-gray-600 bg-yellow-50 border border-yellow-200"
                    title="PDFから検出されたキーワード（課税/非課税判定の根拠）"
                  >
                    🔍 {invoice.detected_indicators.join(', ')}
                  </span>
                )}
                {/* Phase 5d: 課税/非課税を toggle ボタンに */}
                <button
                  type="button"
                  onClick={() =>
                    onUpdateInvoiceField(groupIndex, idx, 'is_taxable', !invoice.is_taxable)
                  }
                  className={`px-3 py-1 rounded text-xs font-medium border transition-colors ${
                    invoice.is_taxable
                      ? 'bg-green-100 text-green-800 border-green-300 hover:bg-green-200'
                      : 'bg-gray-100 text-gray-600 border-gray-300 hover:bg-gray-200'
                  }`}
                  title="クリックで切替"
                >
                  {invoice.is_taxable ? '課税' : '非課税'}
                </button>
                {/* Phase 5d: 行削除ボタン */}
                <button
                  type="button"
                  onClick={() => {
                    if (
                      window.confirm(
                        `この納品書 (#${idx + 1}: ${invoice.slip_number || '伝票番号なし'} / ¥${invoice.total.toLocaleString()}) を削除しますか？`
                      )
                    ) {
                      onDeleteInvoice(groupIndex, idx);
                    }
                  }}
                  className="px-2 py-1 rounded text-xs font-medium border border-red-300 bg-red-50 text-red-700 hover:bg-red-100 transition-colors"
                  title="この納品書を削除"
                >
                  ✕ 削除
                </button>
              </div>
            </div>

            <div className="grid grid-cols-3 gap-4 mb-4 text-sm">
              <div>
                <label className="text-gray-500 block mb-1">日付:</label>
                <input
                  type="text"
                  value={invoice.date}
                  onChange={(e) =>
                    onUpdateInvoiceField(groupIndex, idx, 'date', e.target.value)
                  }
                  placeholder="YYYY/MM/DD"
                  className="w-full border border-gray-300 rounded px-2 py-1 text-gray-800 font-medium focus:outline-none focus:ring-2 focus:ring-blue-400"
                />
              </div>
              <div>
                <label className="text-gray-500 block mb-1">伝票番号:</label>
                <input
                  type="text"
                  value={invoice.slip_number}
                  onChange={(e) =>
                    onUpdateInvoiceField(groupIndex, idx, 'slip_number', e.target.value)
                  }
                  className="w-full border border-gray-300 rounded px-2 py-1 text-gray-800 font-medium focus:outline-none focus:ring-2 focus:ring-blue-400"
                />
              </div>
              <div>
                <label className="text-gray-500 block mb-1">合計:</label>
                <input
                  type="number"
                  value={invoice.total}
                  onChange={(e) =>
                    onUpdateInvoiceField(groupIndex, idx, 'total', Number(e.target.value) || 0)
                  }
                  className="w-full border border-gray-300 rounded px-2 py-1 text-gray-800 font-medium text-lg focus:outline-none focus:ring-2 focus:ring-blue-400"
                />
              </div>
            </div>

            {invoice.items.length > 0 && (
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="bg-gray-50">
                      <th className="text-left px-3 py-2 text-gray-600">品名</th>
                      <th className="text-left px-3 py-2 text-gray-600">コード</th>
                      <th className="text-right px-3 py-2 text-gray-600">数量</th>
                      <th className="text-right px-3 py-2 text-gray-600">単価</th>
                      <th className="text-right px-3 py-2 text-gray-600">金額</th>
                      <th className="px-2 py-2 text-gray-600 w-10"></th>
                    </tr>
                  </thead>
                  <tbody>
                    {invoice.items.map((item, itemIdx) => (
                      <tr key={itemIdx} className="border-t border-gray-100 hover:bg-red-50/30">
                        <td className="px-3 py-2 text-gray-800">{item.product_name}</td>
                        <td className="px-3 py-2 text-gray-600">{item.product_code}</td>
                        <td className="px-3 py-2 text-right text-gray-800">{item.quantity}</td>
                        <td className="px-3 py-2 text-right text-gray-800">
                          ¥{item.unit_price.toLocaleString()}
                        </td>
                        <td className="px-3 py-2 text-right text-gray-800">
                          ¥{item.amount.toLocaleString()}
                        </td>
                        <td className="px-2 py-2 text-center">
                          <button
                            type="button"
                            onClick={() => {
                              if (
                                window.confirm(
                                  `この明細行を削除しますか？\n品名: ${item.product_name || '(空)'}\n金額: ¥${item.amount.toLocaleString()}\n\n※ 小計・消費税・合計は手動で再調整してください`
                                )
                              ) {
                                onDeleteItem(groupIndex, idx, itemIdx);
                              }
                            }}
                            className="text-red-500 hover:text-red-700 hover:bg-red-100 rounded px-1.5 py-0.5 text-xs font-medium"
                            title="この明細行を削除"
                          >
                            ✕
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}

            <div className="mt-4 pt-3 border-t border-gray-200">
              <div className="flex justify-end gap-6 text-sm items-end">
                <div>
                  <label className="text-gray-500 block mb-1">小計:</label>
                  <input
                    type="number"
                    value={invoice.subtotal}
                    onChange={(e) =>
                      onUpdateInvoiceField(
                        groupIndex,
                        idx,
                        'subtotal',
                        Number(e.target.value) || 0,
                      )
                    }
                    className="w-32 border border-gray-300 rounded px-2 py-1 text-gray-800 font-medium text-right focus:outline-none focus:ring-2 focus:ring-blue-400"
                  />
                </div>
                <div>
                  <label className="text-gray-500 block mb-1">消費税:</label>
                  <input
                    type="number"
                    value={invoice.tax}
                    onChange={(e) =>
                      onUpdateInvoiceField(
                        groupIndex,
                        idx,
                        'tax',
                        Number(e.target.value) || 0,
                      )
                    }
                    className="w-32 border border-gray-300 rounded px-2 py-1 text-gray-800 font-medium text-right focus:outline-none focus:ring-2 focus:ring-blue-400"
                  />
                </div>
                <div className="text-xs text-gray-400 self-center pb-1">
                  ※ 小計+消費税 = ¥{(invoice.subtotal + invoice.tax).toLocaleString()}
                </div>
              </div>
            </div>
          </div>
        ))}
      </div>

      {group.invoices.length > 1 && (
        <div className="mt-6 bg-blue-50 border border-blue-200 rounded-lg p-4">
          <h4 className="text-lg font-semibold text-blue-800 mb-2">グループ累積合計</h4>
          <div className="grid grid-cols-3 gap-4">
            <div>
              <span className="text-sm text-blue-600">小計合計:</span>
              <p className="font-bold text-blue-900">¥{totalSubtotal.toLocaleString()}</p>
            </div>
            <div>
              <span className="text-sm text-blue-600">消費税合計:</span>
              <p className="font-bold text-blue-900">¥{totalTax.toLocaleString()}</p>
            </div>
            <div>
              <span className="text-sm text-blue-600">総合計:</span>
              <p className="font-bold text-blue-900 text-xl">¥{totalAmount.toLocaleString()}</p>
            </div>
          </div>
        </div>
      )}

      {group.pdfUrls.length > 0 && (
        <div className="mt-6">
          <h4 className="text-lg font-semibold text-gray-700 mb-3">納品書PDF</h4>
          {group.pdfUrls.map((url, idx) => (
            <div key={idx} className="border border-gray-200 rounded-lg overflow-hidden mb-4">
              <iframe src={url} className="w-full h-96" title={`納品書PDF ${idx + 1}`} />
            </div>
          ))}
        </div>
      )}

      {!group.isSaved ? (
        <div className="mt-8">
          <div className="border-t-2 border-gray-200 mb-6"></div>
          <h2 className="text-2xl font-semibold text-gray-700 mb-4">
            {group.supplierName}: 仕入れスプレッドシートへの書き込み
          </h2>
          <Message type="info" className="mb-4">
            内容を確認後、スプレッドシートに書き込んでください。
          </Message>
          <Button
            onClick={() => onSave(groupIndex, false)}
            variant="primary"
            fullWidth
            loading={group.isSaving}
            disabled={group.supplierMismatch}
          >
            このグループをスプレッドシートに書き込む
          </Button>
        </div>
      ) : (
        <div className="mt-8">
          <Message type="success">仕入れデータの保存が完了しました</Message>
        </div>
      )}
    </div>
  );
};
