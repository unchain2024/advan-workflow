import React, { useState, useMemo } from 'react';
import { useDropzone } from 'react-dropzone';
import { Button } from '../components/Common/Button';
import { Message } from '../components/Common/Message';
import { Spinner } from '../components/Common/Spinner';
import {
  CompanyGroupSection,
  type CompanyGroup,
} from '../components/Upload/CompanyGroupSection';
import { processPDF, regenerateInvoice, getCompanyBillingInfo } from '../api/client';
import { useAppStore } from '../store/useAppStore';
import type {
  DeliveryNote,
  CompanyInfo,
  PreviousBilling,
  CompanyNotMatchedError,
  ProcessPDFResponse,
} from '../types';

// グループ ID 生成（最初の slip_number ベースで安定）
const makeGroupId = (companyName: string, firstSlip?: string) =>
  `${companyName}__${firstSlip || crypto.randomUUID()}`;

// process-pdf の結果リストを会社名で集約してグループ化
function groupResults(results: ProcessPDFResponse[]): CompanyGroup[] {
  const map = new Map<string, CompanyGroup>();

  for (const r of results) {
    // canonical 不一致時は extracted name のままなので、グループキーに使う
    const key = r.delivery_note.company_name;
    const existing = map.get(key);

    if (existing) {
      existing.deliveryNotes.push(r.delivery_note);
      existing.deliveryPdfUrls.push(r.delivery_pdf_url);
      // invoice_url はグループ内で最後の納品書のものに更新
      existing.invoicePath = r.invoice_url;
      // previousBilling / companyInfo は最初のものを保持（同社内で同値のはず）
    } else {
      map.set(key, {
        id: makeGroupId(key, r.delivery_note.slip_number),
        companyName: key,
        deliveryNotes: [r.delivery_note],
        companyInfo: r.company_info,
        previousBilling: r.previous_billing,
        invoicePath: r.invoice_url,
        deliveryPdfUrls: [r.delivery_pdf_url],
        companyMismatch: !r.company_matched,
        extractedCompanyName: r.delivery_note.company_name,
        companyCandidates: r.sheet_company_candidates || [],
        suggestedCandidates: r.suggested_company_candidates || [],
        showAllCandidates: false,
        isSaved: false,
        showEditForm: false,
        editingNoteIndex: 0,
        requestId: crypto.randomUUID(),
      });
    }
  }

  return Array.from(map.values());
}

