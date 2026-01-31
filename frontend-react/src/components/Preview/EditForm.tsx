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
  const { register, handleSubmit, watch } = useForm({
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

  const onSubmit = async (data: any) => {
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
        items: data.items.filter((item: any) => item.product_name.trim()),
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

      <form onSubmit={handleSubmit(onSubmit)} className="bg-gray-50 border border-gray-200 rounded-xl p-8 space-y-6">
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
                  className="w-full px-4 py-3 border border-gray-300 rounded-lg focus:outline-none focus:border-primary"
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
                  className="w-full px-4 py-3 border border-gray-300 rounded-lg focus:outline-none focus:border-primary"
                />
              </div>

              <div>
                <label className="block text-sm font-semibold text-gray-700 mb-2">
                  消費税
                </label>
                <input
                  type="number"
                  {...register('tax')}
                  step="100"
                  className="w-full px-4 py-3 border border-gray-300 rounded-lg focus:outline-none focus:border-primary"
                />
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
                className="w-full px-4 py-3 border border-gray-300 rounded-lg focus:outline-none focus:border-primary"
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
                className="w-full px-4 py-3 border border-gray-300 rounded-lg focus:outline-none focus:border-primary"
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
                        className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:border-primary"
                      />
                    </div>
                  </div>
                </div>
              </Accordion>
            ))}
          </div>
        </div>

        {/* 送信ボタン */}
        <div className="grid grid-cols-4 gap-4 pt-4">
          <Button type="submit" variant="primary" loading={isLoading}>
            🔄 PDFを再生成
          </Button>
          <div className="col-span-3">
            <Button type="button" variant="secondary" onClick={onCancel} fullWidth>
              キャンセル
            </Button>
          </div>
        </div>
      </form>
    </div>
  );
};
