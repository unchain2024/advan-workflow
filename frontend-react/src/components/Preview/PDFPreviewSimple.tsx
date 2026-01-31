import React from 'react';

interface PDFPreviewSimpleProps {
  deliveryPdfUrl: string | null;
  invoicePdfUrl: string;
}

export const PDFPreviewSimple: React.FC<PDFPreviewSimpleProps> = ({
  deliveryPdfUrl,
  invoicePdfUrl,
}) => {
  // 日本語ファイル名をURLエンコード
  const encodedInvoiceUrl = invoicePdfUrl
    .split('/')
    .map((part, index) => (index === invoicePdfUrl.split('/').length - 1 ? encodeURIComponent(part) : part))
    .join('/');

  console.log('PDFPreviewSimple - deliveryPdfUrl:', deliveryPdfUrl);
  console.log('PDFPreviewSimple - encodedInvoiceUrl:', encodedInvoiceUrl);

  return (
    <div>
      <div className="border-t-2 border-gray-200 my-8"></div>

      <h2 className="text-3xl font-semibold text-gray-700 mb-6">
        📄 PDF比較プレビュー
      </h2>

      <div className="grid grid-cols-2 gap-6">
        {/* 納品書（左） */}
        <div>
          <div className="border border-gray-200 rounded-lg overflow-hidden">
            <div className="bg-gray-100 px-4 py-2 font-semibold text-center text-sm text-gray-700">
              📥 納品書（入力）
            </div>
            {deliveryPdfUrl ? (
              <iframe
                src={deliveryPdfUrl}
                className="w-full h-[600px] border-0"
                title="納品書PDF"
              />
            ) : (
              <div className="p-12 text-center bg-gray-50">
                <p className="text-gray-400">納品書がありません</p>
              </div>
            )}
          </div>
        </div>

        {/* 請求書（右） */}
        <div>
          <div className="border border-gray-200 rounded-lg overflow-hidden">
            <div className="bg-gray-100 px-4 py-2 font-semibold text-center text-sm text-gray-700">
              📤 請求書（生成）
            </div>
            <iframe
              src={encodedInvoiceUrl}
              className="w-full h-[600px] border-0"
              title="請求書PDF"
            />
          </div>
        </div>
      </div>

      <div className="mt-4 text-sm text-gray-500 text-center">
        PDFが表示されない場合は、以下のリンクから直接開いてください：
        <br />
        <a
          href={encodedInvoiceUrl}
          target="_blank"
          rel="noopener noreferrer"
          className="text-primary hover:underline"
        >
          請求書PDFを新しいタブで開く
        </a>
      </div>
    </div>
  );
};
