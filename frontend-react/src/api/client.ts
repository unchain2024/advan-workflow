import axios from 'axios';
import type {
  ProcessPDFResponse,
  CompaniesAndMonthsResponse,
  BillingTableResponse,
  UpdatePaymentRequest,
  UpdatePaymentResponse,
  SaveBillingRequest,
  SaveBillingResponse,
  CompanyConfig,
  RegenerateInvoiceRequest,
  RegenerateInvoiceResponse,
  ProcessPurchasePDFResponse,
  SavePurchaseRequest,
  SavePurchaseResponse,
  UpdatePurchasePaymentRequest,
  UpdatePurchasePaymentResponse,
  PurchaseCompaniesAndMonthsResponse,
  PurchaseTableResponse,
  PurchaseMonthlyItem,
  PurchaseDeliveryNote,
  GenerateMonthlyInvoiceResponse,
  CheckDiscrepancyResponse,
  DBDeliveryNote,
  PreviousBilling,
  CompanyInfo,
  DeliveryNote,
} from '../types';

// 本番環境ではVITE_API_URLを使用、開発環境では/api（Viteプロキシ経由）
const API_BASE_URL = import.meta.env.VITE_API_URL || '/api';

const apiClient = axios.create({
  baseURL: API_BASE_URL,
  headers: {
    'Content-Type': 'application/json',
  },
});

export const processPDF = async (
  file: File,
  salesPerson: string,
  year: number,
  month: number,
  resetExisting: boolean = false,
  companyNameOverride: string = '',
  onProgress?: (progress: number, message: string) => void
): Promise<ProcessPDFResponse> => {
  const formData = new FormData();
  formData.append('file', file);
  formData.append('sales_person', salesPerson);
  formData.append('year', year.toString());
  formData.append('month', month.toString());
  formData.append('reset_existing', resetExisting.toString());
  if (companyNameOverride) {
    formData.append('company_name_override', companyNameOverride);
  }

  // シンプルなPOSTリクエスト（プログレスバーは模擬）
  if (onProgress) {
    onProgress(10, '📄 PDFからデータを抽出中...');
  }

  try {
    const response = await apiClient.post<ProcessPDFResponse>('/process-pdf', formData, {
      headers: {
        'Content-Type': 'multipart/form-data',
      },
    });

    if (onProgress) {
      onProgress(100, '✅ 処理完了');
    }

    return response.data;
  } catch (error) {
    throw error;
  }
};

export const regenerateInvoice = async (
  data: RegenerateInvoiceRequest
): Promise<RegenerateInvoiceResponse> => {
  const response = await apiClient.post<RegenerateInvoiceResponse>(
    '/regenerate-invoice',
    data
  );
  return response.data;
};

// Phase A: グループ統合請求書PDFを生成
export interface RegenerateGroupInvoiceRequest {
  company_name: string;
  year_month: string;
  delivery_notes: DeliveryNote[];
  company_info: CompanyInfo | null;
  previous_billing: PreviousBilling;
  sales_person?: string;
}

export const regenerateGroupInvoice = async (
  data: RegenerateGroupInvoiceRequest
): Promise<RegenerateInvoiceResponse> => {
  const response = await apiClient.post<RegenerateInvoiceResponse>(
    '/regenerate-group-invoice',
    data
  );
  return response.data;
};

export const saveBilling = async (data: SaveBillingRequest): Promise<SaveBillingResponse> => {
  const response = await apiClient.post<SaveBillingResponse>('/save-billing', data);
  return response.data;
};

export const updatePayment = async (data: UpdatePaymentRequest): Promise<UpdatePaymentResponse> => {
  const response = await apiClient.post<UpdatePaymentResponse>('/update-payment', data);
  return response.data;
};

export const getCompaniesAndMonths = async (): Promise<CompaniesAndMonthsResponse> => {
  const response = await apiClient.get<CompaniesAndMonthsResponse>('/companies-and-months');
  return response.data;
};

export const getBillingTable = async (): Promise<BillingTableResponse> => {
  const response = await apiClient.get<BillingTableResponse>('/billing-table');
  return response.data;
};

export const getCompanyConfig = async (): Promise<CompanyConfig> => {
  const response = await apiClient.get<CompanyConfig>('/company-config');
  return response.data;
};

export const saveCompanyConfig = async (
  data: CompanyConfig
): Promise<{ success: boolean; message: string }> => {
  const response = await apiClient.post<{ success: boolean; message: string }>('/company-config', data);
  return response.data;
};

