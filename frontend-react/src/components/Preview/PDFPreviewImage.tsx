import React, { useState, useEffect } from 'react';

interface PDFPreviewImageProps {
  deliveryPdfUrl: string | null;
  invoicePdfUrl: string;
}

export const PDFPreviewImage: React.FC<PDFPreviewImageProps> = ({
  deliveryPdfUrl,
  invoicePdfUrl,
}) => {
  const [invoiceImages, setInvoiceImages] = useState<string[]>([]);
  const [deliveryImage, setDeliveryImage] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const loadImages = async () => {
      setLoading(true);
      setError(null);

      try {
        // 請求書PDFを画像に変換
        // URLからクエリパラメータを除去してファイル名を取得
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

        // 納品書PDFも画像に変換
        if (deliveryPdfUrl) {
          // URLからクエリパラメータを除去してファイル名を取得
          const deliveryUrl = deliveryPdfUrl.split('?')[0];
          const deliveryFilename = deliveryUrl.split('/').pop();
          if (deliveryFilename) {
            const response = await fetch(`/api/pdf-to-images/${encodeURIComponent(deliveryFilename)}`);
            if (!response.ok) {
              throw new Error('納品書の画像変換に失敗しました');
            }
            const data = await response.json();
            // 納品書は最初のページのみ使用
            if (data.images.length > 0) {
              setDeliveryImage(data.images[0]);
            }
          }
        }
      } catch (err) {
        setError(err instanceof Error ? err.message : '画像の読み込みに失敗しました');
      } finally {
        setLoading(false);
      }
    };

    loadImages();
  }, [invoicePdfUrl, deliveryPdfUrl]);

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

  const maxPages = Math.max(invoiceImages.length, deliveryImage ? 1 : 0);

  return (
    <div>
      <div className="border-t-2 border-gray-200 my-8"></div>

      <h2 className="text-3xl font-semibold text-gray-700 mb-6">
        📄 PDF比較プレビュー
      </h2>

      <div className="space-y-6">
        {Array.from({ length: maxPages }, (_, i) => (
          <div key={i} className="grid grid-cols-2 gap-6">
            {/* 納品書（左） */}
            <div>
              {deliveryImage && i === 0 ? (
                <div className="border border-gray-200 rounded-lg overflow-hidden">
                  <div className="bg-gray-100 px-4 py-2 font-semibold text-center text-sm text-gray-700">
                    📥 納品書（入力）
                  </div>
                  <div className="bg-white p-4">
                    <img
                      src={deliveryImage}
                      alt="納品書"
                      className="w-full h-auto"
                    />
                  </div>
                </div>
              ) : (
                <div className="border border-dashed border-gray-300 rounded-lg p-12 text-center bg-gray-50">
                  <p className="text-gray-400">ℹ️ 納品書: このページはありません</p>
                </div>
              )}
            </div>

            {/* 請求書（右） */}
            <div>
              {i < invoiceImages.length ? (
                <div className="border border-gray-200 rounded-lg overflow-hidden">
                  <div className="bg-gray-100 px-4 py-2 font-semibold text-center text-sm text-gray-700">
                    📤 請求書（生成） - ページ {i + 1}
                  </div>
                  <div className="bg-white p-4">
                    <img
                      src={invoiceImages[i]}
                      alt={`請求書 ページ ${i + 1}`}
                      className="w-full h-auto"
                    />
                  </div>
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
