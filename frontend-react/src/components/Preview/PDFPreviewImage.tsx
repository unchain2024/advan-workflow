import React, { useState, useEffect } from 'react';

interface PDFPreviewImageProps {
  deliveryPdfUrls: string[];
  invoicePdfUrl: string;
}

export const PDFPreviewImage: React.FC<PDFPreviewImageProps> = ({
  deliveryPdfUrls,
  invoicePdfUrl,
}) => {
  const [invoiceImages, setInvoiceImages] = useState<string[]>([]);
  const [deliveryPages, setDeliveryPages] = useState<string[]>([]);
  const [currentDeliveryPage, setCurrentDeliveryPage] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const loadImages = async () => {
      setLoading(true);
      setError(null);

      try {
        // 請求書PDFを画像に変換
        const invoiceUrl = invoicePdfUrl.split('?')[0];
        const invoiceFilename = invoiceUrl.split('/').pop();
        if (invoiceFilename) {
          const response = await fetch(`/api/pdf-to-images/${encodeURIComponent(invoiceFilename)}`);
          if (!response.ok) {
            throw new Error('請求書の画像変換に失敗しました');
          }
          const data = await response.json();
          setInvoiceImages(data.images);
        }

        // 全ての納品書PDFの全ページを画像に変換
        const allPages: string[] = [];
        for (const pdfUrl of deliveryPdfUrls) {
          const deliveryUrl = pdfUrl.split('?')[0];
          const deliveryFilename = deliveryUrl.split('/').pop();
          if (deliveryFilename) {
            try {
              const response = await fetch(`/api/pdf-to-images/${encodeURIComponent(deliveryFilename)}`);
              if (response.ok) {
                const data = await response.json();
                allPages.push(...data.images);
              }
            } catch {
              // skip
            }
          }
        }
        setDeliveryPages(allPages);
        setCurrentDeliveryPage(0);
      } catch (err) {
        setError(err instanceof Error ? err.message : '画像の読み込みに失敗しました');
      } finally {
        setLoading(false);
      }
    };

    loadImages();
  }, [invoicePdfUrl, deliveryPdfUrls]);

  if (loading) {
    return (
      <div className="text-center py-12">
        <div className="inline-block animate-spin rounded-full h-12 w-12 border-b-2 border-primary"></div>
        <p className="mt-4 text-gray-600">画像を読み込み中...</p>
      </div>
    );
  }

  if (error) {
    return (
      <div className="bg-red-50 border border-red-200 text-red-800 px-4 py-3 rounded">
        ❌ エラー: {error}
      </div>
    );
  }

  const totalPages = deliveryPages.length;
  const currentPageImage = totalPages > 0 ? deliveryPages[currentDeliveryPage] : null;

  return (
    <div>
      <div className="border-t-2 border-gray-200 my-8"></div>

      <h2 className="text-3xl font-semibold text-gray-700 mb-6">
        📄 PDF比較プレビュー
      </h2>

      <div className="grid grid-cols-2 gap-6">
        {/* 納品書（左） */}
        <div>
          {currentPageImage ? (
            <div className="border border-gray-200 rounded-lg overflow-hidden">
              <div className="bg-gray-100 px-4 py-2 font-semibold text-center text-sm text-gray-700">
                📥 納品書（入力）
              </div>
              <div className="bg-white p-4">
                <img
                  src={currentPageImage}
                  alt={`納品書 ページ ${currentDeliveryPage + 1}`}
                  className="w-full h-auto"
                />
              </div>
              {/* ページ切り替え */}
              {totalPages > 1 && (
                <div className="flex items-center justify-center gap-4 py-3 bg-gray-50 border-t border-gray-200">
                  <button
                    onClick={() => setCurrentDeliveryPage((prev) => Math.max(0, prev - 1))}
                    disabled={currentDeliveryPage === 0}
                    className="px-3 py-1 rounded-lg border border-gray-300 bg-white text-gray-700 hover:bg-gray-100 disabled:opacity-40 disabled:cursor-not-allowed font-bold"
                  >
                    ◀
                  </button>
                  <span className="text-sm font-medium text-gray-600">
                    ページ {currentDeliveryPage + 1} / {totalPages}
                  </span>
                  <button
                    onClick={() => setCurrentDeliveryPage((prev) => Math.min(totalPages - 1, prev + 1))}
                    disabled={currentDeliveryPage === totalPages - 1}
                    className="px-3 py-1 rounded-lg border border-gray-300 bg-white text-gray-700 hover:bg-gray-100 disabled:opacity-40 disabled:cursor-not-allowed font-bold"
                  >
                    ▶
                  </button>
                </div>
              )}
            </div>
          ) : (
            <div className="border border-dashed border-gray-300 rounded-lg p-12 text-center bg-gray-50">
              <p className="text-gray-400">ℹ️ 納品書: プレビューなし</p>
            </div>
          )}
        </div>

        {/* 請求書（右） */}
        <div>
          <div className="space-y-4">
            {invoiceImages.map((img, i) => (
              <div key={i} className="border border-gray-200 rounded-lg overflow-hidden">
                <div className="bg-gray-100 px-4 py-2 font-semibold text-center text-sm text-gray-700">
                  📤 請求書（生成） - ページ {i + 1}
                </div>
                <div className="bg-white p-4">
                  <img
                    src={img}
                    alt={`請求書 ページ ${i + 1}`}
                    className="w-full h-auto"
                  />
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
};
