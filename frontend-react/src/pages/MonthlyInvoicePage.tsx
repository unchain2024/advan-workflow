import React, { useState, useEffect } from 'react';
import { Button } from '../components/Common/Button';
import { Message } from '../components/Common/Message';
import { Spinner } from '../components/Common/Spinner';
import { MetricCard } from '../components/Common/MetricCard';
import { generateMonthlyInvoice, getDBCompanies, getDBSalesPersons } from '../api/client';
import type { GenerateMonthlyInvoiceResponse } from '../types';

export const MonthlyInvoicePage: React.FC = () => {
  const [companyName, setCompanyName] = useState('');
  const [salesPerson, setSalesPerson] = useState('');
  const [selectedYear, setSelectedYear] = useState('2025');
  const [selectedMonth, setSelectedMonth] = useState('3');
  const [companies, setCompanies] = useState<string[]>([]);
  const [salesPersons, setSalesPersons] = useState<string[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [result, setResult] = useState<GenerateMonthlyInvoiceResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  // ページ読み込み時にDB内の会社名・担当者名リストを取得
  useEffect(() => {
    getDBCompanies()
      .then((res) => setCompanies(res.companies))
      .catch(() => {});
    getDBSalesPersons()
      .then((res) => setSalesPersons(res.sales_persons))
      .catch(() => {});
  }, []);

  // 年のリスト（2020-2030）
  const years = Array.from({ length: 11 }, (_, i) => (2020 + i).toString());

  // 月のリスト（1-12）
  const months = Array.from({ length: 12 }, (_, i) => (i + 1).toString());

  const handleGenerate = async () => {
    if (!companyName.trim()) {
      setError('会社名を選択してください');
      return;
    }

    setIsLoading(true);
    setError(null);
    setResult(null);

    try {
      // 年月を "YYYY年M月" 形式に変換
      const yearMonth = `${selectedYear}年${parseInt(selectedMonth)}月`;

      const response = await generateMonthlyInvoice(companyName, yearMonth, salesPerson);
      setResult(response);
    } catch (err: any) {
      const errorMessage =
        err?.response?.data?.detail?.error ||
        err?.response?.data?.detail ||
        err.message ||
        '月次請求書の生成中にエラーが発生しました';
      setError(errorMessage);
      console.error('Error:', err?.response?.data);
    } finally {
      setIsLoading(false);
    }
  };

  const formatCurrency = (value: number) => {
    return new Intl.NumberFormat('ja-JP', {
      style: 'currency',
      currency: 'JPY',
    }).format(value);
  };

  return (
    <div>
      <h1 className="text-4xl font-bold text-gray-800 mb-8">
        月次請求書生成
      </h1>

      {/* ヘルプテキスト */}
      <div className="bg-blue-50 border border-blue-200 rounded-lg p-4 mb-8">
        <p className="text-gray-700 leading-relaxed mb-2">
          <strong>📊 月次請求書とは</strong>
        </p>
        <p className="text-gray-700 leading-relaxed">
          同じ会社の複数の納品書を1つの月次請求書にまとめます。
          まず「📤 売上計上」ページで納品書PDFをアップロードしてください。
        </p>
      </div>

      {/* 入力フォーム */}
      <div className="bg-white border border-gray-200 rounded-lg p-6 mb-6">
        <h2 className="text-2xl font-semibold text-gray-700 mb-4">
          請求書生成条件
        </h2>

        {/* 会社名ドロップダウン */}
        <div className="mb-4">
          <label className="block text-sm font-semibold text-gray-700 mb-2">
            会社名
          </label>
          <select
            value={companyName}
            onChange={(e) => setCompanyName(e.target.value)}
            className="w-full px-4 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-primary bg-white text-gray-700"
            disabled={isLoading}
          >
            <option value="">会社を選択してください</option>
            {companies.map((name) => (
              <option key={name} value={name}>
                {name}
              </option>
            ))}
          </select>
        </div>

        {/* 担当者名ドロップダウン */}
        <div className="mb-4">
          <label className="block text-sm font-semibold text-gray-700 mb-2">
            担当者名
          </label>
          <select
            value={salesPerson}
            onChange={(e) => setSalesPerson(e.target.value)}
            className="w-full px-4 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-primary bg-white text-gray-700"
            disabled={isLoading}
          >
            <option value="">担当者を選択してください</option>
            {salesPersons.map((name) => (
              <option key={name} value={name}>
                {name}
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
              onChange={(e) => setSelectedYear(e.target.value)}
              className="px-4 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-primary"
              disabled={isLoading}
            >
              {years.map((year) => (
                <option key={year} value={year}>
                  {year}
                </option>
              ))}
            </select>
            <span className="text-gray-700 font-medium">年</span>
            <select
              value={selectedMonth}
              onChange={(e) => setSelectedMonth(e.target.value)}
              className="px-4 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-primary"
              disabled={isLoading}
            >
              {months.map((month) => (
                <option key={month} value={month}>
                  {month}
                </option>
              ))}
            </select>
            <span className="text-gray-700 font-medium">月</span>
          </div>
        </div>

        {/* 生成ボタン */}
        <Button
          onClick={handleGenerate}
          variant="primary"
          fullWidth
          disabled={isLoading}
        >
          {isLoading ? '生成中...' : '月次請求書を生成'}
        </Button>
      </div>

      {/* ローディング表示 */}
      {isLoading && (
        <div className="mt-6">
          <Spinner message="月次請求書を生成しています..." />
        </div>
      )}

      {/* エラー表示 */}
      {error && (
        <div className="mt-6">
          <Message type="error">
            {error}
            {error.includes('見つかりません') || error.includes('not found') ? (
              <div className="mt-2">
                <p className="text-sm">
                  まず「📤 売上計上」ページで納品書PDFをアップロードしてください。
                </p>
              </div>
            ) : null}
          </Message>
        </div>
      )}

      {/* 結果表示 */}
      {result && (
        <div className="mt-8 space-y-6">
          {/* 成功メッセージ */}
          <Message type="success">
            月次請求書を生成しました！
          </Message>

          {/* 集計情報カード */}
          <div>
            <h3 className="text-xl font-semibold text-gray-700 mb-4">
              集計情報
            </h3>
            <div className="grid grid-cols-2 md:grid-cols-5 gap-4">
              <MetricCard
                label="納品書件数"
                value={`${result.delivery_notes_count}件`}
              />
              <MetricCard
                label="小計合計"
                value={formatCurrency(result.total_subtotal)}
              />
              <MetricCard
                label="消費税合計"
                value={formatCurrency(result.total_tax)}
              />
              <MetricCard
                label="総合計"
                value={formatCurrency(result.total_amount)}
              />
              <MetricCard
                label="明細件数"
                value={`${result.items_count}件`}
              />
            </div>
          </div>

          {/* 含まれる伝票番号リスト */}
          <div>
            <h3 className="text-xl font-semibold text-gray-700 mb-3">
              含まれる伝票番号
            </h3>
            <div className="bg-gray-50 border border-gray-200 rounded-lg p-4">
              <p className="text-gray-700">
                {result.delivery_notes.join(', ')}
              </p>
            </div>
          </div>

          {/* PDF表示 */}
          <div>
            <h3 className="text-xl font-semibold text-gray-700 mb-3">
              生成された月次請求書PDF
            </h3>
            <div className="bg-white border border-gray-200 rounded-lg overflow-hidden">
              <iframe
                src={result.invoice_url}
                className="w-full h-[800px]"
                title="月次請求書PDF"
              />
            </div>
          </div>

          {/* PDFダウンロードボタン */}
          <div>
            <a
              href={result.invoice_url}
              download={result.invoice_filename}
              className="inline-block"
            >
              <Button variant="primary">
                📥 PDFをダウンロード
              </Button>
            </a>
          </div>
        </div>
      )}
    </div>
  );
};