export const UploadPage: React.FC = () => {
  const [files, setFiles] = useState<File[]>([]);
  const [isProcessing, setIsProcessing] = useState(false);
  const [progress, setProgress] = useState(0);
  const [progressMessage, setProgressMessage] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [groups, setGroups] = useState<CompanyGroup[]>([]);

  const {
    salesPerson,
    selectedYear,
    selectedMonth,
    setSalesPerson,
    setSelectedYear,
    setSelectedMonth,
  } = useAppStore();

  // 全グループを通した日付ミスマッチ警告
  const dateMismatchWarnings = useMemo(() => {
    const all: string[] = [];
    for (const g of groups) {
      for (const note of g.deliveryNotes) {
        if (!note.date) continue;
        const parts = note.date.split('/');
        const noteYear = parseInt(parts[0], 10);
        const noteMonth = parseInt(parts[1], 10);
        if (noteYear !== selectedYear || noteMonth !== selectedMonth) {
          all.push(
            `[${g.companyName}] 伝票 ${note.slip_number || '不明'}: 納品書日付 ${note.date} と対象月 ${selectedYear}年${selectedMonth}月 が異なります`
          );
        }
      }
    }
    return all;
  }, [groups, selectedYear, selectedMonth]);

  const updateGroup = (groupIndex: number, patch: Partial<CompanyGroup>) => {
    setGroups((prev) => prev.map((g, i) => (i === groupIndex ? { ...g, ...patch } : g)));
  };

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    accept: { 'application/pdf': ['.pdf'] },
    multiple: true,
    onDrop: (acceptedFiles) => {
      // 追記モード: 既存ファイルに追加 (重複は name+size でスキップ)
      setFiles((prev) => {
        const existingKeys = new Set(prev.map((f) => `${f.name}::${f.size}`));
        const additions = acceptedFiles.filter(
          (f) => !existingKeys.has(`${f.name}::${f.size}`)
        );
        return [...prev, ...additions];
      });
      setError(null);
      // 既に処理済の groups は維持しない (再 process が必要)
      setGroups([]);
    },
  });

  const removeFile = (index: number) => {
    setFiles((prev) => prev.filter((_, i) => i !== index));
    setGroups([]);
  };

  const clearAllFiles = () => {
    setFiles([]);
    setGroups([]);
    setError(null);
  };

  const handleProcess = async () => {
    if (files.length === 0) return;
    if (!salesPerson.trim()) {
      setError('担当者名を入力してください');
      return;
    }

    setIsProcessing(true);
    setError(null);
    setGroups([]);

    try {
      const results: ProcessPDFResponse[] = [];

      for (let i = 0; i < files.length; i++) {
        const file = files[i];
        setProgressMessage(`処理中: ${file.name} (${i + 1}/${files.length})`);

        // Phase 3: companyNameOverride を渡さない（各 PDF を独立に抽出）
        const result = await processPDF(
          file,
          salesPerson,
          selectedYear,
          selectedMonth,
          i === 0 && files.length > 1, // reset_existing
          '',
          (prog, msg) => {
            setProgress(prog);
            setProgressMessage(msg);
          }
        );
        results.push(result);
      }

      const newGroups = groupResults(results);
      setGroups(newGroups);
      setProgressMessage(
        `全ての処理が完了しました（${newGroups.length} 社, ${results.length} 件）`
      );
    } catch (err: any) {
      const errorMessage =
        err?.response?.data?.detail?.error || err.message || '処理中にエラーが発生しました';
      setError(errorMessage);
      console.error('Error:', err?.response?.data?.detail);
    } finally {
      setIsProcessing(false);
      setProgress(0);
    }
  };

  // canonical mismatch picker から会社を選択
  const handleSelectCompany = async (groupIndex: number, selectedName: string) => {
    const group = groups[groupIndex];
    if (!group) return;

    // 全納品書の company_name を更新
    const updatedNotes = group.deliveryNotes.map((n) => ({ ...n, company_name: selectedName }));

    updateGroup(groupIndex, {
      deliveryNotes: updatedNotes,
      companyName: selectedName,
      companyMismatch: false,
      companyCandidates: [],
      suggestedCandidates: [],
      showAllCandidates: false,
      requestId: crypto.randomUUID(),
    });

    // 正しい会社名で前月請求情報＋会社情報を再取得
    const yearMonth = `${selectedYear}-${String(selectedMonth).padStart(2, '0')}`;
    try {
      const info = await getCompanyBillingInfo(selectedName, yearMonth);
      updateGroup(groupIndex, {
        previousBilling: info.previous_billing,
        companyInfo: info.company_info,
      });

      // 編集対象の納品書だけ請求書 PDF を再生成（編集 UI と同じ挙動）
      const target = updatedNotes[updatedNotes.length - 1];
      if (target) {
        try {
          const result = await regenerateInvoice({
            delivery_note: target,
            company_info: info.company_info,
            previous_billing: info.previous_billing,
            year_month: yearMonth,
            sales_person: salesPerson,
          });
          updateGroup(groupIndex, { invoicePath: result.invoice_url });
        } catch (regenErr) {
          console.error('請求書再生成に失敗:', regenErr);
        }
      }
    } catch (err) {
      console.error('会社情報の再取得に失敗:', err);
    }
  };

  // SpreadsheetSave 由来の 400 (canonical mismatch)
  const handleSaveCompanyMismatch = (groupIndex: number, info: CompanyNotMatchedError) => {
    updateGroup(groupIndex, {
      isSaved: false,
      companyMismatch: true,
      extractedCompanyName: info.extracted_name,
      companyCandidates: info.candidates,
      suggestedCandidates: [],
      showAllCandidates: true,
      requestId: crypto.randomUUID(),
    });
    setError(
      `[グループ ${groupIndex + 1}] 会社名 '${info.extracted_name}' が canonical マスターと一致しませんでした。`
    );
    // Phase 5d': scroll-to-top はやらない (UIが下にあると不便)
  };

  const handleRegenerate = async (
    groupIndex: number,
    data: { deliveryNote: DeliveryNote; companyInfo: CompanyInfo | null; previousBilling: PreviousBilling }
  ) => {
    const group = groups[groupIndex];
    if (!group || !data.deliveryNote || !data.previousBilling) return;

    const yearMonth = `${selectedYear}-${String(selectedMonth).padStart(2, '0')}`;
    try {
      const result = await regenerateInvoice({
        delivery_note: data.deliveryNote,
        company_info: data.companyInfo,
        previous_billing: data.previousBilling,
        year_month: yearMonth,
        sales_person: salesPerson,
      });

      // グループ内の該当納品書を更新（slip_number で特定）
      const updatedNotes = group.deliveryNotes.map((n) =>
        n.slip_number === data.deliveryNote.slip_number ? data.deliveryNote : n
      );

      updateGroup(groupIndex, {
        deliveryNotes: updatedNotes,
        previousBilling: data.previousBilling,
        invoicePath: result.invoice_url,
        isSaved: false,
        showEditForm: false,
      });

      alert('PDFを再生成しました。スプレッドシートへの書き込みをやり直してください。');
    } catch (err) {
      alert('再生成に失敗しました: ' + (err instanceof Error ? err.message : '不明なエラー'));
    }
  };

  return (
    <div>
      <h1 className="text-4xl font-bold text-gray-800 mb-8">売上計上システム</h1>

      <h2 className="text-3xl font-semibold text-gray-700 mb-4">納品書PDFをアップロード</h2>

      <div className="bg-gray-50 border border-gray-200 rounded-lg p-4 mb-8">
        <p className="text-gray-700 leading-relaxed">
          納品書PDFをアップロードすると、以下の処理が自動実行されます：
        </p>
        <ol className="list-decimal list-inside mt-2 text-gray-700 space-y-1">
          <li>PDFから情報を抽出（Claude Vision API）</li>
          <li>会社マスターから住所などを取得</li>
          <li>売上集計表から前月の請求情報を取得</li>
          <li>請求書PDFを生成</li>
          <li>会社別にグループ化して、それぞれ売上集計表を更新</li>
        </ol>
      </div>

      {/* 担当者・対象月入力 */}
      <div className="bg-white border border-gray-200 rounded-lg p-4 mb-6">
        <div className="flex items-end gap-4">
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
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">対象年</label>
            <select
              value={selectedYear}
              onChange={(e) => setSelectedYear(Number(e.target.value))}
              className="border border-gray-300 rounded-lg px-3 py-2 text-gray-700 focus:outline-none focus:ring-2 focus:ring-red-400 focus:border-transparent"
              disabled={isProcessing}
            >
              {Array.from({ length: 5 }, (_, i) => new Date().getFullYear() - 2 + i).map((y) => (
                <option key={y} value={y}>
                  {y}年
                </option>
              ))}
            </select>
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">対象月</label>
            <select
              value={selectedMonth}
              onChange={(e) => setSelectedMonth(Number(e.target.value))}
              className="border border-gray-300 rounded-lg px-3 py-2 text-gray-700 focus:outline-none focus:ring-2 focus:ring-red-400 focus:border-transparent"
              disabled={isProcessing}
            >
              {Array.from({ length: 12 }, (_, i) => i + 1).map((m) => (
                <option key={m} value={m}>
                  {m}月
                </option>
              ))}
            </select>
          </div>
        </div>
      </div>

      {/* 複数アップロード注意事項 */}
      <div className="bg-amber-50 border border-amber-200 rounded-lg p-3 mb-6 text-sm text-amber-800">
        <p className="font-semibold mb-1">複数ファイルをアップロードする場合：</p>
        <ol className="list-decimal list-inside space-y-0.5">
          <li>異なる会社の納品書を混ぜてもOK（自動で会社別にグループ化されます）</li>
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
        <p className="text-lg font-semibold text-gray-700 mb-2">納品書PDFを選択（複数可）</p>
        <p className="text-sm text-gray-500">
          ドラッグ&ドロップまたはクリックしてファイルを選択（複数回投入で追加されます）
        </p>
        <p className="text-xs text-gray-400 mt-2">許可形式: PDF (.pdf)</p>
      </div>

      {/* Selected Files */}
      {files.length > 0 && (
        <div className="mt-6">
          <div className="flex items-center justify-between mb-3">
            <p className="font-semibold text-gray-700">選択されたファイル: {files.length}件</p>
            <button
              type="button"
              onClick={clearAllFiles}
              disabled={isProcessing}
              className="text-sm text-red-600 hover:text-red-800 font-medium disabled:opacity-50"
            >
              すべてクリア
            </button>
          </div>
          <div className="space-y-2">
            {files.map((file, index) => (
              <div
                key={`${file.name}::${file.size}::${index}`}
                className="bg-white border border-gray-200 rounded-lg p-4 flex items-center justify-between hover:shadow-md transition-shadow"
              >
                <div className="flex items-center space-x-3">
                  <span className="text-2xl">📄</span>
                  <div>
                    <p className="font-medium text-gray-800">{file.name}</p>
                    <p className="text-sm text-gray-500">{(file.size / 1024 / 1024).toFixed(2)} MB</p>
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
      {files.length > 0 && !isProcessing && groups.length === 0 && (
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

      {/* グループ別セクション */}
      {groups.length > 0 && (
        <>
          {groups.length > 1 && (
            <div className="mt-8 mb-2 bg-blue-50 border border-blue-200 rounded-lg p-3 text-sm text-blue-900">
              <p className="font-semibold">📂 {groups.length} 社が抽出されました。</p>
              <p>会社ごとに保存ボタンが表示されます。それぞれ確認後に保存してください。</p>
            </div>
          )}
          {groups.map((group, idx) => (
            <CompanyGroupSection
              key={group.id}
              group={group}
              groupIndex={idx}
              totalGroups={groups.length}
              selectedYear={selectedYear}
              selectedMonth={selectedMonth}
              salesPerson={salesPerson}
              onSelectCompany={handleSelectCompany}
              onSetShowAllCandidates={(gi, show) => updateGroup(gi, { showAllCandidates: show })}
              onRegenerate={handleRegenerate}
              onSaveCompanyMismatch={handleSaveCompanyMismatch}
              onSaveComplete={(gi) => updateGroup(gi, { isSaved: true })}
              onSetEditingNoteIndex={(gi, ni) => updateGroup(gi, { editingNoteIndex: ni })}
              onSetShowEditForm={(gi, show) => updateGroup(gi, { showEditForm: show })}
            />
          ))}
        </>
      )}
    </div>
  );
};
