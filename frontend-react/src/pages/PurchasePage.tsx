import React, { useState } from 'react';
import { useDropzone } from 'react-dropzone';
import { Button } from '../components/Common/Button';
import { Message } from '../components/Common/Message';
import { Spinner } from '../components/Common/Spinner';
import {
  SupplierGroupSection,
  type PurchaseGroup,
} from '../components/Purchase/SupplierGroupSection';
import { processPurchasePDF, savePurchase } from '../api/client';
import type { ProcessPurchasePDFResponse } from '../types';

// 仕入先名でグルーピング
function groupBySupplier(results: ProcessPurchasePDFResponse[]): PurchaseGroup[] {
  const map = new Map<string, PurchaseGroup>();

  for (const r of results) {
    for (const inv of r.purchase_invoices) {
      const key = inv.supplier_name || '（仕入先名なし）';
      const existing = map.get(key);
      // canonical 化失敗 → picker を即時表示
      const hasMismatch = inv.company_matched === false;
      const candidates = inv.candidate_canonicals || [];

      if (existing) {
        existing.invoices.push(inv);
        existing.pdfUrls.push(r.purchase_pdf_url);
        // グループ内のいずれかが mismatch ならグループ全体を mismatch とする
        if (hasMismatch && !existing.supplierMismatch) {
          existing.supplierMismatch = true;
          existing.extractedSupplierName = inv.supplier_name;
          existing.supplierCandidates = candidates;
          existing.showAllSupplierCandidates = true;
        }
      } else {
        map.set(key, {
          id: `${key}__${inv.slip_number || crypto.randomUUID()}`,
          supplierName: key,
          invoices: [inv],
          pdfUrls: [r.purchase_pdf_url],
          isSaved: false,
          isSaving: false,
          showDuplicateDialog: false,
          duplicateNotes: [],
          supplierMismatch: hasMismatch,
          extractedSupplierName: hasMismatch ? inv.supplier_name : '',
          supplierCandidates: hasMismatch ? candidates : [],
          showAllSupplierCandidates: hasMismatch,
          supplierFilter: '',
          editingSupplierIndex: null,
          requestId: crypto.randomUUID(),
          error: null,
        });
      }
    }
  }
  return Array.from(map.values());
}

