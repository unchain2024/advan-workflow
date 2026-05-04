import React, { useState, useMemo } from 'react';
import { useDropzone } from 'react-dropzone';
import { Button } from '../components/Common/Button';
import { Message } from '../components/Common/Message';
import { Spinner } from '../components/Common/Spinner';
import { ProcessingResult } from '../components/Upload/ProcessingResult';
import { PDFPreviewImage } from '../components/Preview/PDFPreviewImage';
import { EditForm } from '../components/Preview/EditForm';
import { SpreadsheetSave } from '../components/Preview/SpreadsheetSave';
import { processPDF, regenerateInvoice, getCompanyBillingInfo } from '../api/client';
import {
  useAppStore,
  selectCumulativeSubtotal,
  selectCumulativeTax,
  selectCumulativeTotal,
  selectCumulativeItemsCount,
  selectCumulativeItems,
} from '../store/useAppStore';

export const UploadPage: React.FC = () => {
  const [files, setFiles] = useState<File[]>([]);
  const [isProcessing, setIsProcessing] = useState(false);
  const [progress, setProgress] = useState(0);
  const [progressMessage, setProgressMessage] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [showEditForm, setShowEditForm] = useState(false);
  const [companyMismatch, setCompanyMismatch] = useState(false);
  const [companyCandidates, setCompanyCandidates] = useState<string[]>([]);
  const [suggestedCandidates, setSuggestedCandidates] = useState<string[]>([]);
  const [extractedCompanyName, setExtractedCompanyName] = useState('');
  const [showAllCandidates, setShowAllCandidates] = useState(false);
  // バッチ編集: 選択中の納品書インデックス
  const [editingNoteIndex, setEditingNoteIndex] = useState(0);

  const {
    salesPerson,
    selectedYear,
    selectedMonth,
    currentDeliveryNote,
    currentCompanyInfo,
    currentPreviousBilling,
    currentInvoicePath,
    currentYearMonth,
    spreadsheetSaved,
    allDeliveryNotes,
    setSalesPerson,
    setSelectedYear,
    setSelectedMonth,
    setProcessResult,
    setCurrentDeliveryNote,
    setCurrentPreviousBilling,
    setCurrentCompanyInfo,
    setCurrentInvoicePath,
    setSpreadsheetSaved,
    addDeliveryNote,
    addDeliveryPdfUrl,
    deliveryPdfUrls,
    clearAll,
  } = useAppStore();

  // 導出セレクタから累積値を取得
  const cumulativeSubtotal = useAppStore(selectCumulativeSubtotal);
  const cumulativeTax = useAppStore(selectCumulativeTax);
  const cumulativeTotal = useAppStore(selectCumulativeTotal);
  const cumulativeItemsCount = useAppStore(selectCumulativeItemsCount);
  const cumulativeItems = useAppStore(selectCumulativeItems);

  // 納品書日付と対象月の不一致を動的に算出
  const dateMismatchWarnings = useMemo(() => {
    return allDeliveryNotes
      .filter((note) => {
        if (!note.date) return false;
        const parts = note.date.split('/');
        const noteYear = parseInt(parts[0], 10);
        const noteMonth = parseInt(parts[1], 10);
        return noteYear !== selectedYear || noteMonth !== selectedMonth;
      })
      .map((note) => `伝票 ${note.slip_number || '不明'}: 納品書日付 ${note.date} と対象月 ${selectedYear}年${selectedMonth}月 が異なります`);
  }, [allDeliveryNotes, selectedYear, selectedMonth]);

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

    if (!salesPerson.trim()) {
      setError('担当者名を入力してください');
      return;
    }

    setIsProcessing(true);
    setError(null);
    setCompanyMismatch(false);
    setCompanyCandidates([]);
    setExtractedCompanyName('');
    clearAll();

    try {
      let batchCompanyName = '';

      for (let i = 0; i < files.length; i++) {
        const file = files[i];
        setProgressMessage(`処理中: ${file.name} (${i + 1}/${files.length})`);

        const result = await processPDF(file, salesPerson, selectedYear, selectedMonth, i === 0 && files.length > 1, batchCompanyName, (prog, msg) => {
          setProgress(prog);
          setProgressMessage(msg);
        });

        // 最初のファイルの会社名をバッチ内で共有
        if (i === 0 && result.delivery_note.company_name) {
          batchCompanyName = result.delivery_note.company_name;
        }

        // 会社名マッチ状態を保存（最初のファイルで判定）
        if (i === 0 && !result.company_matched) {
          setCompanyMismatch(true);
          setSuggestedCandidates(result.suggested_company_candidates || []);
          setCompanyCandidates(result.sheet_company_candidates);
          setExtractedCompanyName(result.delivery_note.company_name);
          setShowAllCandidates(false);
        }

        // ストアに納品書を追加
        addDeliveryNote(result.delivery_note);

        setProcessResult({
          deliveryNote: result.delivery_note,
          companyInfo: result.company_info,
          previousBilling: result.previous_billing,
          invoicePath: result.invoice_url,
          yearMonth: result.year_month,
        });

        // 納品書PDFのURLを保存（バックエンドから返されたURL）
        useAppStore.setState({ currentDeliveryPdf: result.delivery_pdf_url });
        addDeliveryPdfUrl(result.delivery_pdf_url);
      }

      setProgressMessage('全ての処理が完了しました');
    } catch (err: any) {
      const errorMessage = err?.response?.data?.detail?.error || err.message || '処理中にエラーが発生しました';
      setError(errorMessage);
      console.error('Error:', err?.response?.data?.detail);
    } finally {
      setIsProcessing(false);
      setProgress(0);
    }
  };

  // 保存時に backend が canonical 不一致 (HTTP 400) を返した場合、ピッカーへ戻す
  const handleSaveCompanyMismatch = (info: {
    extracted_name: string;
    candidates: string[];
  }) => {
    setSpreadsheetSaved(false);
    setCompanyMismatch(true);
    setExtractedCompanyName(info.extracted_name);
    setCompanyCandidates(info.candidates);
    setSuggestedCandidates([]);
    setShowAllCandidates(true);
    setError(
      `会社名 '${info.extracted_name}' が canonical マスターと一致しませんでした。下のリストから正しい会社名を選択してください。`
    );
    // ピッカー位置までスクロール
    if (typeof window !== 'undefined') {
      window.scrollTo({ top: 0, behavior: 'smooth' });
    }
  };

  const handleSelectCompany = async (selectedName: string) => {
    // allDeliveryNotes と currentDeliveryNote の会社名を一括更新
    useAppStore.setState((state) => ({
      allDeliveryNotes: state.allDeliveryNotes.map((n) => ({
        ...n,
        company_name: selectedName,
      })),
      currentDeliveryNote: state.currentDeliveryNote
        ? { ...state.currentDeliveryNote, company_name: selectedName }
        : null,
    }));
    setCompanyMismatch(false);
    setCompanyCandidates([]);

    // 正しい会社名で前月請求情報＋会社情報を再取得
    const yearMonth = `${selectedYear}-${String(selectedMonth).padStart(2, '0')}`;
    try {
      const info = await getCompanyBillingInfo(selectedName, yearMonth);
      setCurrentPreviousBilling(info.previous_billing);
      setCurrentCompanyInfo(info.company_info);

      // 正しい会社名・会社情報で請求書PDFを再生成
      const state = useAppStore.getState();
      if (state.currentDeliveryNote) {
        try {
          const result = await regenerateInvoice({
            delivery_note: { ...state.currentDeliveryNote, company_name: selectedName },
            company_info: info.company_info,
            previous_billing: info.previous_billing,
            year_month: yearMonth,
            sales_person: salesPerson,
          });
          setCurrentInvoicePath(result.invoice_url);
        } catch (regenErr) {
          console.error('請求書再生成に失敗:', regenErr);
        }
      }
    } catch (err) {
      console.error('会社情報の再取得に失敗:', err);
    }
  };

  // 編集対象の納品書（バッチ時はドロップダウンで選択可能）
  const editTargetNote = allDeliveryNotes.length > 1
    ? allDeliveryNotes[editingNoteIndex] ?? currentDeliveryNote
    : currentDeliveryNote;

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
        year_month: currentYearMonth || undefined,
        sales_person: salesPerson || undefined,
      });

      // allDeliveryNotes 内の該当エントリを更新（slip_numberで特定）
      if (editTargetNote && data.deliveryNote) {
        useAppStore.setState((state) => {
          const updatedNotes = state.allDeliveryNotes.map((n) =>
            n.slip_number === editTargetNote.slip_number ? data.deliveryNote! : n
          );
          return { allDeliveryNotes: updatedNotes };
        });
      }

      setCurrentDeliveryNote(data.deliveryNote);
      setCurrentPreviousBilling(data.previousBilling);
      setCurrentInvoicePath(result.invoice_url);
      setSpreadsheetSaved(false);
      setShowEditForm(false);

      alert('PDFを再生成しました。スプレッドシートへの書き込みをやり直してください。');
    } catch (err) {
      alert('再生成に失敗しました: ' + (err instanceof Error ? err.message : '不明なエラー'));
    }
  };

  return (
    <div>
      <h1 className="text-4xl font-bold text-gray-800 mb-8">
        売上計上システム
      </h1>

      <h2 className="text-3xl font-semibold text-gray-700 mb-4">
        納品書PDFをアップロード
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
              担当者名 <span className="text-red-500">*</span>
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

      {/* 複数アップロード注意事項 */}
      <div className="bg-amber-50 border border-amber-200 rounded-lg p-3 mb-6 text-sm text-amber-800">
        <p className="font-semibold mb-1">複数ファイルをアップロードする場合：</p>
        <ol className="list-decimal list-inside space-y-0.5">
          <li>同じ会社の納品書のみをまとめてください</li>
          <li>同じ対象年月の納品書のみをまとめてください</li>
        </ol>
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
            処理を開始
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

      {/* Date Mismatch Warning */}
      {dateMismatchWarnings.length > 0 && (
        <div className="mt-6">
          <Message type="warning">
            <p className="font-semibold mb-1">納品書の日付と対象月が一致しません：</p>
            <ul className="list-disc list-inside space-y-0.5">
              {dateMismatchWarnings.map((w, i) => (
                <li key={i}>{w}</li>
              ))}
            </ul>
          </Message>
        </div>
      )}

      {/* Company Name Selection */}
      {companyMismatch && companyCandidates.length > 0 && (
        <div className="mt-6">
          <Message type="error">
            <p className="font-semibold mb-2">
              会社名「{extractedCompanyName}」がスプレッドシートに見つかりません。正しい会社名を選択してください：
            </p>

            {/* おすすめ候補 */}
            {suggestedCandidates.length > 0 && (
              <div className="mt-3">
                <p className="text-sm font-medium text-gray-600 mb-1">類似する会社名：</p>
                <div className="space-y-2">
                  {suggestedCandidates.map((name) => (
                    <button
                      key={name}
                      onClick={() => handleSelectCompany(name)}
                      className="block w-full text-left px-4 py-2 bg-blue-50 border-2 border-blue-400 rounded-lg hover:bg-blue-100 transition-colors text-gray-800 font-medium"
                    >
                      {name}
                    </button>
                  ))}
                </div>
              </div>
            )}

            {/* 全候補（折りたたみ） */}
            <div className="mt-3">
              <button
                onClick={() => setShowAllCandidates(!showAllCandidates)}
                className="text-sm text-blue-600 hover:text-blue-800 font-medium cursor-pointer"
              >
                {showAllCandidates ? '▲ 閉じる' : `▼ すべての会社名を表示（${companyCandidates.length}件）`}
              </button>
              {showAllCandidates && (
                <div className="space-y-2 mt-2">
                  {companyCandidates
                    .filter((name) => !suggestedCandidates.includes(name))
                    .map((name) => (
                      <button
                        key={name}
                        onClick={() => handleSelectCompany(name)}
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

      {/* Processing Result */}
      {currentDeliveryNote && currentPreviousBilling && (
        <div className="mt-8">
          <ProcessingResult
            deliveryNote={currentDeliveryNote}
            companyInfo={currentCompanyInfo}
            previousBilling={currentPreviousBilling}
            cumulativeSubtotal={cumulativeSubtotal}
            cumulativeTax={cumulativeTax}
            cumulativeTotal={cumulativeTotal}
            cumulativeItemsCount={cumulativeItemsCount}
            cumulativeItems={cumulativeItems}
          />

          {/* PDF Preview */}
          {currentInvoicePath && (
            <PDFPreviewImage
              deliveryPdfUrls={deliveryPdfUrls}
              invoicePdfUrl={currentInvoicePath}
            />
          )}

          {/* Edit Button + Batch Selector */}
          {currentInvoicePath && !showEditForm && (
            <div className="mt-6 grid grid-cols-4 gap-4">
              <Button onClick={() => {
                setEditingNoteIndex(allDeliveryNotes.length - 1);
                setShowEditForm(true);
              }} variant="secondary">
                内容を編集
              </Button>
            </div>
          )}

          {/* Edit Form */}
          {showEditForm && (
            <div>
              {/* バッチ時: 編集対象の納品書を選択するドロップダウン */}
              {allDeliveryNotes.length > 1 && (
                <div className="mt-6 mb-4">
                  <label className="block text-sm font-semibold text-gray-700 mb-2">
                    編集する納品書を選択:
                  </label>
                  <select
                    value={editingNoteIndex}
                    onChange={(e) => setEditingNoteIndex(Number(e.target.value))}
                    className="border border-gray-300 rounded-lg px-3 py-2 text-gray-700 focus:outline-none focus:ring-2 focus:ring-red-400 focus:border-transparent"
                  >
                    {allDeliveryNotes.map((note, idx) => (
                      <option key={idx} value={idx}>
                        {idx + 1}. 伝票 {note.slip_number || '不明'} - ¥{note.subtotal.toLocaleString()}
                      </option>
                    ))}
                  </select>
                </div>
              )}

              {editTargetNote && (
                <EditForm
                  key={editTargetNote.slip_number}
                  deliveryNote={editTargetNote}
                  companyInfo={currentCompanyInfo}
                  previousBilling={currentPreviousBilling}
                  onRegenerate={handleRegenerate}
                  onCancel={() => setShowEditForm(false)}
                />
              )}
            </div>
          )}

          {/* Spreadsheet Save — 会社名が未選択の場合はブロック */}
          {currentInvoicePath && !showEditForm && !companyMismatch && (
            <SpreadsheetSave
              allDeliveryNotes={allDeliveryNotes}
              deliveryNote={currentDeliveryNote}
              previousBilling={currentPreviousBilling}
              yearMonth={`${selectedYear}-${String(selectedMonth).padStart(2, '0')}`}
              isSaved={spreadsheetSaved}
              onSaveComplete={() => setSpreadsheetSaved(true)}
              invoicePath={currentInvoicePath}
              cumulativeSubtotal={cumulativeSubtotal}
              cumulativeTax={cumulativeTax}
              salesPerson={salesPerson}
              onCompanyMismatch={handleSaveCompanyMismatch}
            />
          )}
        </div>
      )}
    </div>
  );
};
