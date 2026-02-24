import React, { useState } from 'react';
import { useAppStore } from '../store/useAppStore';
import { getDeliveryNotes, updateDeliveryNote, checkDiscrepancy } from '../api/client';
import type { Discrepancy, DBDeliveryNote } from '../types';

interface EditingNote extends DBDeliveryNote {
  edited_subtotal: number;
  edited_tax: number;
  edited_total: number;
}

const DiscrepancyRow: React.FC<{
  item: Discrepancy;
  onUpdated: () => void;
}> = ({ item, onUpdated }) => {
  const [expanded, setExpanded] = useState(false);
  const [notes, setNotes] = useState<EditingNote[]>([]);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState<number | null>(null);

  const handleExpand = async () => {
    if (expanded) {
      setExpanded(false);
      return;
    }
    setLoading(true);
    try {
      const result = await getDeliveryNotes(item.company_name, item.year_month);
      setNotes(
        result.notes.map((n) => ({
          ...n,
          edited_subtotal: n.subtotal,
          edited_tax: n.tax,
          edited_total: n.total,
        }))
      );
      setExpanded(true);
    } catch (e) {
      console.error('納品書取得エラー:', e);
    } finally {
      setLoading(false);
    }
  };

  const handleNoteChange = (
    noteId: number,
    field: 'edited_subtotal' | 'edited_tax' | 'edited_total',
    value: string
  ) => {
    const numValue = parseInt(value, 10) || 0;
    setNotes((prev) =>
      prev.map((n) => (n.id === noteId ? { ...n, [field]: numValue } : n))
    );
  };

  const handleSave = async (note: EditingNote) => {
    setSaving(note.id);
    try {
      await updateDeliveryNote(
        note.id,
        note.edited_subtotal,
        note.edited_tax,
        note.edited_total
      );
      // 元値を更新
      setNotes((prev) =>
        prev.map((n) =>
          n.id === note.id
            ? {
                ...n,
                subtotal: note.edited_subtotal,
                tax: note.edited_tax,
                total: note.edited_total,
              }
            : n
        )
      );
      onUpdated();
    } catch (e) {
      console.error('保存エラー:', e);
      alert('保存に失敗しました');
    } finally {
      setSaving(null);
    }
  };

  const diffSubtotal = item.db_subtotal - item.sheet_subtotal;
  const diffTax = item.db_tax - item.sheet_tax;

  return (
    <div className="border border-gray-200 rounded-lg mb-3">
      <div
        className="flex items-center justify-between px-4 py-3 cursor-pointer hover:bg-gray-50"
        onClick={handleExpand}
      >
        <div className="flex items-center gap-4">
          <span className="text-sm font-medium w-6">{expanded ? '▼' : '▶'}</span>
          <span className="font-medium text-gray-800">{item.company_name}</span>
          <span className="text-sm text-gray-500">{item.year_month}</span>
        </div>
        <div className="flex items-center gap-6 text-sm">
          <div>
            <span className="text-gray-500">DB小計:</span>{' '}
            <span className="font-mono">&yen;{item.db_subtotal.toLocaleString()}</span>
          </div>
          <div>
            <span className="text-gray-500">シート小計:</span>{' '}
            <span className="font-mono">&yen;{item.sheet_subtotal.toLocaleString()}</span>
          </div>
          <div>
            <span className="text-gray-500">DB税:</span>{' '}
            <span className="font-mono">&yen;{item.db_tax.toLocaleString()}</span>
          </div>
          <div>
            <span className="text-gray-500">シート税:</span>{' '}
            <span className="font-mono">&yen;{item.sheet_tax.toLocaleString()}</span>
          </div>
          <div className={`font-medium ${diffSubtotal !== 0 || diffTax !== 0 ? 'text-red-600' : 'text-green-600'}`}>
            差額: &yen;{(diffSubtotal + diffTax).toLocaleString()}
          </div>
        </div>
      </div>

      {loading && (
        <div className="px-8 py-4 text-sm text-gray-500">読み込み中...</div>
      )}

      {expanded && !loading && (
        <div className="border-t border-gray-200 px-6 py-4">
          {notes.length === 0 ? (
            <p className="text-sm text-gray-500">納品書がありません</p>
          ) : (
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-gray-200 text-left text-gray-500">
                  <th className="pb-2 pr-4">伝票番号</th>
                  <th className="pb-2 pr-4">日付</th>
                  <th className="pb-2 pr-4">小計</th>
                  <th className="pb-2 pr-4">消費税</th>
                  <th className="pb-2 pr-4">合計</th>
                  <th className="pb-2"></th>
                </tr>
              </thead>
              <tbody>
                {notes.map((note) => {
                  const isChanged =
                    note.edited_subtotal !== note.subtotal ||
                    note.edited_tax !== note.tax ||
                    note.edited_total !== note.total;
                  return (
                    <tr key={note.id} className="border-b border-gray-100">
                      <td className="py-2 pr-4 font-mono">{note.slip_number}</td>
                      <td className="py-2 pr-4">{note.date}</td>
                      <td className="py-2 pr-4">
                        <input
                          type="number"
                          value={note.edited_subtotal}
                          onChange={(e) =>
                            handleNoteChange(note.id, 'edited_subtotal', e.target.value)
                          }
                          className="w-28 px-2 py-1 border border-gray-300 rounded text-right font-mono"
                        />
                      </td>
                      <td className="py-2 pr-4">
                        <input
                          type="number"
                          value={note.edited_tax}
                          onChange={(e) =>
                            handleNoteChange(note.id, 'edited_tax', e.target.value)
                          }
                          className="w-28 px-2 py-1 border border-gray-300 rounded text-right font-mono"
                        />
                      </td>
                      <td className="py-2 pr-4">
                        <input
                          type="number"
                          value={note.edited_total}
                          onChange={(e) =>
                            handleNoteChange(note.id, 'edited_total', e.target.value)
                          }
                          className="w-28 px-2 py-1 border border-gray-300 rounded text-right font-mono"
                        />
                      </td>
                      <td className="py-2">
                        <button
                          onClick={() => handleSave(note)}
                          disabled={!isChanged || saving === note.id}
                          className={`px-3 py-1 rounded text-sm font-medium transition-colors ${
                            isChanged && saving !== note.id
                              ? 'bg-blue-600 text-white hover:bg-blue-700'
                              : 'bg-gray-200 text-gray-400 cursor-not-allowed'
                          }`}
                        >
                          {saving === note.id ? '保存中...' : '保存'}
                        </button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}
        </div>
      )}
    </div>
  );
};

export const ReconciliationPage: React.FC = () => {
  const discrepancies = useAppStore((s) => s.discrepancies);
  const discrepancyLoading = useAppStore((s) => s.discrepancyLoading);
  const setDiscrepancies = useAppStore((s) => s.setDiscrepancies);
  const setDiscrepancyLoading = useAppStore((s) => s.setDiscrepancyLoading);
  const [refreshing, setRefreshing] = useState(false);

  const handleRefresh = async () => {
    setRefreshing(true);
    setDiscrepancyLoading(true);
    try {
      const result = await checkDiscrepancy();
      setDiscrepancies(result.discrepancies);
    } catch (e) {
      console.error('乖離チェックエラー:', e);
    } finally {
      setDiscrepancyLoading(false);
      setRefreshing(false);
    }
  };

  const handleUpdated = async () => {
    // 保存後に乖離チェックを再実行
    await handleRefresh();
  };

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-3xl font-bold text-gray-800">乖離確認</h1>
        <button
          onClick={handleRefresh}
          disabled={refreshing}
          className="px-4 py-2 bg-gray-100 text-gray-700 rounded-lg hover:bg-gray-200 transition-colors text-sm font-medium disabled:opacity-50"
        >
          {refreshing ? '確認中...' : '再チェック'}
        </button>
      </div>

      <p className="text-gray-600 mb-6">
        DB に保存されている金額とスプレッドシートの金額を比較し、乖離がある項目を表示します。
        納品書単位で金額を修正できます。
      </p>

      {discrepancyLoading && discrepancies.length === 0 ? (
        <div className="text-center py-12 text-gray-500">チェック中...</div>
      ) : discrepancies.length === 0 ? (
        <div className="text-center py-12">
          <div className="text-4xl mb-4">&#x2705;</div>
          <p className="text-lg text-gray-600">乖離はありません</p>
        </div>
      ) : (
        <div>
          <div className="mb-4 text-sm text-gray-500">
            {discrepancies.length} 件の乖離があります
          </div>
          {discrepancies.map((item, idx) => (
            <DiscrepancyRow
              key={`${item.company_name}-${item.year_month}-${idx}`}
              item={item}
              onUpdated={handleUpdated}
            />
          ))}
        </div>
      )}
    </div>
  );
};