export const PurchasePage: React.FC = () => {
  const [files, setFiles] = useState<File[]>([]);
  const [isProcessing, setIsProcessing] = useState(false);
  const [progress, setProgress] = useState(0);
  const [progressMessage, setProgressMessage] = useState('');
  const [error, setError] = useState<string | null>(null);

  const [salesPerson, setSalesPerson] = useState('');
  const [selectedYear, setSelectedYear] = useState(new Date().getFullYear());
  const [selectedMonth, setSelectedMonth] = useState(new Date().getMonth() + 1);

  const [groups, setGroups] = useState<PurchaseGroup[]>([]);

  const updateGroup = (groupIndex: number, patch: Partial<PurchaseGroup>) => {
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
      const results: ProcessPurchasePDFResponse[] = [];
      for (let i = 0; i < files.length; i++) {
        const file = files[i];
        setProgressMessage(`処理中: ${file.name} (${i + 1}/${files.length})`);
        const result = await processPurchasePDF(file, (prog, msg) => {
          setProgress(prog);
          setProgressMessage(msg);
        });
        results.push(result);
      }
      const newGroups = groupBySupplier(results);
      setGroups(newGroups);
      setProgressMessage(
        `全ての処理が完了しました（${newGroups.length} 仕入先, ${results.reduce((s, r) => s + r.purchase_invoices.length, 0)} 件）`
      );
    } catch (err: any) {
      const errorMessage = err?.response?.data?.detail || err.message || '処理中にエラーが発生しました';
      setError(typeof errorMessage === 'string' ? errorMessage : JSON.stringify(errorMessage));
    } finally {
      setIsProcessing(false);
      setProgress(0);
    }
  };

  const handleSaveGroup = async (groupIndex: number, forceOverwrite: boolean) => {
    const group = groups[groupIndex];
    if (!group || group.invoices.length === 0) return;

    const companyName = group.invoices[0].supplier_name;
    if (!companyName) {
      updateGroup(groupIndex, { error: '仕入先名が空です。仕入先名を編集してください。' });
      return;
    }

    updateGroup(groupIndex, { isSaving: true, error: null, showDuplicateDialog: false });

    try {
      const yearMonth = `${selectedYear}-${String(selectedMonth).padStart(2, '0')}`;

      const response = await savePurchase({
        company_name: companyName,
        year_month: yearMonth,
        purchase_notes: group.invoices.map((inv) => ({
          date: inv.date,
          slip_number: inv.slip_number,
          items: inv.items,
          subtotal: inv.subtotal,
          tax: inv.tax,
          total: inv.total,
          is_taxable: inv.is_taxable,
          detected_indicators: inv.detected_indicators || [],
        })),
        sales_person: salesPerson,
        request_id: group.requestId,
        force_overwrite: forceOverwrite,
      });

      if (response.duplicate_conflict && response.existing_notes) {
        updateGroup(groupIndex, {
          duplicateNotes: response.existing_notes,
          showDuplicateDialog: true,
          isSaving: false,
        });
        return;
      }

      let message = response.message;
      if (response.warning) message += `\n${response.warning}`;
      alert(message);
      updateGroup(groupIndex, { isSaved: true, isSaving: false, showDuplicateDialog: false });
    } catch (err: any) {
      const status = err?.response?.status;
      const detail = err?.response?.data?.detail;
      if (status === 400 && detail?.error === 'company_not_matched') {
        updateGroup(groupIndex, {
          isSaving: false,
          requestId: crypto.randomUUID(),
          extractedSupplierName: detail.extracted_name,
          supplierCandidates: detail.candidates || [],
          supplierMismatch: true,
          showAllSupplierCandidates: true,
          supplierFilter: '',
          error: null,
        });
        // Phase 5d': scroll-to-top はやらない (UIが下にあると不便)
      } else {
        const errorMessage =
          (typeof detail === 'string' ? detail : detail?.message) ||
          err?.message ||
          '保存中にエラーが発生しました';
        updateGroup(groupIndex, { isSaving: false, error: errorMessage });
      }
    }
  };

  const handleSelectSupplier = (groupIndex: number, selectedName: string) => {
    const group = groups[groupIndex];
    if (!group) return;
    updateGroup(groupIndex, {
      supplierName: selectedName,
      invoices: group.invoices.map((inv) => ({ ...inv, supplier_name: selectedName })),
      supplierMismatch: false,
      supplierCandidates: [],
      extractedSupplierName: '',
      requestId: crypto.randomUUID(),
      error: null,
    });
  };

  // インライン編集（グループ全体に反映 — グループ概念に合わせて挙動変更）
  const handleEditSupplierNameForGroup = (groupIndex: number, newName: string) => {
    const group = groups[groupIndex];
    if (!group) return;
    updateGroup(groupIndex, {
      supplierName: newName,
      invoices: group.invoices.map((inv) => ({ ...inv, supplier_name: newName })),
    });
  };

  // Phase 5d: 個別 invoice の項目編集
  const handleUpdateInvoiceField = (
    groupIndex: number,
    invoiceIndex: number,
    field: 'date' | 'slip_number' | 'subtotal' | 'tax' | 'total' | 'is_taxable',
    value: string | number | boolean,
  ) => {
    setGroups((prev) =>
      prev.map((g, gi) => {
        if (gi !== groupIndex) return g;
        return {
          ...g,
          invoices: g.invoices.map((inv, ii) =>
            ii === invoiceIndex ? { ...inv, [field]: value as never } : inv,
          ),
        };
      }),
    );
  };

  // Phase 5d: 行削除（重複行の手動削除）
  const handleDeleteInvoice = (groupIndex: number, invoiceIndex: number) => {
    setGroups((prev) => {
      return prev
        .map((g, gi) => {
          if (gi !== groupIndex) return g;
          const newInvoices = g.invoices.filter((_, ii) => ii !== invoiceIndex);
          const newPdfUrls = g.pdfUrls.filter((_, ii) => ii !== invoiceIndex);
          return { ...g, invoices: newInvoices, pdfUrls: newPdfUrls };
        })
        // グループ内の invoice が 0 になったらグループ自体も削除
        .filter((g) => g.invoices.length > 0);
    });
  };

  // Phase 5d': 明細行 (item) 削除 — 誤OCR行を1行ずつ消す
  // 小計/消費税/合計は自動再計算しない（ユーザの手動編集を尊重、必要なら下の input で調整）
  const handleDeleteItem = (
    groupIndex: number,
    invoiceIndex: number,
    itemIndex: number,
  ) => {
    setGroups((prev) =>
      prev.map((g, gi) => {
        if (gi !== groupIndex) return g;
        return {
          ...g,
          invoices: g.invoices.map((inv, ii) => {
            if (ii !== invoiceIndex) return inv;
            return {
              ...inv,
              items: inv.items.filter((_, mi) => mi !== itemIndex),
            };
          }),
        };
      }),
    );
  };

  return (
    <div>
      <h1 className="text-4xl font-bold text-gray-800 mb-8">仕入れ計上</h1>

      <div className="bg-gray-50 border border-gray-200 rounded-lg p-4 mb-8">
        <p className="text-gray-700 leading-relaxed">
          仕入れ納品書PDFをアップロードすると、以下の処理が自動実行されます：
        </p>
        <ol className="list-decimal list-inside mt-2 text-gray-700 space-y-1">
          <li>PDFから情報を抽出（Gemini API）</li>
          <li>課税/非課税を自動判定</li>
          <li>仕入先別にグループ化</li>
          <li>各仕入先ごとにDBに保存 + 仕入シートを更新</li>
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
              className="w-full border border-gray-300 rounded-lg px-3 py-2 text-gray-700 focus:outline-none focus:ring-2 focus:ring-blue-400 focus:border-transparent"
              disabled={isProcessing}
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">対象年</label>
            <select
              value={selectedYear}
              onChange={(e) => setSelectedYear(Number(e.target.value))}
              className="border border-gray-300 rounded-lg px-3 py-2 text-gray-700 focus:outline-none focus:ring-2 focus:ring-blue-400 focus:border-transparent"
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
              className="border border-gray-300 rounded-lg px-3 py-2 text-gray-700 focus:outline-none focus:ring-2 focus:ring-blue-400 focus:border-transparent"
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

      <div className="bg-amber-50 border border-amber-200 rounded-lg p-3 mb-6 text-sm text-amber-800">
        <p className="font-semibold mb-1">複数ファイルをアップロードする場合：</p>
        <ol className="list-decimal list-inside space-y-0.5">
          <li>異なる仕入先の納品書を混ぜてもOK（自動で仕入先別にグループ化されます）</li>
          <li>同じ対象年月の納品書のみをまとめてください</li>
        </ol>
      </div>

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
        <p className="text-lg font-semibold text-gray-700 mb-2">仕入れ納品書PDFを選択（複数可）</p>
        <p className="text-sm text-gray-500">
          ドラッグ&ドロップまたはクリックしてファイルを選択（複数回投入で追加されます）
        </p>
        <p className="text-xs text-gray-400 mt-2">許可形式: PDF (.pdf)</p>
      </div>

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

      {files.length > 0 && !isProcessing && groups.length === 0 && (
        <div className="mt-6">
          <Button onClick={handleProcess} variant="primary" fullWidth>
            処理を開始
          </Button>
        </div>
      )}

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

      {error && (
        <div className="mt-6">
          <Message type="error">{error}</Message>
        </div>
      )}

      {groups.length > 0 && (
        <>
          {groups.length > 1 && (
            <div className="mt-8 mb-2 bg-blue-50 border border-blue-200 rounded-lg p-3 text-sm text-blue-900">
              <p className="font-semibold">📂 {groups.length} 仕入先が抽出されました。</p>
              <p>仕入先ごとに保存ボタンが表示されます。それぞれ確認後に保存してください。</p>
            </div>
          )}
          {groups.map((group, idx) => (
            <SupplierGroupSection
              key={group.id}
              group={group}
              groupIndex={idx}
              totalGroups={groups.length}
              onSave={handleSaveGroup}
              onCancelDuplicate={(gi) =>
                updateGroup(gi, { showDuplicateDialog: false, duplicateNotes: [] })
              }
              onSelectSupplier={handleSelectSupplier}
              onSetShowAllSupplierCandidates={(gi, show) =>
                updateGroup(gi, { showAllSupplierCandidates: show })
              }
              onSetSupplierFilter={(gi, f) => updateGroup(gi, { supplierFilter: f })}
              onSetEditingSupplierIndex={(gi, ix) => updateGroup(gi, { editingSupplierIndex: ix })}
              onEditSupplierNameForGroup={handleEditSupplierNameForGroup}
              onUpdateInvoiceField={handleUpdateInvoiceField}
              onDeleteInvoice={handleDeleteInvoice}
              onDeleteItem={handleDeleteItem}
            />
          ))}
        </>
      )}
    </div>
  );
};
