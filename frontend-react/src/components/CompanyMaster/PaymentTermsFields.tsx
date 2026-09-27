import React from 'react';
import {
  CLOSING_DAY_OPTIONS,
  PAYMENT_DAY_OPTIONS,
  PAYMENT_MONTH_OPTIONS,
  buildPaymentDay,
  parsePaymentDay,
  type PaymentMonth,
} from '../../utils/paymentTerms';

interface Props {
  closingDay: string;
  paymentDay: string;
  onChange: (next: { closing_day: string; payment_day: string }) => void;
  inputCls: string;
  /** 一覧のインライン編集ではラベルを省く */
  compact?: boolean;
}

/**
 * 締め日・支払日の入力（プルダウンのみ。自由入力はさせない）
 *  - 締め日: 未設定 / 月末 / 1〜30日
 *  - 支払日: 支払月（当月/翌月/翌々月）× 日（末日/1〜30日）
 */
export const PaymentTermsFields: React.FC<Props> = ({
  closingDay,
  paymentDay,
  onChange,
  inputCls,
  compact = false,
}) => {
  const parsed = parsePaymentDay(paymentDay);
  const payMonth: PaymentMonth | '' = parsed?.month ?? '';
  const payDay = parsed?.day ?? '';

  const setPayment = (month: PaymentMonth | '', day: string) => {
    // 月だけ選んだら末日を既定にして即座に有効な値にする
    const effectiveDay = month && !day ? '末' : day;
    onChange({ closing_day: closingDay, payment_day: buildPaymentDay(month, effectiveDay) });
  };

  return (
    <div className={compact ? 'flex flex-col gap-1' : 'contents'}>
      <div>
        {!compact && <label className="block text-xs font-medium text-gray-600 mb-1">締め日</label>}
        <select
          className={inputCls}
          value={closingDay}
          onChange={(e) => onChange({ closing_day: e.target.value, payment_day: paymentDay })}
          title="締め日"
        >
          {CLOSING_DAY_OPTIONS.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </select>
      </div>
      <div>
        {!compact && <label className="block text-xs font-medium text-gray-600 mb-1">支払日</label>}
        <div className="flex gap-1">
          <select
            className={inputCls}
            value={payMonth}
            onChange={(e) => setPayment(e.target.value as PaymentMonth | '', payDay)}
            title="支払月"
          >
            <option value="">未設定</option>
            {PAYMENT_MONTH_OPTIONS.map((m) => (
              <option key={m} value={m}>
                {m}
              </option>
            ))}
          </select>
          <select
            className={inputCls}
            value={payDay}
            onChange={(e) => setPayment(payMonth, e.target.value)}
            disabled={!payMonth}
            title="支払日"
          >
            {!payMonth && <option value="">—</option>}
            {PAYMENT_DAY_OPTIONS.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </select>
        </div>
      </div>
    </div>
  );
};