// 仕入れ関連API
export const processPurchasePDF = async (
  file: File,
  onProgress?: (progress: number, message: string) => void
): Promise<ProcessPurchasePDFResponse> => {
  const formData = new FormData();
  formData.append('file', file);

  if (onProgress) {
    onProgress(10, 'PDFからデータを抽出中...');
  }

  try {
    const response = await apiClient.post<ProcessPurchasePDFResponse>('/process-purchase-pdf', formData, {
      headers: {
        'Content-Type': 'multipart/form-data',
      },
    });

    if (onProgress) {
      onProgress(100, '処理完了');
    }

    return response.data;
  } catch (error) {
    throw error;
  }
};

export const savePurchase = async (
  data: SavePurchaseRequest
): Promise<SavePurchaseResponse> => {
  const response = await apiClient.post<SavePurchaseResponse>('/save-purchase', data);
  return response.data;
};

export const updatePurchasePayment = async (
  data: UpdatePurchasePaymentRequest
): Promise<UpdatePurchasePaymentResponse> => {
  const response = await apiClient.post<UpdatePurchasePaymentResponse>('/update-purchase-payment', data);
  return response.data;
};

export const getPurchaseCompaniesAndMonths = async (): Promise<PurchaseCompaniesAndMonthsResponse> => {
  const response = await apiClient.get<PurchaseCompaniesAndMonthsResponse>('/purchase-companies-and-months');
  return response.data;
};

export const getPurchaseDBCompanies = async (): Promise<{ companies: string[] }> => {
  const response = await apiClient.get<{ companies: string[] }>('/purchase-db-companies');
  return response.data;
};

export const getPurchaseDBSalesPersons = async (companyName?: string): Promise<{ sales_persons: string[] }> => {
  const params = companyName ? { company_name: companyName } : {};
  const response = await apiClient.get<{ sales_persons: string[] }>('/purchase-db-sales-persons', { params });
  return response.data;
};

export const getPurchaseMonthly = async (
  companyName: string,
  yearMonth: string,
  salesPerson: string = ''
): Promise<{ items: PurchaseMonthlyItem[] }> => {
  const response = await apiClient.get<{ items: PurchaseMonthlyItem[] }>('/purchase-monthly', {
    params: { company_name: companyName, year_month: yearMonth, sales_person: salesPerson },
  });
  return response.data;
};

export const getPurchaseTable = async (): Promise<PurchaseTableResponse> => {
  const response = await apiClient.get<PurchaseTableResponse>('/purchase-table');
  return response.data;
};

export const getPurchaseDeliveryNotes = async (
  companyName: string,
  yearMonth: string
): Promise<{ notes: PurchaseDeliveryNote[] }> => {
  const response = await apiClient.get<{ notes: PurchaseDeliveryNote[] }>('/purchase-delivery-notes', {
    params: { company_name: companyName, year_month: yearMonth },
  });
  return response.data;
};

export const updatePurchaseDeliveryNote = async (
  id: number,
  subtotal: number,
  tax: number,
  total: number
): Promise<{ success: boolean }> => {
  const response = await apiClient.put<{ success: boolean }>(`/purchase-delivery-notes/${id}`, {
    subtotal,
    tax,
    total,
  });
  return response.data;
};

export const generateMonthlyInvoice = async (
  companyName: string,
  yearMonth: string,
  salesPerson: string = ''
): Promise<GenerateMonthlyInvoiceResponse> => {
  const response = await apiClient.post<GenerateMonthlyInvoiceResponse>('/generate-monthly-invoice', {
    company_name: companyName,
    year_month: yearMonth,
    sales_person: salesPerson,
  });
  return response.data;
};

// DB会社名一覧取得API
export const getDBCompanies = async (): Promise<{ companies: string[] }> => {
  const response = await apiClient.get<{ companies: string[] }>('/db-companies');
  return response.data;
};

// DB担当者名一覧取得API
export const getDBSalesPersons = async (companyName?: string): Promise<{ sales_persons: string[] }> => {
  const params = companyName ? { company_name: companyName } : {};
  const response = await apiClient.get<{ sales_persons: string[] }>('/db-sales-persons', { params });
  return response.data;
};

