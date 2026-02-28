import React, { useState, useEffect } from 'react';
import { Button } from '../components/Common/Button';
import { Spinner } from '../components/Common/Spinner';
import { Message } from '../components/Common/Message';
import {
  getPurchaseDBCompanies,
  getPurchaseDBSalesPersons,
  getPurchaseMonthly,
} from '../api/client';
import type { PurchaseMonthlyItem } from '../types';

export const PurchaseMonthlyPage: React.FC = () => {
  const [companies, setCompanies] = useState<string[]>([]);
  const [salesPersons, setSalesPersons] = useState<string[]>([]);
  const [selectedCompany, setSelectedCompany] = useState('');
  const [selectedSalesPerson, setSelectedSalesPerson] = useState('');
  const [selectedYear, setSelectedYear] = useState(new Date().getFullYear());
  const [selectedMonth, setSelectedMonth] = useState(new Date().getMonth() + 1);

  const [items, setItems] = useState<PurchaseMonthlyItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadingItems, setLoadingItems] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    loadInitialData();
  }, []);

  useEffect(() => {
    if (selectedCompany) {
      loadSalesPersons(selectedCompany);
    }
  }, [selectedCompany]);

  const loadInitialData = async () => {
    setLoading(true);
    try {
      const companiesData = await getPurchaseDBCompanies();
      setCompanies(companiesData.companies);
      if (companiesData.companies.length > 0) {
        setSelectedCompany(companiesData.companies[0]);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'データの読み込みに失敗しました');
    } finally {
      setLoading(false);
    }
  };

  const loadSalesPersons = async (companyName: string) => {
    try {
      const data = await getPurchaseDBSalesPersons(companyName);
      setSalesPersons(data.sales_persons);
    } catch {
      setSalesPersons([]);
    }
  };

  const handleSearch = async () => {
    if (!selectedCompany) {
      setError('仕入先を選択してください');
      return;
    }

    setLoadingItems(true);
    setError(null);

    try {
      const yearMonth = `${selectedYear}年${selectedMonth}月`;
      const data = await getPurchaseMonthly(
        selectedCompany,
        yearMonth,
        selectedSalesPerson
      );
      setItems(data.items);
    } catch (err) {
      setError(err instanceof Error ? err.message : '取得に失敗しました');
    } finally {
      setLoadingItems(false);
    }
  };

  // 合計計算
  const totalSubtotal = items.reduce((sum, item) => sum + item.subtotal, 0);
  const totalTax = items.reduce((sum, item) => sum + item.tax, 0);
  const totalAmount = items.reduce((sum, item) => sum + item.total, 0);

  if (loading) {
    return (
      <div className="flex justify-center items-center min-h-screen">
        <Spinner message="データを読み込み中..." />
      </div>
    );
  }

  return (
    <div>
      <h1 className="text-4xl font-bold text-gray-800 mb-4">仕入れ月次一覧</h1>

      <div className="bg-gray-50 border border-gray-200 rounded-lg p-4 mb-8">
        <p className="text-gray-700 leading-relaxed">
          仕入先・担当者・年月で絞り込んで、仕入れデータの一覧を表示します。
        </p>
      </div>

      {error && (
        <Message type="error" className="mb-4">
          {error}
        </Message>
      )}

      {/* フィルター */}
      <div className="bg-white border border-gray-200 rounded-lg p-6 mb-6">
        <h2 className="text-2xl font-semibold text-gray-700 mb-4">
          検索条件
        </h2>

        {/* 仕入先ドロップダウン */}
        <div className="mb-4">
          <label className="block text-sm font-semibold text-gray-700 mb-2">
            仕入先
          </label>
          <select
            value={selectedCompany}
            onChange={(e) => {
              setSelectedCompany(e.target.value);
              setSelectedSalesPerson('');
            }}
            className="w-full px-4 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-primary bg-white text-gray-700"
            disabled={loadingItems}
          >
            <option value="">仕入先を選択してください</option>
            {companies.map((company) => (
              <option key={company} value={company}>
                {company}
              </option>
            ))}
          </select>
        </div>

        {/* 担当者ドロップダウン */}
        <div className="mb-4">
          <label className="block text-sm font-semibold text-gray-700 mb-2">
            担当者名
          </label>
          <select
            value={selectedSalesPerson}
            onChange={(e) => setSelectedSalesPerson(e.target.value)}
            className="w-full px-4 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-primary bg-white text-gray-700"
            disabled={loadingItems}
          >
            <option value="">担当者を選択してください</option>
            {salesPersons.map((sp) => (
              <option key={sp} value={sp}>
                {sp}
              </option>
            ))}
          </select>
        </div>

        {/* 年月選択 */}
        <div className="mb-6">
          <label className="block text-sm font-semibold text-gray-700 mb-2">
            対象年月
          </label>
          <div className="flex items-center space-x-3">
            <select
              value={selectedYear}
              onChange={(e) => setSelectedYear(Number(e.target.value))}
              className="px-4 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-primary"
              disabled={loadingItems}
            >
              {Array.from({ length: 11 }, (_, i) => 2020 + i).map((y) => (
                <option key={y} value={y}>{y}</option>
              ))}
            </select>
            <span className="text-gray-700 font-medium">年</span>
            <select
              value={selectedMonth}
              onChange={(e) => setSelectedMonth(Number(e.target.value))}
              className="px-4 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-primary"
              disabled={loadingItems}
            >
              {Array.from({ length: 12 }, (_, i) => i + 1).map((m) => (
                <option key={m} value={m}>{m}</option>
              ))}
            </select>
            <span className="text-gray-700 font-medium">月</span>
          </div>
        </div>

        {/* 検索ボタン */}
        <Button
          onClick={handleSearch}
          variant="primary"
          fullWidth
          disabled={loadingItems}
        >
          {loadingItems ? '検索中...' : '検索'}
        </Button>
      </div>

      {/* 一覧テーブル */}
      {loadingItems ? (
        <Spinner message="データを取得中..." />
      ) : items.length > 0 ? (
        <div className="overflow-x-auto">
          <table className="w-full border-collapse">
            <thead>
              <tr className="bg-gray-50">
                <th className="text-left px-4 py-3 border-b-2 border-gray-200 text-sm font-medium text-gray-600">
                  伝票番号
                </th>
                <th className="text-left px-4 py-3 border-b-2 border-gray-200 text-sm font-medium text-gray-600">
                  日付
                </th>
                <th className="text-left px-4 py-3 border-b-2 border-gray-200 text-sm font-medium text-gray-600">
                  担当者
                </th>
                <th className="text-center px-4 py-3 border-b-2 border-gray-200 text-sm font-medium text-gray-600">
                  課税区分
                </th>
                <th className="text-right px-4 py-3 border-b-2 border-gray-200 text-sm font-medium text-gray-600">
                  小計
                </th>
                <th className="text-right px-4 py-3 border-b-2 border-gray-200 text-sm font-medium text-gray-600">
                  消費税
                </th>
                <th className="text-right px-4 py-3 border-b-2 border-gray-200 text-sm font-medium text-gray-600">
                  合計
                </th>
              </tr>
            </thead>
            <tbody>
              {items.map((item, idx) => (
                <tr key={item.id} className={idx % 2 === 0 ? 'bg-white' : 'bg-gray-50'}>
                  <td className="px-4 py-3 border-b border-gray-100 text-gray-800">
                    {item.slip_number}
                  </td>
                  <td className="px-4 py-3 border-b border-gray-100 text-gray-800">
                    {item.date}
                  </td>
                  <td className="px-4 py-3 border-b border-gray-100 text-gray-800">
                    {item.sales_person || '—'}
                  </td>
                  <td className="px-4 py-3 border-b border-gray-100 text-center">
                    <span
                      className={`px-2 py-1 rounded text-xs font-medium ${
                        item.is_taxable
                          ? 'bg-green-100 text-green-800'
                          : 'bg-gray-100 text-gray-600'
                      }`}
                    >
                      {item.is_taxable ? '課税' : '非課税'}
                    </span>
                  </td>
                  <td className="px-4 py-3 border-b border-gray-100 text-right text-gray-800">
                    ¥{item.subtotal.toLocaleString()}
                  </td>
                  <td className="px-4 py-3 border-b border-gray-100 text-right text-gray-800">
                    ¥{item.tax.toLocaleString()}
                  </td>
                  <td className="px-4 py-3 border-b border-gray-100 text-right font-semibold text-gray-800">
                    ¥{item.total.toLocaleString()}
                  </td>
                </tr>
              ))}
              {/* 合計行 */}
              <tr className="bg-blue-50 font-semibold">
                <td colSpan={4} className="px-4 py-3 text-right text-blue-800">
                  合計
                </td>
                <td className="px-4 py-3 text-right text-blue-800">
                  ¥{totalSubtotal.toLocaleString()}
                </td>
                <td className="px-4 py-3 text-right text-blue-800">
                  ¥{totalTax.toLocaleString()}
                </td>
                <td className="px-4 py-3 text-right text-blue-900 text-lg">
                  ¥{totalAmount.toLocaleString()}
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      ) : (
        items.length === 0 && !loadingItems && selectedCompany && (
          <Message type="info">
            該当するデータがありません。フィルター条件を変更してください。
          </Message>
        )
      )}
    </div>
  );
};
