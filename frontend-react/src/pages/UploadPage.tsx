import React, { useState } from 'react';
import { useDropzone } from 'react-dropzone';
import { Button } from '../components/Common/Button';
import { Message } from '../components/Common/Message';
import { Spinner } from '../components/Common/Spinner';
import { ProcessingResult } from '../components/Upload/ProcessingResult';
import { PDFPreviewImage } from '../components/Preview/PDFPreviewImage';
import { EditForm } from '../components/Preview/EditForm';
import { SpreadsheetSave } from '../components/Preview/SpreadsheetSave';
import { processPDF, regenerateInvoice } from '../api/client';
import { useAppStore } from '../store/useAppStore';

export const UploadPage: React.FC = () => {
  const [files, setFiles] = useState<File[]>([]);
  const [isProcessing, setIsProcessing] = useState(false);
  const [progress, setProgress] = useState(0);
  const [progressMessage, setProgressMessage] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [showEditForm, setShowEditForm] = useState(false);

  const {
    salesPerson,
    selectedYear,
    selectedMonth,
    currentDeliveryNote,
    currentCompanyInfo,
    currentPreviousBilling,
    currentInvoicePath,
    currentYearMonth,
    currentDeliveryPdf,
    spreadsheetSaved,
    setSalesPerson,
    setSelectedYear,
    setSelectedMonth,
    setProcessResult,
    setCurrentDeliveryNote,
    setCurrentPreviousBilling,
    setCurrentInvoicePath,
    setSpreadsheetSaved,
    clearAll,
  } = useAppStore();

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    accept: { 'application/pdf': ['.pdf'] },
    multiple: true,
    onDrop: (acceptedFiles) => {
      setFiles(acceptedFiles);
      setError(null);
      clearAll();
    },
  });

  const removeFile = (index: number) => {
    setFiles(files.filter((_, i) => i !== index));
    if (files.length === 1) {
      clearAll();
    }
  };

  const handleProcess = async () => {
    if (files.length === 0) return;

    setIsProcessing(true);
    setError(null);
    clearAll();

    try {
      for (let i = 0; i < files.length; i++) {
        const file = files[i];
        setProgressMessage(`処理中: ${file.name} (${i + 1}/${files.length})`);

        const result = await processPDF(file, salesPerson, selectedYear, selectedMonth, (prog, msg) => {
          setProgress(prog);
          setProgressMessage(msg);
        });

        setProcessResult({
          deliveryNote: result.delivery_note,
          companyInfo: result.company_info,
          previousBilling: result.previous_billing,
          invoicePath: result.invoice_url,
          yearMonth: result.year_month,
        });

        // 納品書PDFのURLを保存（バックエンドから返されたURL）
        useAppStore.setState({ currentDeliveryPdf: result.delivery_pdf_url });
      }

      setProgressMessage('✅ 全ての処理が完了しました');
    } catch (err: any) {
      const errorMessage = err?.response?.data?.detail?.error || err.message || '処理中にエラーが発生しました';
      setError(errorMessage);
      console.error('Error:', err?.response?.data?.detail);
    } finally {
      setIsProcessing(false);
      setProgress(0);
    }
  };

  const handleRegenerate = async (data: {
    deliveryNote: typeof currentDeliveryNote;
    companyInfo: typeof currentCompanyInfo;
    previousBilling: typeof currentPreviousBilling;
  }) => {
    if (!data.deliveryNote || !data.previousBilling) return;

    try {
      const result = await regenerateInvoice({
        delivery_note: data.deliveryNote,
        company_info: data.companyInfo,
        previous_billing: data.previousBilling,
      });

      setCurrentDeliveryNote(data.deliveryNote);
      setCurrentPreviousBilling(data.previousBilling);
      setCurrentInvoicePath(result.invoice_url);
      setSpreadsheetSaved(false);
      setShowEditForm(false);

      alert('✅ PDFを再生成しました！スプレッドシートへの書き込みをやり直してください。');
    } catch (err) {
      alert('❌ 再生成に失敗しました: ' + (err instanceof Error ? err.message : '不明なエラー'));
    }
  };

  return (
    <div>
      <h1 className="text-4xl font-bold text-gray-800 mb-8">
        📄 売上計上システム
      </h1>

      <h2 className="text-3xl font-semibold text-gray-700 mb-4">
        📤 納品書PDFをアップロード
      </h2>

      <div className="bg-gray-50 border border-gray-200 rounded-lg p-4 mb-8">
        <p className="text-gray-700 leading-relaxed">
          納品書PDFをアップロードすると、以下の処理が自動実行されます：
        </p>
        <ol className="list-decimal list-inside mt-2 text-gray-700 space-y-1">
          <li>PDFから情報を抽出（Claude Vision API）</li>
          <li>会社マスターから住所などを取得</li>
          <li>売上集計表から前月の請求情報を取得</li>
          <li>請求書PDFを生成</li>
          <li>売上集計表を更新（発生・消費税を加算）</li>
        </ol>
      </div>

      {/* 担当者・対象月入力 */}
      <div className="bg-white border border-gray-200 rounded-lg p-4 mb-6">
        <div className="flex items-end gap-4">
          {/* 担当者名 */}
          <div className="flex-1">
            <label className="block text-sm font-medium text-gray-700 mb-1">
              担当者名
            </label>
            <input
              type="text"
              value={salesPerson}
              onChange={(e) => setSalesPerson(e.target.value)}
              placeholder="例：山田太郎"
              className="w-full border border-gray-300 rounded-lg px-3 py-2 text-gray-700 focus:outline-none focus:ring-2 focus:ring-red-400 focus:border-transparent"
              disabled={isProcessing}
            />
          </div>

          {/* 対象年 */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              対象年
            </label>
            <select
              value={selectedYear}
              onChange={(e) => setSelectedYear(Number(e.target.value))}
              className="border border-gray-300 rounded-lg px-3 py-2 text-gray-700 focus:outline-none focus:ring-2 focus:ring-red-400 focus:border-transparent"
              disabled={isProcessing}
            >
              {Array.from({ length: 5 }, (_, i) => new Date().getFullYear() - 2 + i).map((y) => (
                <option key={y} value={y}>{y}年</option>
              ))}
            </select>
          </div>

          {/* 対象月 */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              対象月
            </label>
            <select
              value={selectedMonth}
              onChange={(e) => setSelectedMonth(Number(e.target.value))}
              className="border border-gray-300 rounded-lg px-3 py-2 text-gray-700 focus:outline-none focus:ring-2 focus:ring-red-400 focus:border-transparent"
              disabled={isProcessing}
            >
              {Array.from({ length: 12 }, (_, i) => i + 1).map((m) => (
                <option key={m} value={m}>{m}月</option>
              ))}
            </select>
          </div>
        </div>
      </div>

      {/* File Upload */}
      <div
        {...getRootProps()}
        className={`border-2 border-dashed rounded-xl p-12 text-center cursor-pointer transition-all ${
          isDragActive
            ? 'border-primary bg-red-50'
            : 'border-gray-300 bg-gray-50 hover:border-primary hover:bg-red-50'
        }`}
      >
        <input {...getInputProps()} />
        <div className="text-6xl mb-4">📎</div>
        <p className="text-lg font-semibold text-gray-700 mb-2">
          納品書PDFを選択（複数可）
        </p>
        <p className="text-sm text-gray-500">
          ドラッグ&ドロップまたはクリックしてファイルを選択
        </p>
        <p className="text-xs text-gray-400 mt-2">許可形式: PDF (.pdf)</p>
      </div>

      {/* Selected Files */}
      {files.length > 0 && (
        <div className="mt-6">
          <p className="font-semibold text-gray-700 mb-3">
            選択されたファイル: {files.length}件
          </p>
          <div className="space-y-2">
            {files.map((file, index) => (
              <div
                key={index}
                className="bg-white border border-gray-200 rounded-lg p-4 flex items-center justify-between hover:shadow-md transition-shadow"
              >
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
                  onClick={() => removeFile(index)}
                  className="text-gray-400 hover:text-red-500 text-xl"
                  disabled={isProcessing}
                >
                  ✕
                </button>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Process Button */}
      {files.length > 0 && !isProcessing && !currentDeliveryNote && (
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
      {currentDeliveryNote && currentPreviousBilling && (
        <div className="mt-8">
          <ProcessingResult
            deliveryNote={currentDeliveryNote}
            companyInfo={currentCompanyInfo}
            previousBilling={currentPreviousBilling}
          />

          {/* PDF Preview */}
          {currentInvoicePath && (
            <PDFPreviewImage
              deliveryPdfUrl={currentDeliveryPdf}
              invoicePdfUrl={currentInvoicePath}
            />
          )}

          {/* Edit Button */}
          {currentInvoicePath && !showEditForm && (
            <div className="mt-6 grid grid-cols-4 gap-4">
              <Button onClick={() => setShowEditForm(true)} variant="secondary">
                ✏️ 内容を編集
              </Button>
            </div>
          )}

          {/* Edit Form */}
          {showEditForm && (
            <EditForm
              deliveryNote={currentDeliveryNote}
              companyInfo={currentCompanyInfo}
              previousBilling={currentPreviousBilling}
              onRegenerate={handleRegenerate}
              onCancel={() => setShowEditForm(false)}
            />
          )}

          {/* Spreadsheet Save */}
          {currentInvoicePath && !showEditForm && currentYearMonth && (
            <SpreadsheetSave
              deliveryNote={currentDeliveryNote}
              previousBilling={currentPreviousBilling}
              yearMonth={currentYearMonth}
              isSaved={spreadsheetSaved}
              onSaveComplete={() => setSpreadsheetSaved(true)}
              invoicePath={currentInvoicePath}
            />
          )}
        </div>
      )}
    </div>
  );
};
