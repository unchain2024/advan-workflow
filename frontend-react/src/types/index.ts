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
  delivery_note: DeliveryNote;
  previous_billing: PreviousBilling;
}

export interface RegenerateInvoiceRequest {
  delivery_note: DeliveryNote;
  company_info: CompanyInfo | null;
  previous_billing: PreviousBilling;
}

export interface RegenerateInvoiceResponse {
  invoice_url: string;
  invoice_filename: string;
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
