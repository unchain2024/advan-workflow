import React, { useState, useEffect, useRef, useCallback } from 'react';
import { Button } from '../components/Common/Button';
import { Message } from '../components/Common/Message';
import { Spinner } from '../components/Common/Spinner';
import { MetricCard } from '../components/Common/MetricCard';
import {
  generateMonthlyInvoice,
  getDBCompanies,
  getDBSalesPersons,
  getDeliveryNotes,
  updateDeliveryNote,
  syncSheetsFromDB,
} from '../api/client';
import type { GenerateMonthlyInvoiceResponse, DBDeliveryNote } from '../types';

interface EditableNote extends DBDeliveryNote {
  edited_subtotal: number;
  edited_tax: number;
  edited_total: number;
  saving?: boolean;
}

const PAGES_PER_BATCH = 5;

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
  const [invoiceImages, setInvoiceImages] = useState<string[]>([]);
  const [imagesLoading, setImagesLoading] = useState(false);
  const [totalPages, setTotalPages] = useState(0);
  const [loadedPageCount, setLoadedPageCount] = useState(0);
  const [loadingMore, setLoadingMore] = useState(false);
  const [currentPage, setCurrentPage] = useState(0);
  const pdfFilenameRef = useRef<string | null>(null);

  // 納品書 inline 編集 (LLM 誤抽出を業務側で修正するため)
  const [editableNotes, setEditableNotes] = useState<EditableNote[]>([]);
  const [notesLoading, setNotesLoading] = useState(false);

  // ページ読み込み時にDB内の会社名リストを取得
  useEffect(() => {
    getDBCompanies()
      .then((res) => setCompanies(res.companies))
      .catch(() => {});
  }, []);

  // 会社名が変更されたら担当者リストを再取得
  useEffect(() => {
    if (companyName) {
      getDBSalesPersons(companyName)
        .then((res) => setSalesPersons(res.sales_persons))
        .catch(() => {});
    } else {
      setSalesPersons([]);
    }
    setSalesPerson('');
  }, [companyName]);

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

      // 納品書 inline 編集用の一覧を取得
      try {
        setNotesLoading(true);
        const notesRes = await getDeliveryNotes(companyName, yearMonth);
        setEditableNotes(
          notesRes.notes.map((n) => ({
            ...n,
            edited_subtotal: n.subtotal,
            edited_tax: n.tax,
            edited_total: n.total,
          }))
        );
      } catch (e) {
        console.error('納品書一覧取得エラー:', e);
      } finally {
        setNotesLoading(false);
      }

      // PDFを画像に変換（最初のバッチ）
      setImagesLoading(true);
      setInvoiceImages([]);
      setTotalPages(0);
      setLoadedPageCount(0);
      setCurrentPage(0);
      try {
        const pdfUrl = response.invoice_url.split('?')[0];
        const filename = pdfUrl.split('/').pop();
        if (filename) {
          pdfFilenameRef.current = filename;
          const imgRes = await fetch(`/api/pdf-to-images/${encodeURIComponent(filename)}?start_page=1&end_page=${PAGES_PER_BATCH}`);
          if (imgRes.ok) {
            const imgData = await imgRes.json();
            setInvoiceImages(imgData.images);
            setTotalPages(imgData.num_pages);
            setLoadedPageCount(imgData.images.length);
          }
        }
      } catch {
        // 画像変換失敗時はフォールバック（ダウンロードのみ）
      } finally {
        setImagesLoading(false);
      }
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

  // 追加ページ読み込み
  const loadMorePages = useCallback(async () => {
    if (loadingMore || loadedPageCount >= totalPages || !pdfFilenameRef.current) return;
    setLoadingMore(true);
    try {
      const startPage = loadedPageCount + 1;
      const endPage = Math.min(loadedPageCount + PAGES_PER_BATCH, totalPages);
      const imgRes = await fetch(
        `/api/pdf-to-images/${encodeURIComponent(pdfFilenameRef.current)}?start_page=${startPage}&end_page=${endPage}`
      );
      if (imgRes.ok) {
        const imgData = await imgRes.json();
        setInvoiceImages((prev) => [...prev, ...imgData.images]);
        setLoadedPageCount((prev) => prev + imgData.images.length);
      }
    } catch {
      // ignore
    } finally {
      setLoadingMore(false);
    }
  }, [loadedPageCount, totalPages, loadingMore]);

  // ページ遷移時に未読み込みなら追加取得
  const handlePageChange = useCallback(async (newPage: number) => {
    setCurrentPage(newPage);
    // 次のページがまだ読み込まれていない場合、先読み
    if (newPage >= loadedPageCount - 1 && loadedPageCount < totalPages) {
      await loadMorePages();
    }
  }, [loadedPageCount, totalPages, loadMorePages]);

  // 納品書 inline 編集ハンドラ
  const handleNoteFieldChange = (
    noteId: number,
    field: 'edited_subtotal' | 'edited_tax' | 'edited_total',
    value: string
  ) => {
    const numValue = parseInt(value, 10) || 0;
    setEditableNotes((prev) =>
      prev.map((n) => (n.id === noteId ? { ...n, [field]: numValue } : n))
    );
  };

  // 単一納品書の保存 + 月次請求書再生成 + シート再同期
  const handleSaveNote = async (note: EditableNote) => {
    setEditableNotes((prev) =>
      prev.map((n) => (n.id === note.id ? { ...n, saving: true } : n))
    );
    try {
      // 1. DB 更新
      await updateDeliveryNote(
        note.id,
        note.edited_subtotal,
        note.edited_tax,
        note.edited_total
      );
      // 2. 月次請求書を再生成 (新しい合計値を反映)
      const yearMonth = `${selectedYear}年${parseInt(selectedMonth)}月`;
      const newRes = await generateMonthlyInvoice(companyName, yearMonth, salesPerson);
      setResult(newRes);
      // PDF 画像も再ロード
      try {
        setImagesLoading(true);
        setInvoiceImages([]);
        setTotalPages(0);
        setLoadedPageCount(0);
        setCurrentPage(0);
        const pdfUrl = newRes.invoice_url.split('?')[0];
        const filename = pdfUrl.split('/').pop();
        if (filename) {
          pdfFilenameRef.current = filename;
          const imgRes = await fetch(
            `/api/pdf-to-images/${encodeURIComponent(filename)}?start_page=1&end_page=${PAGES_PER_BATCH}`
          );
          if (imgRes.ok) {
            const imgData = await imgRes.json();
            setInvoiceImages(imgData.images);
            setTotalPages(imgData.num_pages);
            setLoadedPageCount(imgData.images.length);
          }
        }
      } finally {
        setImagesLoading(false);
      }
      // 3. シート再同期 (DB 真値でシート上書き)
      try {
        await syncSheetsFromDB();
      } catch (e) {
        console.error('シート再同期エラー:', e);
      }
      // 4. 編集状態をリセット (新しい値を origin に)
      setEditableNotes((prev) =>
        prev.map((n) =>
          n.id === note.id
            ? {
                ...n,
                subtotal: note.edited_subtotal,
                tax: note.edited_tax,
                total: note.edited_total,
                saving: false,
              }
            : n
        )
      );
    } catch (e: any) {
      console.error('納品書保存エラー:', e);
      alert(`保存に失敗しました: ${e?.message || e}`);
      setEditableNotes((prev) =>
        prev.map((n) => (n.id === note.id ? { ...n, saving: false } : n))
      );
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

          {/* 納品書一覧 (inline 編集可能) */}
          <div>
            <h3 className="text-xl font-semibold text-gray-700 mb-3">
              含まれる納品書（金額を編集できます）
            </h3>
            <p className="text-sm text-gray-600 mb-3">
              ※ LLM の誤抽出があった場合、その場で修正してください。保存すると
              月次請求書PDF + 売上集計シートが自動的に再生成されます。
            </p>
            {notesLoading ? (
              <div className="text-center py-6 text-gray-500">納品書一覧を読み込み中...</div>
            ) : editableNotes.length === 0 ? (
              <div className="text-center py-6 text-gray-500">納品書がありません</div>
            ) : (
              <div className="overflow-x-auto bg-white border border-gray-200 rounded-lg">
                <table className="w-full text-sm">
                  <thead className="bg-gray-50 border-b border-gray-200">
                    <tr>
                      <th className="px-3 py-2 text-left text-gray-600 font-medium">伝票番号</th>
                      <th className="px-3 py-2 text-left text-gray-600 font-medium">日付</th>
                      <th className="px-3 py-2 text-right text-gray-600 font-medium w-32">小計</th>
                      <th className="px-3 py-2 text-right text-gray-600 font-medium w-32">消費税</th>
                      <th className="px-3 py-2 text-right text-gray-600 font-medium w-32">合計</th>
                      <th className="px-3 py-2 text-center text-gray-600 font-medium w-24">操作</th>
                    </tr>
                  </thead>
                  <tbody>
                    {editableNotes.map((note) => {
                      const dirty =
                        note.edited_subtotal !== note.subtotal ||
                        note.edited_tax !== note.tax ||
                        note.edited_total !== note.total;
                      const expectedTax = Math.floor(note.edited_subtotal * 0.1);
                      const expectedTotal = note.edited_subtotal + note.edited_tax;
                      return (
                        <tr
                          key={note.id}
                          className={`border-t border-gray-100 ${dirty ? 'bg-yellow-50' : ''}`}
                        >
                          <td className="px-3 py-2 text-gray-800 font-mono">{note.slip_number}</td>
                          <td className="px-3 py-2 text-gray-600">{note.date}</td>
                          <td className="px-3 py-2">
                            <input
                              type="number"
                              value={note.edited_subtotal}
                              onChange={(e) =>
                                handleNoteFieldChange(note.id, 'edited_subtotal', e.target.value)
                              }
                              className="w-full border border-gray-300 rounded px-2 py-1 text-right font-mono focus:outline-none focus:ring-2 focus:ring-blue-400"
                            />
                          </td>
                          <td className="px-3 py-2">
                            <input
                              type="number"
                              value={note.edited_tax}
                              onChange={(e) =>
                                handleNoteFieldChange(note.id, 'edited_tax', e.target.value)
                              }
                              className="w-full border border-gray-300 rounded px-2 py-1 text-right font-mono focus:outline-none focus:ring-2 focus:ring-blue-400"
                            />
                            {expectedTax !== note.edited_tax && (
                              <button
                                type="button"
                                onClick={() =>
                                  handleNoteFieldChange(
                                    note.id,
                                    'edited_tax',
                                    String(expectedTax)
                                  )
                                }
                                className="text-xs text-blue-600 hover:text-blue-800 mt-1"
                                title="小計×10% を適用"
                              >
                                → {expectedTax.toLocaleString()}
                              </button>
                            )}
                          </td>
                          <td className="px-3 py-2">
                            <input
                              type="number"
                              value={note.edited_total}
                              onChange={(e) =>
                                handleNoteFieldChange(note.id, 'edited_total', e.target.value)
                              }
                              className="w-full border border-gray-300 rounded px-2 py-1 text-right font-mono focus:outline-none focus:ring-2 focus:ring-blue-400"
                            />
                            {expectedTotal !== note.edited_total && (
                              <button
                                type="button"
                                onClick={() =>
                                  handleNoteFieldChange(
                                    note.id,
                                    'edited_total',
                                    String(expectedTotal)
                                  )
                                }
                                className="text-xs text-blue-600 hover:text-blue-800 mt-1"
                                title="小計+消費税 を適用"
                              >
                                → {expectedTotal.toLocaleString()}
                              </button>
                            )}
                          </td>
                          <td className="px-3 py-2 text-center">
                            <Button
                              onClick={() => handleSaveNote(note)}
                              disabled={!dirty || note.saving}
                              variant="primary"
                              loading={note.saving}
                            >
                              保存
                            </Button>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </div>

          {/* PDF画像プレビュー */}
          <div>
            <h3 className="text-xl font-semibold text-gray-700 mb-3">
              生成された月次請求書PDF
            </h3>
            {imagesLoading ? (
              <div className="text-center py-12">
                <div className="inline-block animate-spin rounded-full h-12 w-12 border-b-2 border-primary"></div>
                <p className="mt-4 text-gray-600">画像を読み込み中...</p>
              </div>
            ) : invoiceImages.length > 0 ? (
              <div className="border border-gray-200 rounded-lg overflow-hidden">
                <div className="bg-gray-100 px-4 py-2 font-semibold text-center text-sm text-gray-700">
                  ページ {currentPage + 1} / {totalPages}
                </div>
                <div className="bg-white p-4">
                  {invoiceImages[currentPage] ? (
                    <img
                      src={invoiceImages[currentPage]}
                      alt={`月次請求書 ページ ${currentPage + 1}`}
                      className="w-full h-auto"
                    />
                  ) : loadingMore ? (
                    <div className="text-center py-12">
                      <div className="inline-block animate-spin rounded-full h-8 w-8 border-b-2 border-primary"></div>
                      <p className="mt-2 text-sm text-gray-500">読み込み中...</p>
                    </div>
                  ) : null}
                </div>
                {/* ページ切り替え */}
                {totalPages > 1 && (
                  <div className="flex items-center justify-center gap-4 py-3 bg-gray-50 border-t border-gray-200">
                    <button
                      onClick={() => handlePageChange(Math.max(0, currentPage - 1))}
                      disabled={currentPage === 0}
                      className="px-3 py-1 rounded-lg border border-gray-300 bg-white text-gray-700 hover:bg-gray-100 disabled:opacity-40 disabled:cursor-not-allowed font-bold"
                    >
                      ◀
                    </button>
                    <span className="text-sm font-medium text-gray-600">
                      ページ {currentPage + 1} / {totalPages}
                    </span>
                    <button
                      onClick={() => handlePageChange(Math.min(totalPages - 1, currentPage + 1))}
                      disabled={currentPage === totalPages - 1}
                      className="px-3 py-1 rounded-lg border border-gray-300 bg-white text-gray-700 hover:bg-gray-100 disabled:opacity-40 disabled:cursor-not-allowed font-bold"
                    >
                      ▶
                    </button>
                  </div>
                )}
              </div>
            ) : (
              <div className="border border-dashed border-gray-300 rounded-lg p-12 text-center bg-gray-50">
                <p className="text-gray-400">プレビューを生成できませんでした</p>
              </div>
            )}
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
