import React, { useState, useRef } from 'react';
import { useDropzone } from 'react-dropzone';
import { Button } from '../components/Common/Button';
import { Message } from '../components/Common/Message';
import { Spinner } from '../components/Common/Spinner';
import { processPurchasePDF, savePurchase } from '../api/client';
import type { PurchaseInvoice, ExistingPurchaseNoteInfo } from '../types';

export const PurchasePage: React.FC = () => {
  const [files, setFiles] = useState<File[]>([]);
  const [isProcessing, setIsProcessing] = useState(false);
  const [progress, setProgress] = useState(0);
  const [progressMessage, setProgressMessage] = useState('');
  const [error, setError] = useState<string | null>(null);

  // 入力フィールド
  const [salesPerson, setSalesPerson] = useState('');
  const [selectedYear, setSelectedYear] = useState(new Date().getFullYear());
  const [selectedMonth, setSelectedMonth] = useState(new Date().getMonth() + 1);

  // 処理結果（全PDF分をまとめる）
  const [allInvoices, setAllInvoices] = useState<PurchaseInvoice[]>([]);
  const [purchasePdfUrls, setPurchasePdfUrls] = useState<string[]>([]);

  // 保存状態
  const [isSaving, setIsSaving] = useState(false);
  const [isSaved, setIsSaved] = useState(false);
  const requestIdRef = useRef(crypto.randomUUID());

  // 重複確認ポップアップ
  const [showDuplicateDialog, setShowDuplicateDialog] = useState(false);
  const [duplicateNotes, setDuplicateNotes] = useState<ExistingPurchaseNoteInfo[]>([]);

  // 仕入先名の編集状態
  const [editingSupplierIndex, setEditingSupplierIndex] = useState<number | null>(null);

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    accept: { 'application/pdf': ['.pdf'] },
    multiple: true,
    onDrop: (acceptedFiles) => {
      setFiles(acceptedFiles);
      setError(null);
      setAllInvoices([]);
      setPurchasePdfUrls([]);
      setIsSaved(false);
      requestIdRef.current = crypto.randomUUID();
    },
  });

  const removeFile = (index: number) => {
    setFiles(files.filter((_, i) => i !== index));
    if (files.length === 1) {
      setAllInvoices([]);
      setPurchasePdfUrls([]);
      setIsSaved(false);
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
    setAllInvoices([]);
    setPurchasePdfUrls([]);
    setIsSaved(false);

    try {
      const collectedInvoices: PurchaseInvoice[] = [];
      const collectedPdfUrls: string[] = [];

      for (let i = 0; i < files.length; i++) {
        const file = files[i];
        setProgressMessage(`処理中: ${file.name} (${i + 1}/${files.length})`);

        const result = await processPurchasePDF(file, (prog, msg) => {
          setProgress(prog);
          setProgressMessage(msg);
        });

        collectedInvoices.push(...result.purchase_invoices);
        collectedPdfUrls.push(result.purchase_pdf_url);
      }

      setAllInvoices(collectedInvoices);
      setPurchasePdfUrls(collectedPdfUrls);
      setProgressMessage('全ての処理が完了しました');
    } catch (err: any) {
      const errorMessage = err?.response?.data?.detail || err.message || '処理中にエラーが発生しました';
      setError(errorMessage);
    } finally {
      setIsProcessing(false);
      setProgress(0);
    }
  };

  const doSave = async (forceOverwrite: boolean) => {
    if (allInvoices.length === 0) return;

    // 仕入先名を決定（最初の納品書の仕入先名を使用）
    const companyName = allInvoices[0].supplier_name;
    if (!companyName) {
      setError('仕入先名が空です。仕入先名を入力してください。');
      return;
    }

    setIsSaving(true);
    setError(null);

    try {
      const yearMonth = `${selectedYear}-${String(selectedMonth).padStart(2, '0')}`;

      const response = await savePurchase({
        company_name: companyName,
        year_month: yearMonth,
        purchase_notes: allInvoices.map((inv) => ({
          date: inv.date,
          slip_number: inv.slip_number,
          items: inv.items,
          subtotal: inv.subtotal,
          tax: inv.tax,
          total: inv.total,
          is_taxable: inv.is_taxable,
        })),
        sales_person: salesPerson,
        request_id: requestIdRef.current,
        force_overwrite: forceOverwrite,
      });

      // 重複検出 → ポップアップ
      if (response.duplicate_conflict && response.existing_notes) {
        setDuplicateNotes(response.existing_notes);
        setShowDuplicateDialog(true);
        setIsSaving(false);
        return;
      }

      let message = response.message;
      if (response.warning) {
        message += `\n${response.warning}`;
      }
      alert(message);
      setIsSaved(true);
    } catch (err: any) {
      const errorMessage = err?.response?.data?.detail || err.message || '保存中にエラーが発生しました';
      setError(errorMessage);
    } finally {
      setIsSaving(false);
    }
  };

  const handleSave = () => doSave(false);

  const handleForceOverwrite = () => {
    setShowDuplicateDialog(false);
    doSave(true);
  };

  const handleCancelOverwrite = () => {
    setShowDuplicateDialog(false);
    setDuplicateNotes([]);
  };

  const handleSupplierNameEdit = (index: number, newName: string) => {
    setAllInvoices((prev) =>
      prev.map((inv, i) => (i === index ? { ...inv, supplier_name: newName } : inv))
    );
  };

  // 累積合計
  const totalSubtotal = allInvoices.reduce((sum, inv) => sum + inv.subtotal, 0);
  const totalTax = allInvoices.reduce((sum, inv) => sum + inv.tax, 0);
  const totalAmount = allInvoices.reduce((sum, inv) => sum + inv.total, 0);

  return (
    <div>
      <h1 className="text-4xl font-bold text-gray-800 mb-8">
        仕入れ計上
      </h1>

      <div className="bg-gray-50 border border-gray-200 rounded-lg p-4 mb-8">
        <p className="text-gray-700 leading-relaxed">
          仕入れ納品書PDFをアップロードすると、以下の処理が自動実行されます：
        </p>
        <ol className="list-decimal list-inside mt-2 text-gray-700 space-y-1">
          <li>PDFから情報を抽出（Gemini API）</li>
          <li>課税/非課税を自動判定</li>
          <li>仕入れDBに保存</li>
          <li>仕入れスプレッドシートの該当月・該当会社に金額を記入</li>
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
            <label className="block text-sm font-medium text-gray-700 mb-1">
              対象年
            </label>
            <select
              value={selectedYear}
              onChange={(e) => setSelectedYear(Number(e.target.value))}
              className="border border-gray-300 rounded-lg px-3 py-2 text-gray-700 focus:outline-none focus:ring-2 focus:ring-blue-400 focus:border-transparent"
              disabled={isProcessing}
            >
              {Array.from({ length: 5 }, (_, i) => new Date().getFullYear() - 2 + i).map((y) => (
                <option key={y} value={y}>{y}年</option>
              ))}
            </select>
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              対象月
            </label>
            <select
              value={selectedMonth}
              onChange={(e) => setSelectedMonth(Number(e.target.value))}
              className="border border-gray-300 rounded-lg px-3 py-2 text-gray-700 focus:outline-none focus:ring-2 focus:ring-blue-400 focus:border-transparent"
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
          <li>同じ仕入先の納品書のみをまとめてください</li>
          <li>同じ対象年月の納品書のみをまとめてください</li>
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
          仕入れ納品書PDFを選択（複数可）
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
      {files.length > 0 && !isProcessing && allInvoices.length === 0 && (
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

      {/* 重複確認ポップアップ */}
      {showDuplicateDialog && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
          <div className="bg-white rounded-xl shadow-2xl max-w-2xl w-full mx-4 max-h-[80vh] overflow-y-auto">
            <div className="p-6">
              <h3 className="text-xl font-bold text-amber-700 mb-4">
                この伝票番号は既に保存されています
              </h3>
              <p className="text-gray-600 mb-4">
                以下のデータが既にDBに存在します。上書きしますか？
              </p>
              <div className="space-y-3 mb-6">
                {duplicateNotes.map((note) => (
                  <div
                    key={note.slip_number}
                    className="bg-amber-50 border border-amber-200 rounded-lg p-4"
                  >
                    <div className="flex justify-between items-start mb-2">
                      <span className="font-semibold text-gray-800">
                        伝票番号: {note.slip_number}
                      </span>
                      <span className="text-xs text-gray-500">
                        保存日時: {note.saved_at}
                      </span>
                    </div>
                    <div className="grid grid-cols-2 gap-x-4 gap-y-1 text-sm text-gray-700">
                      <div>日付: {note.date}</div>
                      <div>担当者: {note.sales_person || '—'}</div>
                      <div>小計: ¥{note.subtotal.toLocaleString()}</div>
                      <div>消費税: ¥{note.tax.toLocaleString()}</div>
                      <div className="font-semibold">
                        合計: ¥{note.total.toLocaleString()}
                      </div>
                    </div>
                  </div>
                ))}
              </div>
              <div className="flex gap-3">
                <Button onClick={handleForceOverwrite} variant="primary" loading={isSaving}>
                  上書き保存する
                </Button>
                <Button onClick={handleCancelOverwrite} variant="secondary" fullWidth>
                  キャンセル
                </Button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Processing Results */}
      {allInvoices.length > 0 && (
        <div className="mt-8">
          <h3 className="text-2xl font-semibold text-gray-700 mb-4">
            抽出結果（{allInvoices.length}件）
          </h3>

          <div className="space-y-6">
            {allInvoices.map((invoice, idx) => (
              <div key={idx} className="bg-white border border-gray-200 rounded-lg p-6">
                {/* 仕入先情報 */}
                <div className="flex items-center justify-between mb-4">
                  <div className="flex items-center gap-3">
                    <span className="text-lg font-semibold text-gray-700">
                      #{idx + 1}
                    </span>
                    {editingSupplierIndex === idx ? (
                      <input
                        type="text"
                        value={invoice.supplier_name}
                        onChange={(e) => handleSupplierNameEdit(idx, e.target.value)}
                        onBlur={() => setEditingSupplierIndex(null)}
                        onKeyDown={(e) => e.key === 'Enter' && setEditingSupplierIndex(null)}
                        className="border border-blue-400 rounded px-2 py-1 text-gray-800 font-medium focus:outline-none focus:ring-2 focus:ring-blue-400"
                        autoFocus
                      />
                    ) : (
                      <span
                        className="font-medium text-gray-800 cursor-pointer hover:text-blue-600"
                        onClick={() => setEditingSupplierIndex(idx)}
                        title="クリックして仕入先名を編集"
                      >
                        {invoice.supplier_name || '（仕入先名なし）'}
                      </span>
                    )}
                  </div>
                  <div className="flex items-center gap-2">
                    <span
                      className={`px-2 py-1 rounded text-xs font-medium ${
                        invoice.is_taxable
                          ? 'bg-green-100 text-green-800'
                          : 'bg-gray-100 text-gray-600'
                      }`}
                    >
                      {invoice.is_taxable ? '課税' : '非課税'}
                    </span>
                  </div>
                </div>

                <div className="grid grid-cols-3 gap-4 mb-4 text-sm">
                  <div>
                    <span className="text-gray-500">日付:</span>
                    <p className="font-medium text-gray-800">{invoice.date}</p>
                  </div>
                  <div>
                    <span className="text-gray-500">伝票番号:</span>
                    <p className="font-medium text-gray-800">{invoice.slip_number}</p>
                  </div>
                  <div>
                    <span className="text-gray-500">合計:</span>
                    <p className="font-medium text-gray-800 text-lg">
                      ¥{invoice.total.toLocaleString()}
                    </p>
                  </div>
                </div>

                {/* 明細テーブル */}
                {invoice.items.length > 0 && (
                  <div className="overflow-x-auto">
                    <table className="w-full text-sm">
                      <thead>
                        <tr className="bg-gray-50">
                          <th className="text-left px-3 py-2 text-gray-600">品名</th>
                          <th className="text-left px-3 py-2 text-gray-600">コード</th>
                          <th className="text-right px-3 py-2 text-gray-600">数量</th>
                          <th className="text-right px-3 py-2 text-gray-600">単価</th>
                          <th className="text-right px-3 py-2 text-gray-600">金額</th>
                        </tr>
                      </thead>
                      <tbody>
                        {invoice.items.map((item, itemIdx) => (
                          <tr key={itemIdx} className="border-t border-gray-100">
                            <td className="px-3 py-2 text-gray-800">{item.product_name}</td>
                            <td className="px-3 py-2 text-gray-600">{item.product_code}</td>
                            <td className="px-3 py-2 text-right text-gray-800">{item.quantity}</td>
                            <td className="px-3 py-2 text-right text-gray-800">
                              ¥{item.unit_price.toLocaleString()}
                            </td>
                            <td className="px-3 py-2 text-right text-gray-800">
                              ¥{item.amount.toLocaleString()}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}

                {/* 金額サマリー */}
                <div className="mt-4 pt-3 border-t border-gray-200">
                  <div className="flex justify-end gap-6 text-sm">
                    <div>
                      <span className="text-gray-500">小計: </span>
                      <span className="font-medium">¥{invoice.subtotal.toLocaleString()}</span>
                    </div>
                    <div>
                      <span className="text-gray-500">消費税: </span>
                      <span className="font-medium">¥{invoice.tax.toLocaleString()}</span>
                    </div>
                    <div>
                      <span className="text-gray-500">合計: </span>
                      <span className="font-bold text-lg">¥{invoice.total.toLocaleString()}</span>
                    </div>
                  </div>
                </div>
              </div>
            ))}
          </div>

          {/* 累積合計（複数の場合） */}
          {allInvoices.length > 1 && (
            <div className="mt-6 bg-blue-50 border border-blue-200 rounded-lg p-4">
              <h4 className="text-lg font-semibold text-blue-800 mb-2">累積合計</h4>
              <div className="grid grid-cols-3 gap-4">
                <div>
                  <span className="text-sm text-blue-600">小計合計:</span>
                  <p className="font-bold text-blue-900">¥{totalSubtotal.toLocaleString()}</p>
                </div>
                <div>
                  <span className="text-sm text-blue-600">消費税合計:</span>
                  <p className="font-bold text-blue-900">¥{totalTax.toLocaleString()}</p>
                </div>
                <div>
                  <span className="text-sm text-blue-600">総合計:</span>
                  <p className="font-bold text-blue-900 text-xl">¥{totalAmount.toLocaleString()}</p>
                </div>
              </div>
            </div>
          )}

          {/* PDF Preview */}
          {purchasePdfUrls.length > 0 && (
            <div className="mt-6">
              <h4 className="text-lg font-semibold text-gray-700 mb-3">納品書PDF</h4>
              {purchasePdfUrls.map((url, idx) => (
                <div key={idx} className="border border-gray-200 rounded-lg overflow-hidden mb-4">
                  <iframe
                    src={url}
                    className="w-full h-96"
                    title={`納品書PDF ${idx + 1}`}
                  />
                </div>
              ))}
            </div>
          )}

          {/* Save Button */}
          {!isSaved ? (
            <div className="mt-8">
              <div className="border-t-2 border-gray-200 mb-6"></div>
              <h2 className="text-2xl font-semibold text-gray-700 mb-4">
                仕入れスプレッドシートへの書き込み
              </h2>
              <Message type="info" className="mb-4">
                内容を確認後、スプレッドシートに書き込んでください。
              </Message>
              <Button
                onClick={handleSave}
                variant="primary"
                fullWidth
                loading={isSaving}
              >
                スプレッドシートに書き込む
              </Button>
            </div>
          ) : (
            <div className="mt-8">
              <Message type="success">
                仕入れデータの保存が完了しました
              </Message>
            </div>
          )}
        </div>
      )}
    </div>
  );
};