// 会社請求情報取得API（前月請求 + 会社情報）
export const getCompanyBillingInfo = async (companyName: string, yearMonth: string): Promise<{
  previous_billing: PreviousBilling;
  company_info: CompanyInfo | null;
}> => {
  const response = await apiClient.get<{
    previous_billing: PreviousBilling;
    company_info: CompanyInfo | null;
  }>('/company-billing-info', {
    params: { company_name: companyName, year_month: yearMonth },
  });
  return response.data;
};

// 月次請求書ページの明細編集 (Phase 5e'/編集)
export interface DeliveryItemEdit {
  product_code: string;
  product_name: string;
  quantity: number;
  unit_price: number;
  amount: number;
}

export interface DeliveryNoteWithItems {
  id: number;
  slip_number: string;
  date: string;
  subtotal: number;
  tax: number;
  total: number;
  items: DeliveryItemEdit[];
}

export const getDeliveryNotesWithItems = async (
  companyName: string,
  yearMonth: string
): Promise<{ notes: DeliveryNoteWithItems[] }> => {
  const response = await apiClient.get<{ notes: DeliveryNoteWithItems[] }>(
    '/delivery-notes-with-items',
    { params: { company_name: companyName, year_month: yearMonth } }
  );
  return response.data;
};

export const updateDeliveryNoteWithItems = async (
  noteId: number,
  date: string,
  items: DeliveryItemEdit[]
): Promise<{ success: boolean; subtotal: number; tax: number; total: number }> => {
  const response = await apiClient.put<{
    success: boolean;
    subtotal: number;
    tax: number;
    total: number;
  }>(`/delivery-notes/${noteId}/full`, { date, items });
  return response.data;
};


// 乖離チェック関連API
export const checkDiscrepancy = async (): Promise<CheckDiscrepancyResponse> => {
  const response = await apiClient.get<CheckDiscrepancyResponse>('/check-discrepancy');
  return response.data;
};

// Phase 2d: DB 集計値で売上シートを強制再同期
export interface SyncSheetsResponse {
  synced_count: number;
  failed: string[];
  message: string;
}

export const syncSheetsFromDB = async (): Promise<SyncSheetsResponse> => {
  const response = await apiClient.post<SyncSheetsResponse>('/sync-sheets-from-db');
  return response.data;
};

export const syncPurchaseSheetsFromDB = async (): Promise<SyncSheetsResponse> => {
  const response = await apiClient.post<SyncSheetsResponse>('/sync-purchase-sheets-from-db');
  return response.data;
};

export const getDeliveryNotes = async (
  companyName: string,
  yearMonth: string
): Promise<{ notes: DBDeliveryNote[] }> => {
  const response = await apiClient.get<{ notes: DBDeliveryNote[] }>('/delivery-notes', {
    params: { company_name: companyName, year_month: yearMonth },
  });
  return response.data;
};

export const updateDeliveryNote = async (
  id: number,
  subtotal: number,
  tax: number,
  total: number
): Promise<{ success: boolean }> => {
  const response = await apiClient.put<{ success: boolean }>(`/delivery-notes/${id}`, {
    subtotal,
    tax,
    total,
  });
  return response.data;
};

// --- 売上入金管理 (新設) ---

export interface LedgerEntry {
  year_month: string;
  previous_balance: number;
  opening_balance: number;
  subtotal: number;
  tax: number;
  payment_amount: number;
  carried_over: number;
  notes_count: number;
}

export interface CompanyLedgerResponse {
  company_name: string;
  entries: LedgerEntry[];
}

export interface PaymentResponse {
  id: number;
  company_name: string;
  year_month: string;
  payment_amount: number;
  opening_balance: number;
  note: string;
  sheet_synced: boolean;
  sheet_error: string;
}

export const getBillingLedger = async (
  companyName: string,
  year: number
): Promise<CompanyLedgerResponse> => {
  const response = await apiClient.get<CompanyLedgerResponse>('/billing-ledger', {
    params: { company_name: companyName, year },
  });
  return response.data;
};

export const upsertBillingPayment = async (
  companyName: string,
  yearMonth: string,
  paymentAmount: number,
  openingBalance?: number,
  note?: string,
  syncSheet: boolean = true
): Promise<PaymentResponse> => {
  const response = await apiClient.post<PaymentResponse>('/payments', {
    company_name: companyName,
    year_month: yearMonth,
    payment_amount: paymentAmount,
    opening_balance: openingBalance,
    note,
    sync_sheet: syncSheet,
  });
  return response.data;
};
