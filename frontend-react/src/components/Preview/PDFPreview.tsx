import React, { useState } from 'react';
import { Document, Page, pdfjs } from 'react-pdf';
import 'react-pdf/dist/esm/Page/AnnotationLayer.css';
import 'react-pdf/dist/esm/Page/TextLayer.css';

// PDF.js workerの設定
pdfjs.GlobalWorkerOptions.workerSrc = `https://unpkg.com/pdfjs-dist@${pdfjs.version}/build/pdf.worker.min.js`;

interface PDFPreviewProps {
  deliveryPdfUrl: string | null;
  invoicePdfUrl: string;
}

export const PDFPreview: React.FC<PDFPreviewProps> = ({
  deliveryPdfUrl,
  invoicePdfUrl,
}) => {
  const [deliveryNumPages, setDeliveryNumPages] = useState<number>(0);
  const [invoiceNumPages, setInvoiceNumPages] = useState<number>(0);
  const [error, setError] = useState<string | null>(null);

  // 日本語ファイル名をURLエンコード
  const encodedInvoiceUrl = invoicePdfUrl
    .split('/')
    .map((part, index) => (index === invoicePdfUrl.split('/').length - 1 ? encodeURIComponent(part) : part))
    .join('/');

  const maxPages = Math.max(deliveryNumPages, invoiceNumPages);

  console.log('PDFPreview - deliveryPdfUrl:', deliveryPdfUrl);
  console.log('PDFPreview - invoicePdfUrl:', invoicePdfUrl);
  console.log('PDFPreview - encodedInvoiceUrl:', encodedInvoiceUrl);

  return (
    <div>
      <div className="border-t-2 border-gray-200 my-8"></div>

      <h2 className="text-3xl font-semibold text-gray-700 mb-6">
        📄 PDF比較プレビュー
      </h2>

      {error && (
        <div className="bg-red-50 border border-red-200 text-red-800 px-4 py-3 rounded mb-4">
          ❌ PDFの読み込みエラー: {error}
        </div>
      )}

      <div className="space-y-6">
        {Array.from({ length: maxPages }, (_, i) => (
          <div key={i} className="grid grid-cols-2 gap-6">
            {/* 納品書（左） */}
            <div>
              {deliveryPdfUrl && i < deliveryNumPages ? (
                <div className="border border-gray-200 rounded-lg overflow-hidden">
                  <div className="bg-gray-100 px-4 py-2 font-semibold text-center text-sm text-gray-700">
                    📥 納品書（入力） - ページ {i + 1}
                  </div>
                  <Document
                    file={deliveryPdfUrl}
                    onLoadSuccess={({ numPages }) => {
                      console.log('納品書PDF読み込み成功:', numPages, 'ページ');
                      setDeliveryNumPages(numPages);
                    }}
                    onLoadError={(error) => {
                      console.error('納品書PDF読み込みエラー:', error);
                      setError(`納品書PDF: ${error.message}`);
                    }}
                    loading={<div className="p-8 text-center">読み込み中...</div>}
                  >
                    <Page
                      pageNumber={i + 1}
                      width={500}
                      renderTextLayer={false}
                      renderAnnotationLayer={false}
                    />
                  </Document>
                </div>
              ) : (
                <div className="border border-dashed border-gray-300 rounded-lg p-12 text-center bg-gray-50">
                  <p className="text-gray-400">ℹ️ 納品書: このページはありません</p>
                </div>
              )}
            </div>

            {/* 請求書（右） */}
            <div>
              {i < invoiceNumPages ? (
                <div className="border border-gray-200 rounded-lg overflow-hidden">
                  <div className="bg-gray-100 px-4 py-2 font-semibold text-center text-sm text-gray-700">
                    📤 請求書（生成） - ページ {i + 1}
                  </div>
                  <Document
                    file={encodedInvoiceUrl}
                    onLoadSuccess={({ numPages }) => {
                      console.log('請求書PDF読み込み成功:', numPages, 'ページ');
                      setInvoiceNumPages(numPages);
                    }}
                    onLoadError={(error) => {
                      console.error('請求書PDF読み込みエラー:', error);
                      setError(`請求書PDF: ${error.message}`);
                    }}
                    loading={<div className="p-8 text-center">読み込み中...</div>}
                  >
                    <Page
                      pageNumber={i + 1}
                      width={500}
                      renderTextLayer={false}
                      renderAnnotationLayer={false}
                    />
                  </Document>
                </div>
              ) : (
                <div className="border border-dashed border-gray-300 rounded-lg p-12 text-center bg-gray-50">
                  <p className="text-gray-400">ℹ️ 請求書: このページはありません</p>
                </div>
              )}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
};
