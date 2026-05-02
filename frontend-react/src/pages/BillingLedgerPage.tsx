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

  // 編集用のローカル値（year_month → paymentAmount）
  const [editing, setEditing] = useState<Record<string, string>>({});

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
    } catch (err) {
      setError(err instanceof Error ? err.message : '台帳の取得に失敗しました');
      setEntries([]);
    } finally {
      setLoadingLedger(false);
    }
  };

  const handleSavePayment = async (yearMonth: string) => {
    const rawValue = editing[yearMonth];
    if (rawValue === undefined) return;
    const payment = parseInt(rawValue.replace(/,/g, ''), 10);
    if (Number.isNaN(payment)) {
      setError(`'${rawValue}' は数値として解釈できません`);
      return;
    }
    setSavingCell(yearMonth);
    setError(null);
    setSuccess(null);
    try {
      const res = await upsertBillingPayment(selectedCompany, yearMonth, payment);
      let msg = `${selectedCompany} ${yearMonth} の消滅を ¥${payment.toLocaleString()} で保存`;
      if (!res.sheet_synced && res.sheet_error) {
        msg += `（⚠ シート書込失敗: ${res.sheet_error}）`;
      }
      setSuccess(msg);
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
        消滅セルをクリックして金額を入力すると、DB 保存 + スプレッドシートへのミラー書込が行われます。
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
                const isSaving = savingCell === e.year_month;
                const hasActivity = e.subtotal !== 0 || e.tax !== 0 || e.payment_amount !== 0;
                return (
                  <tr
                    key={e.year_month}
                    className={`border-b ${hasActivity ? '' : 'text-gray-400'}`}
                  >
                    <td className="px-3 py-2">{e.year_month}</td>
                    <td className="px-3 py-2 text-right">
                      ¥{e.previous_balance.toLocaleString()}
                    </td>
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
                      {hasEdit && (
                        <Button
                          onClick={() => handleSavePayment(e.year_month)}
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
          ※ 発生・消費税は DB の納品書データから集計しています。
          消滅の保存は DB に書き込み後、スプレッドシートにもミラー書込します（シート書込失敗しても DB は保持）。
        </p>
      </div>
    </div>
  );
};
