import React, { useState, useEffect } from 'react';
import { Button } from '../components/Common/Button';
import { Message } from '../components/Common/Message';
import { Spinner } from '../components/Common/Spinner';
import { getCompaniesAndMonths, getBillingTable, updatePayment } from '../api/client';

export const PaymentPage: React.FC = () => {
  const [companies, setCompanies] = useState<string[]>([]);
  const [yearMonths, setYearMonths] = useState<string[]>([]);
  const [selectedCompany, setSelectedCompany] = useState<string>('');
  const [selectedYearMonth, setSelectedYearMonth] = useState<string>('');
  const [paymentAmount, setPaymentAmount] = useState<number>(0);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const [billingTable, setBillingTable] = useState<{
    headers: string[];
    data: string[][];
  } | null>(null);

  useEffect(() => {
    loadData();
  }, []);

  const loadData = async () => {
    setLoading(true);
    setError(null);

    try {
      const [companiesData, tableData] = await Promise.all([
        getCompaniesAndMonths(),
        getBillingTable(),
      ]);

      setCompanies(companiesData.companies);
      setYearMonths(companiesData.year_months);
      setBillingTable(tableData);

      if (companiesData.companies.length > 0) {
        setSelectedCompany(companiesData.companies[0]);
      }
      if (companiesData.year_months.length > 0) {
        setSelectedYearMonth(companiesData.year_months[0]);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'データの読み込みに失敗しました');
    } finally {
      setLoading(false);
    }
  };

  const handleUpdate = async (addMode: boolean) => {
    if (!selectedCompany || !selectedYearMonth) {
      setError('会社名と年月を選択してください');
      return;
    }

    if (paymentAmount < 0) {
      setError('入金額は0以上で入力してください');
      return;
    }

    setSubmitting(true);
    setError(null);
    setSuccess(null);

    try {
      const result = await updatePayment({
        company_name: selectedCompany,
        year_month: selectedYearMonth,
        payment_amount: paymentAmount,
        add_mode: addMode,
      });

      // メッセージを構築
      let message = result.message;
      if (addMode) {
        // 加算モード: 前の値 + 入金額 = 新しい値
        message += `\n前の値: ¥${result.previous_value.toLocaleString()} + ¥${paymentAmount.toLocaleString()} = ¥${result.new_value.toLocaleString()}`;
      } else {
        // 更新モード: 前の値 → 新しい値
        message += `\n前の値: ¥${result.previous_value.toLocaleString()} → 新しい値: ¥${result.new_value.toLocaleString()}`;
      }
      setSuccess(message);

      // テーブルを再読み込み
      const tableData = await getBillingTable();
      setBillingTable(tableData);

      // 入金額をリセット
      setPaymentAmount(0);
    } catch (err) {
      setError(err instanceof Error ? err.message : '更新に失敗しました');
    } finally {
      setSubmitting(false);
    }
  };

  if (loading) {
    return (
      <div className="flex justify-center items-center min-h-screen">
        <Spinner message="データを読み込み中..." />
      </div>
    );
  }

  return (
    <div>
      <h1 className="text-4xl font-bold text-gray-800 mb-4">💰 入金額入力</h1>

      <div className="bg-gray-50 border border-gray-200 rounded-lg p-4 mb-8">
        <p className="text-gray-700 leading-relaxed">
          各会社の入金額を手動で入力します。
          <br />
          入力すると、売上集計表の「消滅」列が更新され、残高が自動計算されます。
        </p>
      </div>

      {error && (
        <Message type="error" className="mb-4">
          {error}
        </Message>
      )}

      {success && (
        <Message type="success" className="mb-4" style={{ whiteSpace: 'pre-line' }}>
          {success}
        </Message>
      )}

      <div className="grid grid-cols-3 gap-4 mb-6">
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-2">
            会社名を選択
          </label>
          <select
            value={selectedCompany}
            onChange={(e) => setSelectedCompany(e.target.value)}
            className="w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary focus:border-transparent"
          >
            {companies.map((company, index) => (
              <option key={`${company}-${index}`} value={company}>
                {company}
              </option>
            ))}
          </select>
          <p className="text-xs text-gray-500 mt-1">
            売上集計表のA列から選択
          </p>
        </div>

        <div>
          <label className="block text-sm font-medium text-gray-700 mb-2">
            年月を選択
          </label>
          <select
            value={selectedYearMonth}
            onChange={(e) => setSelectedYearMonth(e.target.value)}
            className="w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary focus:border-transparent"
          >
            {yearMonths.map((yearMonth, index) => (
              <option key={`${yearMonth}-${index}`} value={yearMonth}>
                {yearMonth}
              </option>
            ))}
          </select>
          <p className="text-xs text-gray-500 mt-1">
            売上集計表の1行目から選択
          </p>
        </div>

        <div>
          <label className="block text-sm font-medium text-gray-700 mb-2">
            入金額（円）
          </label>
          <input
            type="number"
            value={paymentAmount}
            onChange={(e) => setPaymentAmount(Number(e.target.value))}
            min="0"
            step="1000"
            className="w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary focus:border-transparent"
            placeholder="0"
          />
          <p className="text-xs text-gray-500 mt-1">入金された金額を入力</p>
        </div>
      </div>

      <div className="grid grid-cols-2 gap-4 mb-8">
        <Button
          onClick={() => handleUpdate(false)}
          variant="primary"
          fullWidth
          loading={submitting}
        >
          💾 入金額を更新
        </Button>

        <Button
          onClick={() => handleUpdate(true)}
          variant="secondary"
          fullWidth
          loading={submitting}
        >
          ➕ 加算
        </Button>
      </div>

      {/* 売上集計表 */}
      <div className="border-t-2 border-gray-200 my-8"></div>

      <h2 className="text-3xl font-semibold text-gray-700 mb-4">
        📊 現在の売上集計表
      </h2>

{billingTable && (
        <div style={{ height: '800px', width: '100%', maxWidth: '100%' }}>
          <div
            style={{
              height: '100%',
              width: '100%',
              overflow: 'auto',
              border: '1px solid #e5e7eb',
              borderRadius: '4px',
            }}
          >
            <table className="border-collapse" style={{ width: 'max-content' }}>
              <thead>
                <tr>
                  {billingTable.headers.map((header, index) => {
                    // 列の種類を判定
                    const isCompanyColumn = index === 0;
                    const isCarryOverColumn = header === '繰越';
                    const isTotalColumn =
                      header.includes('前半合計') ||
                      header.includes('後半合計') ||
                      header.includes('年間合計');
                    const isMonthColumn = header.includes('年') && header.includes('月');

                    // 列幅を設定
                    let width = '70px';
                    if (isCompanyColumn) width = '200px';
                    if (isMonthColumn) width = '140px';

                    return (
                      <th
                        key={index}
                        style={{
                          width: width,
                          minWidth: width,
                          maxWidth: width,
                          padding: '8px 12px',
                          backgroundColor: '#f3f4f6',
                          borderBottom: '2px solid #e5e7eb',
                          borderRight: '1px solid #e5e7eb',
                          fontSize: '12px',
                          fontWeight: 500,
                          textAlign: 'left',
                          whiteSpace: 'nowrap',
                          position: (isCompanyColumn || isCarryOverColumn || isTotalColumn) ? 'sticky' : 'static',
                          left: isCompanyColumn ? 0 : undefined,
                          right: isTotalColumn ? 0 : undefined,
                          zIndex: (isCompanyColumn || isCarryOverColumn || isTotalColumn) ? 10 : 'auto',
                        }}
                      >
                        {header}
                      </th>
                    );
                  })}
                </tr>
              </thead>
              <tbody>
                {billingTable.data.map((row, rowIndex) => (
                  <tr key={rowIndex}>
                    {row.map((cell, cellIndex) => {
                      const header = billingTable.headers[cellIndex];
                      const isCompanyColumn = cellIndex === 0;
                      const isCarryOverColumn = header === '繰越';
                      const isTotalColumn =
                        header.includes('前半合計') ||
                        header.includes('後半合計') ||
                        header.includes('年間合計');
                      const isMonthColumn = header.includes('年') && header.includes('月');

                      let width = '70px';
                      if (isCompanyColumn) width = '200px';
                      if (isMonthColumn) width = '140px';

                      const bgColor = rowIndex % 2 === 0 ? '#ffffff' : '#f9fafb';

                      return (
                        <td
                          key={cellIndex}
                          style={{
                            width: width,
                            minWidth: width,
                            maxWidth: width,
                            padding: '8px 12px',
                            backgroundColor: (isCompanyColumn || isCarryOverColumn || isTotalColumn) ? bgColor : 'transparent',
                            borderBottom: '1px solid #e5e7eb',
                            borderRight: '1px solid #e5e7eb',
                            fontSize: '14px',
                            whiteSpace: 'nowrap',
                            overflow: 'hidden',
                            textOverflow: 'ellipsis',
                            position: (isCompanyColumn || isCarryOverColumn || isTotalColumn) ? 'sticky' : 'static',
                            left: isCompanyColumn ? 0 : undefined,
                            right: isTotalColumn ? 0 : undefined,
                            zIndex: (isCompanyColumn || isCarryOverColumn || isTotalColumn) ? 5 : 'auto',
                            fontWeight: isTotalColumn ? 600 : 'normal',
                          }}
                        >
                          {cell}
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
};
