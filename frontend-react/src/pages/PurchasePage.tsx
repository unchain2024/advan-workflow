import React, { useState } from 'react';
import { useDropzone } from 'react-dropzone';
import { Button } from '../components/Common/Button';
import { Message } from '../components/Common/Message';
import { Spinner } from '../components/Common/Spinner';
import { processPurchasePDF, savePurchaseRecord } from '../api/client';
import type { PurchaseInvoice, PaymentTerms } from '../types';

export const PurchasePage: React.FC = () => {
  const [file, setFile] = useState<File | null>(null);
  const [isProcessing, setIsProcessing] = useState(false);
  const [progress, setProgress] = useState(0);
  const [progressMessage, setProgressMessage] = useState('');
  const [error, setError] = useState<string | null>(null);

  // 処理結果
  const [purchaseInvoice, setPurchaseInvoice] = useState<PurchaseInvoice | null>(null);
  const [paymentTerms, setPaymentTerms] = useState<PaymentTerms | null>(null);
  const [targetYearMonth, setTargetYearMonth] = useState<string>('');
  const [isOverseas, setIsOverseas] = useState(false);
  const [recordsCount, setRecordsCount] = useState(0);
  const [purchasePdfUrl, setPurchasePdfUrl] = useState('');

  // スプレッドシート保存状態
  const [isSaving, setIsSaving] = useState(false);
  const [isSaved, setIsSaved] = useState(false);

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    accept: { 'application/pdf': ['.pdf'] },
    multiple: false,
    onDrop: (acceptedFiles) => {
      if (acceptedFiles.length > 0) {
        setFile(acceptedFiles[0]);
        setError(null);
        // 前回の結果をクリア
        setPurchaseInvoice(null);
        setPaymentTerms(null);
        setTargetYearMonth('');
        setIsOverseas(false);
        setRecordsCount(0);
        setPurchasePdfUrl('');
        setIsSaved(false);
      }
    },
  });

  const removeFile = () => {
    setFile(null);
    setPurchaseInvoice(null);
    setPaymentTerms(null);
    setTargetYearMonth('');
    setIsOverseas(false);
    setRecordsCount(0);
    setPurchasePdfUrl('');
    setIsSaved(false);
  };

  const handleProcess = async () => {
    if (!file) return;

    setIsProcessing(true);
    setError(null);

    try {
      const result = await processPurchasePDF(file, (prog, msg) => {
        setProgress(prog);
        setProgressMessage(msg);
      });

      setPurchaseInvoice(result.purchase_invoice);
      setPaymentTerms(result.payment_terms);
      setTargetYearMonth(result.target_year_month);
      setIsOverseas(result.is_overseas);
      setRecordsCount(result.records_count);
      setPurchasePdfUrl(result.purchase_pdf_url);
      setProgressMessage('✅ 処理が完了しました');
    } catch (err: any) {
      const errorMessage = err?.response?.data?.detail || err.message || '処理中にエラーが発生しました';
      setError(errorMessage);
      console.error('Error:', err?.response?.data);
    } finally {
      setIsProcessing(false);
      setProgress(0);
    }
  };

  const handleSaveToSpreadsheet = async () => {
    if (!purchaseInvoice || !targetYearMonth) return;

    setIsSaving(true);
    setError(null);

    try {
      const result = await savePurchaseRecord({
        supplier_name: purchaseInvoice.supplier_name,
        target_year_month: targetYearMonth,
        purchase_invoice: purchaseInvoice,
      });

      if (result.success) {
        setIsSaved(true);
        alert(`✅ ${result.message}`);
      }
    } catch (err: any) {
      const errorMessage = err?.response?.data?.detail || err.message || '保存中にエラーが発生しました';
      setError(errorMessage);
      console.error('Error:', err?.response?.data);
    } finally {
      setIsSaving(false);
    }
  };

  return (
    <div>
      <h1 className="text-4xl font-bold text-gray-800 mb-8">
        📥 仕入れワークフロー
      </h1>

      <h2 className="text-3xl font-semibold text-gray-700 mb-4">
        📤 仕入れ納品書PDFをアップロード
      </h2>

      <div className="bg-gray-50 border border-gray-200 rounded-lg p-4 mb-8">
        <p className="text-gray-700 leading-relaxed">
          仕入れ納品書PDFをアップロードすると、以下の処理が自動実行されます：
        </p>
        <ol className="list-decimal list-inside mt-2 text-gray-700 space-y-1">
          <li>PDFから情報を抽出（Claude Vision + Gemini API）</li>
          <li>締め日マスターから支払条件を取得</li>
          <li>締め日に基づいて記入対象月を計算</li>
          <li>仕入れスプレッドシートの該当月・該当会社に金額を記入</li>
          <li>海外輸入の場合は2行に記録（関税なし・関税あり）</li>
        </ol>
      </div>

      {/* File Upload */}
      <div
        {...getRootProps()}
        className={`border-2 border-dashed rounded-xl p-12 text-center cursor-pointer transition-all ${
          isDragActive
            ? 'border-primary bg-blue-50'
            : 'border-gray-300 bg-gray-50 hover:border-primary hover:bg-blue-50'
        }`}
      >
        <input {...getInputProps()} />
        <div className="text-6xl mb-4">📎</div>
        <p className="text-lg font-semibold text-gray-700 mb-2">
          仕入れ納品書PDFを選択
        </p>
        <p className="text-sm text-gray-500">
          ドラッグ&ドロップまたはクリックしてファイルを選択
        </p>
        <p className="text-xs text-gray-400 mt-2">許可形式: PDF (.pdf)</p>
      </div>

      {/* Selected File */}
      {file && (
        <div className="mt-6">
          <p className="font-semibold text-gray-700 mb-3">選択されたファイル:</p>
          <div className="bg-white border border-gray-200 rounded-lg p-4 flex items-center justify-between hover:shadow-md transition-shadow">
            <div className="flex items-center space-x-3">
              <span className="text-2xl">📄</span>
              <div>
                <p className="font-medium text-gray-800">{file.name}</p>
                <p className="text-sm text-gray-500">
                  {(file.size / 1024 / 1024).toFixed(2)} MB
                </p>
              </div>
            </div>
            <button
              onClick={removeFile}
              className="text-gray-400 hover:text-red-500 text-xl"
              disabled={isProcessing}
            >
              ✕
            </button>
          </div>
        </div>
      )}

      {/* Process Button */}
      {file && !isProcessing && !purchaseInvoice && (
        <div className="mt-6">
          <Button onClick={handleProcess} variant="primary" fullWidth>
            🚀 処理を開始
          </Button>
        </div>
      )}

      {/* Progress */}
      {isProcessing && (
        <div className="mt-6">
          <p className="text-sm text-gray-600 mb-2">{progressMessage}</p>
          <div className="w-full bg-gray-200 rounded-full h-6 overflow-hidden">
            <div
              className="bg-primary h-full transition-all duration-300 ease-out flex items-center justify-center text-white text-xs font-semibold"
              style={{ width: `${progress}%` }}
            >
              {progress > 0 && `${progress}%`}
            </div>
          </div>
          <div className="mt-4">
            <Spinner message="処理中..." />
          </div>
        </div>
      )}

      {/* Error */}
      {error && (
        <div className="mt-6">
          <Message type="error">{error}</Message>
        </div>
      )}

      {/* Processing Result */}
      {purchaseInvoice && (
        <div className="mt-8">
          <h3 className="text-2xl font-semibold text-gray-700 mb-4">
            📊 抽出結果
          </h3>

          <div className="bg-white border border-gray-200 rounded-lg p-6 space-y-4">
            {/* 仕入先情報 */}
            <div>
              <h4 className="text-lg font-semibold text-gray-700 mb-2">仕入先情報</h4>
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <span className="text-sm text-gray-500">仕入先名:</span>
                  <p className="font-medium text-gray-800">{purchaseInvoice.supplier_name}</p>
                </div>
                <div>
                  <span className="text-sm text-gray-500">納品日:</span>
                  <p className="font-medium text-gray-800">{purchaseInvoice.date}</p>
                </div>
                <div className="col-span-2">
                  <span className="text-sm text-gray-500">住所:</span>
                  <p className="font-medium text-gray-800">{purchaseInvoice.supplier_address}</p>
                </div>
              </div>
            </div>

            {/* 海外輸入バッジ */}
            {isOverseas && (
              <div className="bg-yellow-50 border border-yellow-200 rounded-lg p-3">
                <p className="text-sm font-semibold text-yellow-800">
                  🌏 海外輸入: 2行に記録されます（関税なし・関税あり）
                </p>
              </div>
            )}

            {/* 金額情報 */}
            <div>
              <h4 className="text-lg font-semibold text-gray-700 mb-2">金額情報</h4>
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <span className="text-sm text-gray-500">税抜金額:</span>
                  <p className="font-medium text-gray-800">¥{purchaseInvoice.subtotal.toLocaleString()}</p>
                </div>
                <div>
                  <span className="text-sm text-gray-500">消費税:</span>
                  <p className="font-medium text-gray-800">¥{purchaseInvoice.tax.toLocaleString()}</p>
                </div>
                <div>
                  <span className="text-sm text-gray-500">合計金額:</span>
                  <p className="font-medium text-gray-800 text-lg">¥{purchaseInvoice.total.toLocaleString()}</p>
                </div>
                {purchaseInvoice.customs_duty > 0 && (
                  <div>
                    <span className="text-sm text-gray-500">関税額:</span>
                    <p className="font-medium text-yellow-700">¥{purchaseInvoice.customs_duty.toLocaleString()}</p>
                  </div>
                )}
              </div>
            </div>

            {/* 締め日情報 */}
            {paymentTerms && (
              <div className="bg-blue-50 border border-blue-200 rounded-lg p-4">
                <h4 className="text-lg font-semibold text-blue-800 mb-2">締め日情報</h4>
                <div className="grid grid-cols-3 gap-4 text-sm">
                  <div>
                    <span className="text-blue-600">締め日:</span>
                    <p className="font-medium text-blue-900">{paymentTerms.closing_day}</p>
                  </div>
                  <div>
                    <span className="text-blue-600">支払日:</span>
                    <p className="font-medium text-blue-900">{paymentTerms.payment_day}</p>
                  </div>
                  {paymentTerms.payment_method && (
                    <div>
                      <span className="text-blue-600">支払方法:</span>
                      <p className="font-medium text-blue-900">{paymentTerms.payment_method}</p>
                    </div>
                  )}
                </div>
              </div>
            )}

            {/* 記入対象月 */}
            <div className="bg-green-50 border border-green-200 rounded-lg p-4">
              <h4 className="text-lg font-semibold text-green-800 mb-1">記入対象月</h4>
              <p className="text-2xl font-bold text-green-900">{targetYearMonth}</p>
              <p className="text-xs text-green-600 mt-1">
                この月の「発生」「消費税」列に記録されます
              </p>
            </div>
          </div>

          {/* PDF Preview */}
          {purchasePdfUrl && (
            <div className="mt-6">
              <h4 className="text-lg font-semibold text-gray-700 mb-3">📄 納品書PDF</h4>
              <div className="border border-gray-200 rounded-lg overflow-hidden">
                <iframe
                  src={purchasePdfUrl}
                  className="w-full h-96"
                  title="納品書PDF"
                />
              </div>
            </div>
          )}

          {/* Save to Spreadsheet Button */}
          {!isSaved && (
            <div className="mt-6">
              <Button
                onClick={handleSaveToSpreadsheet}
                variant="primary"
                fullWidth
                disabled={isSaving}
              >
                {isSaving ? '💾 保存中...' : '💾 スプレッドシートに保存'}
              </Button>
            </div>
          )}

          {/* Saved Message */}
          {isSaved && (
            <div className="mt-6">
              <Message type="success">
                ✅ スプレッドシートに保存されました！
              </Message>
            </div>
          )}
        </div>
      )}
    </div>
  );
};
