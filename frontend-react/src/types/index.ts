export interface DeliveryItem {
  slip_number: string;
  product_code: string;
  product_name: string;
  quantity: number;
  unit_price: number;
  amount: number;
}

export interface DeliveryNote {
  date: string; // YYYY/MM/DD
  company_name: string;
  slip_number: string;
  items: DeliveryItem[];
  subtotal: number;
  tax: number;
  total: number;
  payment_received: number;
}

export interface CompanyInfo {
  company_name: string;
  postal_code: string;
  address: string;
  department: string;
}

export interface PreviousBilling {
  previous_amount: number;
  payment_received: number;
  carried_over: number;
  sales_amount?: number;
  tax_amount?: number;
  current_amount?: number;
}

export interface CompanyConfig {
  registration_number: string;
  company_name: string;
  postal_code: string;
  address: string;
  phone: string;
  bank_info: string;
}

export interface ProcessPDFResponse {
  delivery_note: DeliveryNote;
  company_info: CompanyInfo | null;
  previous_billing: PreviousBilling;
  invoice_url: string;
  delivery_pdf_url: string;
  year_month: string;
  sales_person: string;
  cumulative_subtotal: number;
  cumulative_tax: number;
  cumulative_total: number;
  cumulative_items_count: number;
  company_matched: boolean;
  sheet_company_candidates: string[];
  suggested_company_candidates: string[];
}

export interface CompaniesAndMonthsResponse {
  companies: string[];
  year_months: string[];
}

export interface BillingTableResponse {
  headers: string[];
  data: string[][];
}

export interface UpdatePaymentRequest {
  company_name: string;
  year_month: string;
  payment_amount: number;
  add_mode: boolean;
}

export interface UpdatePaymentResponse {
  success: boolean;
  message: string;
  previous_value: number;
  new_value: number;
}

export interface SaveBillingRequest {
  company_name: string;
  year_month: string;
  delivery_notes: DeliveryNote[];
  previous_billing: PreviousBilling;
  sales_person?: string;
  request_id?: string;
  force_overwrite?: boolean;
}

export interface ExistingNoteInfo {
  slip_number: string;
  date: string;
  subtotal: number;
  tax: number;
  total: number;
  sales_person: string;
  saved_at: string;
}

export interface SaveBillingResponse {
  success: boolean;
  message: string;
  saved_count?: number;
  duplicate_conflict?: boolean;
  existing_notes?: ExistingNoteInfo[];
}

export interface RegenerateInvoiceRequest {
  delivery_note: DeliveryNote;
  company_info: CompanyInfo | null;
  previous_billing: PreviousBilling;
  year_month?: string;
  sales_person?: string;
}

export interface RegenerateInvoiceResponse {
  invoice_url: string;
  invoice_filename: string;
}

// 乖離チェック関連の型定義
export interface Discrepancy {
  company_name: string;
  year_month: string;
  db_subtotal: number;
  db_tax: number;
  sheet_subtotal: number;
  sheet_tax: number;
}

export interface CheckDiscrepancyResponse {
  discrepancies: Discrepancy[];
}

export interface DBDeliveryNote {
  id: number;
  slip_number: string;
  date: string;
  subtotal: number;
  tax: number;
  total: number;
}

// 仕入れ関連の型定義
export interface PurchaseItem {
  slip_number: string;
  product_code: string;
  product_name: string;
  quantity: number;
  unit_price: number;
  amount: number;
}

export interface PurchaseInvoice {
  date: string;
  supplier_name: string;
  supplier_address: string;
  slip_number: string;
  items: PurchaseItem[];
  subtotal: number;
  tax: number;
  total: number;
  customs_duty: number;
  is_overseas: boolean;
}

export interface PaymentTerms {
  supplier_name: string;
  closing_day: string;
  payment_day: string;
  payment_method: string;
}

export interface ProcessPurchasePDFResponse {
  purchase_invoice: PurchaseInvoice;
  payment_terms: PaymentTerms | null;
  target_year_month: string;
  is_overseas: boolean;
  records_count: number;
  purchase_pdf_url: string;
}

export interface SavePurchaseRecordRequest {
  supplier_name: string;
  target_year_month: string;
  purchase_invoice: PurchaseInvoice;
}

export interface SavePurchaseRecordResponse {
  success: boolean;
  message: string;
}

// 月次請求書生成関連の型定義
export interface GenerateMonthlyInvoiceRequest {
  company_name: string;
  year_month: string;
}

export interface GenerateMonthlyInvoiceResponse {
  invoice_url: string;
  invoice_filename: string;
  delivery_notes_count: number;
  total_subtotal: number;
  total_tax: number;
  total_amount: number;
  items_count: number;
  delivery_notes: string[];
}
