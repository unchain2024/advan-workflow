/**
 * 支払条件（締め日・支払日）のフロント側ユーティリティ
 *
 * 形式はバックエンド src/payment_terms.py と揃える:
 *   closing_day: "" (未設定=月末) | "月末" | "N日"
 *   payment_day: "" (未設定) | "{当月|翌月|翌々月}{末|N日}"
 */

/** 締め日の選択肢（プルダウン用） */
export const CLOSING_DAY_OPTIONS: { value: string; label: string }[] = [
  { value: '', label: '未設定（月末締めとして扱う）' },
  { value: '月末', label: '月末' },
  ...Array.from({ length: 30 }, (_, i) => ({ value: `${i + 1}日`, label: `${i + 1}日` })),
];

export const PAYMENT_MONTH_OPTIONS = ['当月', '翌月', '翌々月'] as const;
export type PaymentMonth = (typeof PAYMENT_MONTH_OPTIONS)[number];

export const PAYMENT_DAY_OPTIONS: { value: string; label: string }[] = [
  { value: '末', label: '末日' },
  ...Array.from({ length: 30 }, (_, i) => ({ value: `${i + 1}日`, label: `${i + 1}日` })),
];

/** "翌月10日" → { month: "翌月", day: "10日" } / "" → null */
export function parsePaymentDay(value: string): { month: PaymentMonth; day: string } | null {
  const m = (value || '').match(/^(当月|翌月|翌々月)(末|\d{1,2}日)$/);
  if (!m) return null;
  return { month: m[1] as PaymentMonth, day: m[2] };
}

export function buildPaymentDay(month: PaymentMonth | '', day: string): string {
  if (!month || !day) return '';
  return `${month}${day}`;
}

/** 表示用: "" → "未設定" */
export function paymentDayLabel(value: string): string {
  const p = parsePaymentDay(value);
  if (!p) return '未設定';
  return `${p.month}${p.day === '末' ? '末日' : p.day}`;
}

export function closingDayLabel(value: string): string {
  return value ? value : '未設定（月末）';
}

function parseDate(dateStr: string): { y: number; m: number; d: number | null } | null {
  const s = (dateStr || '').trim().replace(/-/g, '/');
  let m = s.match(/^(\d{4})\/(\d{1,2})(?:\/(\d{1,2}))?/);
  if (!m) m = s.match(/^(\d{4})年(\d{1,2})月(?:(\d{1,2})日)?/);
  if (!m) return null;
  const y = Number(m[1]);
  const mo = Number(m[2]);
  if (mo < 1 || mo > 12) return null;
  return { y, m: mo, d: m[3] ? Number(m[3]) : null };
}

/**
 * 納品日と締め日から計上月（"YYYY年M月"）を返す。日付が読めなければ ""。
 * 月末締め（未設定含む）: 納品日の月。N日締め: 納品日 > N なら翌月。
 */
export function computeTargetYearMonth(deliveryDate: string, closingDay: string): string {
  const p = parseDate(deliveryDate);
  if (!p) return '';
  let { y, m } = p;
  const n = closingDay && closingDay !== '月末' ? Number(closingDay.replace('日', '')) : NaN;
  if (!Number.isNaN(n) && p.d !== null && p.d > n) {
    if (m === 12) {
      y += 1;
      m = 1;
    } else {
      m += 1;
    }
  }
  return `${y}年${m}月`;
}

/** "2026年7月" → { year: 2026, month: 7 } / 不正なら null */
export function parseYearMonth(ym: string): { year: number; month: number } | null {
  const m = (ym || '').match(/^(\d{4})年(\d{1,2})月$/);
  if (!m) return null;
  return { year: Number(m[1]), month: Number(m[2]) };
}

/** "2026年7月" → "2026-07"（API 送信用） */
export function yearMonthToApi(ym: string): string {
  const p = parseYearMonth(ym);
  if (!p) return '';
  return `${p.year}-${String(p.month).padStart(2, '0')}`;
}
