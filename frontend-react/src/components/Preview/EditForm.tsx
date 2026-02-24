import React, { useState } from 'react';
import { useForm } from 'react-hook-form';
import { Button } from '../Common/Button';
import { Message } from '../Common/Message';
import type { DeliveryNote, CompanyInfo, PreviousBilling } from '../../types';
import { Accordion } from '../Common/Accordion';

interface EditFormProps {
  deliveryNote: DeliveryNote;
  companyInfo: CompanyInfo | null;
  previousBilling: PreviousBilling;
  onRegenerate: (data: {
    deliveryNote: DeliveryNote;
    companyInfo: CompanyInfo | null;
    previousBilling: PreviousBilling;
  }) => Promise<void>;
  onCancel: () => void;
}

export const EditForm: React.FC<EditFormProps> = ({
  deliveryNote,
  companyInfo,
  previousBilling,
  onRegenerate,
  onCancel,
}) => {
  const { register, watch, setValue, getValues } = useForm({
    defaultValues: {
      date: deliveryNote.date,
      company_name: deliveryNote.company_name,
      slip_number: deliveryNote.slip_number,
      subtotal: deliveryNote.subtotal,
      tax: deliveryNote.tax,
      payment_received: deliveryNote.payment_received,
      previous_amount: previousBilling.previous_amount,
      payment_received_prev: previousBilling.payment_received,
      items: deliveryNote.items,
    },
  });

  const [isLoading, setIsLoading] = useState(false);

  const dateValue = watch('date');
  const datePattern = /^(20\d{2})\/(0[1-9]|1[0-2])\/(0[1-9]|[12]\d|3[01])$/;
  const isDateValid = datePattern.test(dateValue);

  // Watch all fields for calculation checks
  const watchedItems = watch('items');
  const watchedSubtotal = watch('subtotal');
  const watchedTax = watch('tax');

  // Item-level: expected amount = quantity × unit_price
  const itemExpected = !watchedItems ? [] : watchedItems.map((item: any) => {
    const qty = Number(item.quantity) || 0;
    const price = Number(item.unit_price) || 0;
    const actual = Number(item.amount) || 0;
    const expected = qty * price;
    return { expected, mismatch: expected !== actual };
  });

  // Subtotal-level: expected = sum of all item amounts
  const subtotalSum = !watchedItems ? 0 : watchedItems.reduce((acc: number, item: any) => acc + (Number(item.amount) || 0), 0);
  const subtotalExpected = { expected: subtotalSum, mismatch: subtotalSum !== (Number(watchedSubtotal) || 0) };

  // Tax-level: expected = Math.floor(subtotal * 0.1)
  const taxExp = Math.floor((Number(watchedSubtotal) || 0) * 0.1);
  const taxExpected = { expected: taxExp, mismatch: taxExp !== (Number(watchedTax) || 0) };

  const [validationError, setValidationError] = useState(false);

  const handleClick = async () => {
    // 1. 現在のフォーム値を直接取得
    const data = getValues();

    // 2. 計算チェック（一番最初）
    const items = data.items || [];
    let hasError = false;

    for (const item of items) {
      const expected = Number(item.quantity) * Number(item.unit_price);
      if (expected !== Number(item.amount)) {
        hasError = true;
        break;
      }
    }

    if (!hasError) {
      const sumAmounts = items.reduce((acc: number, item: any) => acc + Number(item.amount), 0);
      if (sumAmounts !== Number(data.subtotal)) hasError = true;
    }

    if (!hasError) {
      const expectedTax = Math.floor(Number(data.subtotal) * 0.1);
      if (expectedTax !== Number(data.tax)) hasError = true;
    }

    // 3. エラーがあれば止める
    if (hasError) {
      setValidationError(true);
      return;
    }

    // 4. チェック通過 → 再生成
    setValidationError(false);
    setIsLoading(true);
    try {
      const editedDeliveryNote: DeliveryNote = {
        date: data.date,
        company_name: data.company_name,
        slip_number: data.slip_number,
        subtotal: Number(data.subtotal),
        tax: Number(data.tax),
        total: Number(data.subtotal) + Number(data.tax),
        payment_received: Number(data.payment_received),
        items: items
          .filter((item: any) => item.product_name.trim())
          .map((item: any) => ({
            slip_number: item.slip_number || '',
            product_code: item.product_code || '',
            product_name: item.product_name,
            quantity: Number(item.quantity) || 0,
            unit_price: Number(item.unit_price) || 0,
            amount: Number(item.amount) || 0,
          })),
      };

      const editedPreviousBilling: PreviousBilling = {
        previous_amount: Number(data.previous_amount),
        payment_received: Number(data.payment_received_prev),
        carried_over: Number(data.previous_amount) - Number(data.payment_received_prev),
      };

      await onRegenerate({
        deliveryNote: editedDeliveryNote,
        companyInfo,
        previousBilling: editedPreviousBilling,
      });
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="mt-8">
      <div className="border-t-2 border-gray-200 mb-8"></div>

      <h2 className="text-3xl font-semibold text-gray-700 mb-6">
        ✏️ 請求書内容の編集
      </h2>

      <div className="bg-gray-50 border border-gray-200 rounded-xl p-8 space-y-6">
        {/* 基本情報 */}
        <div>
          <h3 className="text-xl font-semibold mb-4">基本情報</h3>

          {!isDateValid && dateValue && (
            <Message type="warning" className="mb-4">
              無効な日付形式が検出されました: `{dateValue}` → 正しい形式（YYYY/MM/DD）で入力してください
            </Message>
          )}

          <div className="grid grid-cols-2 gap-6">
            <div className="space-y-4">
              <div>
                <label className="block text-sm font-semibold text-gray-700 mb-2">
                  日付 (YYYY/MM/DD)
                </label>
                <input
                  type="text"
                  {...register('date')}
                  placeholder="2025/03/15"
                  className="w-full px-4 py-3 border border-gray-300 rounded-lg focus:outline-none focus:border-primary"
                />
              </div>

              <div>
                <label className="block text-sm font-semibold text-gray-700 mb-2">
                  会社名
                </label>
                <input
                  type="text"
                  {...register('company_name')}
                  disabled
                  className="w-full px-4 py-3 border border-gray-300 rounded-lg bg-gray-100 text-gray-500 cursor-not-allowed"
                />
              </div>

              <div>
                <label className="block text-sm font-semibold text-gray-700 mb-2">
                  伝票番号
                </label>
                <input
                  type="text"
                  {...register('slip_number')}
                  className="w-full px-4 py-3 border border-gray-300 rounded-lg focus:outline-none focus:border-primary"
                />
              </div>
            </div>

            <div className="space-y-4">
              <div>
                <label className="block text-sm font-semibold text-gray-700 mb-2">
                  小計（税抜）
                </label>
                <input
                  type="number"
                  {...register('subtotal')}
                  step="1000"
                  className={`w-full px-4 py-3 border rounded-lg focus:outline-none focus:border-primary ${
                    subtotalExpected.mismatch ? 'border-red-500 border-2' : 'border-gray-300'
                  }`}
                />
                {subtotalExpected.mismatch && (
                  <button
                    type="button"
                    onClick={() => setValue('subtotal', subtotalExpected.expected)}
                    className="text-sm text-blue-600 hover:text-blue-800 cursor-pointer mt-1"
                  >
                    → {subtotalExpected.expected.toLocaleString()} (クリックで反映)
                  </button>
                )}
              </div>

              <div>
                <label className="block text-sm font-semibold text-gray-700 mb-2">
                  消費税
                </label>
                <input
                  type="number"
                  {...register('tax')}
                  step="100"
                  className={`w-full px-4 py-3 border rounded-lg focus:outline-none focus:border-primary ${
                    taxExpected.mismatch ? 'border-red-500 border-2' : 'border-gray-300'
                  }`}
                />
                {taxExpected.mismatch && (
                  <button
                    type="button"
                    onClick={() => setValue('tax', taxExpected.expected)}
                    className="text-sm text-blue-600 hover:text-blue-800 cursor-pointer mt-1"
                  >
                    → {taxExpected.expected.toLocaleString()} (クリックで反映)
                  </button>
                )}
              </div>

              <div>
                <label className="block text-sm font-semibold text-gray-700 mb-2">
                  御入金額
                </label>
                <input
                  type="number"
                  {...register('payment_received')}
                  step="1000"
                  className="w-full px-4 py-3 border border-gray-300 rounded-lg focus:outline-none focus:border-primary"
                />
              </div>
            </div>
          </div>
        </div>

        {/* 前月情報 */}
        <div>
          <h3 className="text-xl font-semibold mb-4">前月情報</h3>
          <div className="grid grid-cols-2 gap-6">
            <div>
              <label className="block text-sm font-semibold text-gray-700 mb-2">
                前回繰越残高
              </label>
              <input
                type="number"
                {...register('previous_amount')}
                step="1000"
                disabled
                className="w-full px-4 py-3 border border-gray-300 rounded-lg bg-gray-100 text-gray-500 cursor-not-allowed"
              />
            </div>

            <div>
              <label className="block text-sm font-semibold text-gray-700 mb-2">
                前月御入金額
              </label>
              <input
                type="number"
                {...register('payment_received_prev')}
                step="1000"
                disabled
                className="w-full px-4 py-3 border border-gray-300 rounded-lg bg-gray-100 text-gray-500 cursor-not-allowed"
              />
            </div>
          </div>
        </div>

        {/* 明細情報 */}
        <div>
          <h3 className="text-xl font-semibold mb-2">明細情報</h3>
          <p className="text-sm text-gray-600 mb-4">※ 明細を編集できます。空白行は削除されます。</p>

          {isDateValid && (
            <Message type="info" className="mb-4">
              日付: <strong>{dateValue}</strong> （上の基本情報で変更できます）
            </Message>
          )}

          <div className="space-y-2">
            {deliveryNote.items.map((item, index) => (
              <Accordion key={index} title={`明細 ${index + 1}: ${item.product_name}`}>
                <div className="grid grid-cols-3 gap-4">
                  <div className="space-y-3">
                    <div>
                      <label className="block text-sm font-semibold text-gray-700 mb-1">
                        伝票番号
                      </label>
                      <input
                        type="text"
                        {...register(`items.${index}.slip_number`)}
                        className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:border-primary"
                      />
                    </div>
                    <div>
                      <label className="block text-sm font-semibold text-gray-700 mb-1">
                        商品コード
                      </label>
                      <input
                        type="text"
                        {...register(`items.${index}.product_code`)}
                        className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:border-primary"
                      />
                    </div>
                  </div>

                  <div className="space-y-3">
                    <div>
                      <label className="block text-sm font-semibold text-gray-700 mb-1">
                        品名
                      </label>
                      <input
                        type="text"
                        {...register(`items.${index}.product_name`)}
                        className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:border-primary"
                      />
                    </div>
                    <div>
                      <label className="block text-sm font-semibold text-gray-700 mb-1">
                        数量
                      </label>
                      <input
                        type="number"
                        {...register(`items.${index}.quantity`)}
                        className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:border-primary"
                      />
                    </div>
                  </div>

                  <div className="space-y-3">
                    <div>
                      <label className="block text-sm font-semibold text-gray-700 mb-1">
                        単価
                      </label>
                      <input
                        type="number"
                        {...register(`items.${index}.unit_price`)}
                        step="100"
                        className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:border-primary"
                      />
                    </div>
                    <div>
                      <label className="block text-sm font-semibold text-gray-700 mb-1">
                        金額
                      </label>
                      <input
                        type="number"
                        {...register(`items.${index}.amount`)}
                        step="100"
                        className={`w-full px-3 py-2 border rounded-lg text-sm focus:outline-none focus:border-primary ${
                          itemExpected[index]?.mismatch ? 'border-red-500 border-2' : 'border-gray-300'
                        }`}
                      />
                      {itemExpected[index]?.mismatch && (
                        <button
                          type="button"
                          onClick={() => setValue(`items.${index}.amount`, itemExpected[index].expected)}
                          className="text-sm text-blue-600 hover:text-blue-800 cursor-pointer mt-1"
                        >
                          → {itemExpected[index].expected.toLocaleString()} (クリックで反映)
                        </button>
                      )}
                    </div>
                  </div>
                </div>
              </Accordion>
            ))}
          </div>
        </div>

        {/* 計算エラーメッセージ */}
        {validationError && (
          <Message type="error">
            計算が合わない箇所があります（赤枠）。修正してからPDFを再生成してください。
          </Message>
        )}

        {/* ボタン */}
        <div className="grid grid-cols-4 gap-4 pt-4">
          <Button type="button" variant="primary" loading={isLoading} onClick={handleClick}>
            🔄 PDFを再生成
          </Button>
          <div className="col-span-3">
            <Button type="button" variant="secondary" onClick={onCancel} fullWidth>
              キャンセル
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
};
