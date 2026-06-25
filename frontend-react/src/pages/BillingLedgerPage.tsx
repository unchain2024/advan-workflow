import React, { useState, useEffect } from 'react';
import { Button } from '../components/Common/Button';
import { Message } from '../components/Common/Message';
import { Spinner } from '../components/Common/Spinner';
import {
  getDBCompanies,
  getBillingLedger,
  upsertBillingPayment,
  LedgerEntry,
} from '../api/client';

export const BillingLedgerPage: React.FC = () => {
  const currentYear = new Date().getFullYear();
  const [companies, setCompanies] = useState<string[]>([]);
  const [selectedCompany, setSelectedCompany] = useState<string>('');
  const [selectedYear, setSelectedYear] = useState<number>(currentYear);
  const [entries, setEntries] = useState<LedgerEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadingLedger, setLoadingLedger] = useState(false);
  const [savingCell, setSavingCell] = useState<string>('');
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  // 編集用のローカル値（year_month → 文字列）
  const [editing, setEditing] = useState<Record<string, string>>({});        // 消滅(入金)
  const [editingOpen, setEditingOpen] = useState<Record<string, string>>({}); // 期首残高

  // 期首残高は移行時のみ使う一度きりの値。普段は隠す（トグルでON）
  const [showOpeningBalance, setShowOpeningBalance] = useState(false);

  useEffect(() => {
    loadCompanies();
  }, []);

  useEffect(() => {
    if (selectedCompany) {
      loadLedger();
    }
  }, [selectedCompany, selectedYear]);

  const loadCompanies = async () => {
    setLoading(true);
    try {
      const data = await getDBCompanies();
      setCompanies(data.companies);
      if (data.companies.length > 0) {
        setSelectedCompany(data.companies[0]);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : '会社一覧の取得に失敗しました');
    } finally {
      setLoading(false);
    }
  };

  const loadLedger = async () => {
    if (!selectedCompany) return;
    setLoadingLedger(true);
    setError(null);
    try {
      const data = await getBillingLedger(selectedCompany, selectedYear);
      setEntries(data.entries);
      setEditing({});
      setEditingOpen({});
    } catch (err) {
      setError(err instanceof Error ? err.message : '台帳の取得に失敗しました');
      setEntries([]);
    } finally {
      setLoadingLedger(false);
    }
  };

  const handleSaveRow = async (entry: LedgerEntry) => {
    const ym = entry.year_month;
    const rawPay = editing[ym];
    const rawOpen = editingOpen[ym];
    if (rawPay === undefined && rawOpen === undefined) return;

    const payment = rawPay !== undefined
      ? parseInt(rawPay.replace(/,/g, ''), 10)
      : entry.payment_amount;
    const opening = rawOpen !== undefined
      ? parseInt(rawOpen.replace(/,/g, ''), 10)
      : entry.opening_balance;
    if (Number.isNaN(payment) || Number.isNaN(opening)) {
      setError('数値として解釈できない入力があります');
      return;
    }
    setSavingCell(ym);
    setError(null);
    setSuccess(null);
    try {
      // payment_amount と opening_balance を同時に保存（互いを上書きしない）
      await upsertBillingPayment(selectedCompany, ym, payment, opening);
      setSuccess(
        `${selectedCompany} ${ym} を保存（期首残高 ¥${opening.toLocaleString()} / 消滅 ¥${payment.toLocaleString()}）`
      );
      await loadLedger();
    } catch (err) {
      setError(err instanceof Error ? err.message : '保存に失敗しました');
    } finally {
      setSavingCell('');
    }
  };

  const yearOptions = Array.from({ length: 5 }, (_, i) => currentYear - 2 + i);

  if (loading) {
    return (
      <div className="flex justify-center items-center min-h-screen">
        <Spinner message="読み込み中..." />
      </div>
    );
  }

  return (
    <div>
      <h1 className="text-4xl font-bold text-gray-800 mb-4">売上入金管理</h1>
      <p className="text-sm text-gray-600 mb-6">
        会社ごとの月次台帳（発生・消費税・消滅・残高）を DB から計算して表示します。
        <strong>消滅（入金）</strong>を入力して保存できます。
      </p>

      <div className="bg-gray-50 border border-gray-200 rounded-lg p-4 mb-6">
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">会社</label>
            <select
              value={selectedCompany}
              onChange={(e) => setSelectedCompany(e.target.value)}
              className="w-full border border-gray-300 rounded-lg px-3 py-2 bg-white"
            >
              {companies.map((c) => (
                <option key={c} value={c}>
                  {c}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">年</label>
            <select
              value={selectedYear}
              onChange={(e) => setSelectedYear(parseInt(e.target.value, 10))}
              className="w-full border border-gray-300 rounded-lg px-3 py-2 bg-white"
            >
              {yearOptions.map((y) => (
                <option key={y} value={y}>
                  {y}年
                </option>
              ))}
            </select>
          </div>
          <div className="flex items-end">
            <Button onClick={loadLedger} disabled={loadingLedger} variant="secondary">
              {loadingLedger ? '読み込み中...' : '再読み込み'}
            </Button>
          </div>
        </div>
        <div className="mt-3 pt-3 border-t border-gray-200">
          <label className="flex items-center gap-2 text-sm text-gray-600">
            <input
              type="checkbox"
              checked={showOpeningBalance}
              onChange={(e) => {
                setShowOpeningBalance(e.target.checked);
                if (!e.target.checked) setEditingOpen({});
              }}
            />
            移行残高を設定する（期首残高の入力欄を表示）
          </label>
          {showOpeningBalance && (
            <p className="text-xs text-gray-500 mt-1">
              ※ レガシーからの移行時に、各社のその月時点の繰越残高を一度だけ入力する欄です
              （その月以降の残高計算の起点になります）。通常運用では使いません。
            </p>
          )}
        </div>
      </div>

      {error && <Message type="error">{error}</Message>}
      {success && <Message type="success">{success}</Message>}

      {loadingLedger ? (
        <Spinner message="台帳を計算中..." />
      ) : (
        <div className="overflow-x-auto bg-white border border-gray-200 rounded-lg">
          <table className="w-full text-sm">
            <thead className="bg-gray-100">
              <tr>
                <th className="px-3 py-2 text-left border-b">年月</th>
                <th className="px-3 py-2 text-right border-b">前月残高</th>
                {showOpeningBalance && (
                  <th className="px-3 py-2 text-right border-b">期首残高</th>
                )}
                <th className="px-3 py-2 text-right border-b">発生</th>
                <th className="px-3 py-2 text-right border-b">消費税</th>
                <th className="px-3 py-2 text-right border-b">消滅（入金）</th>
                <th className="px-3 py-2 text-right border-b">残高</th>
                <th className="px-3 py-2 text-center border-b">伝票数</th>
                <th className="px-3 py-2 text-center border-b">操作</th>
              </tr>
            </thead>
            <tbody>
              {entries.map((e) => {
                const editValue = editing[e.year_month];
                const hasEdit = editValue !== undefined;
                const openValue = editingOpen[e.year_month];
                const hasOpenEdit = openValue !== undefined;
                const rowDirty = hasEdit || hasOpenEdit;
                const isSaving = savingCell === e.year_month;
                const hasActivity =
                  e.subtotal !== 0 || e.tax !== 0 || e.payment_amount !== 0 || e.opening_balance !== 0;
                return (
                  <tr
                    key={e.year_month}
                    className={`border-b ${hasActivity ? '' : 'text-gray-400'}`}
                  >
                    <td className="px-3 py-2">{e.year_month}</td>
                    <td className="px-3 py-2 text-right">
                      ¥{e.previous_balance.toLocaleString()}
                    </td>
                    {showOpeningBalance && (
                      <td className="px-3 py-2 text-right">
                        <input
                          type="text"
                          inputMode="numeric"
                          value={
                            hasOpenEdit
                              ? openValue
                              : e.opening_balance === 0
                              ? ''
                              : e.opening_balance.toLocaleString()
                          }
                          placeholder="0"
                          onChange={(ev) =>
                            setEditingOpen((prev) => ({
                              ...prev,
                              [e.year_month]: ev.target.value,
                            }))
                          }
                          onFocus={(ev) => {
                            if (!hasOpenEdit) {
                              setEditingOpen((prev) => ({
                                ...prev,
                                [e.year_month]: String(e.opening_balance),
                              }));
                            }
                            ev.target.select();
                          }}
                          className="w-28 border border-gray-300 rounded px-2 py-1 text-right bg-white"
                          disabled={isSaving}
                        />
                      </td>
                    )}
                    <td className="px-3 py-2 text-right">¥{e.subtotal.toLocaleString()}</td>
                    <td className="px-3 py-2 text-right">¥{e.tax.toLocaleString()}</td>
                    <td className="px-3 py-2 text-right">
                      <input
                        type="text"
                        inputMode="numeric"
                        value={
                          hasEdit
                            ? editValue
                            : e.payment_amount === 0
                            ? ''
                            : e.payment_amount.toLocaleString()
                        }
                        placeholder="0"
                        onChange={(ev) =>
                          setEditing((prev) => ({
                            ...prev,
                            [e.year_month]: ev.target.value,
                          }))
                        }
                        onFocus={(ev) => {
                          if (!hasEdit) {
                            setEditing((prev) => ({
                              ...prev,
                              [e.year_month]: String(e.payment_amount),
                            }));
                          }
                          ev.target.select();
                        }}
                        className="w-28 border border-gray-300 rounded px-2 py-1 text-right bg-white"
                        disabled={isSaving}
                      />
                    </td>
                    <td className="px-3 py-2 text-right font-semibold">
                      ¥{e.carried_over.toLocaleString()}
                    </td>
                    <td className="px-3 py-2 text-center">{e.notes_count}</td>
                    <td className="px-3 py-2 text-center">
                      {rowDirty && (
                        <Button
                          onClick={() => handleSaveRow(e)}
                          disabled={isSaving}
                          variant="primary"
                        >
                          {isSaving ? '保存中...' : '保存'}
                        </Button>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      <div className="mt-4 text-xs text-gray-500">
        <p>
          ※ 発生・消費税は DB の納品書データから集計しています。残高 = 前月残高 + 期首残高 + 発生 + 消費税 − 消滅。
          すべて DB に保存されます（シート非依存）。
        </p>
      </div>
    </div>
  );
};
