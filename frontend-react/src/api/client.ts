import axios from 'axios';
import type {
  ProcessPDFResponse,
  CompaniesAndMonthsResponse,
  BillingTableResponse,
  UpdatePaymentRequest,
  UpdatePaymentResponse,
  SaveBillingRequest,
  CompanyConfig,
  RegenerateInvoiceRequest,
  RegenerateInvoiceResponse,
  ProcessPurchasePDFResponse,
  SavePurchaseRecordRequest,
  SavePurchaseRecordResponse,
  GenerateMonthlyInvoiceResponse,
  CheckDiscrepancyResponse,
  DBDeliveryNote,
  PreviousBilling,
  CompanyInfo,
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

export const saveBilling = async (data: SaveBillingRequest): Promise<{ success: boolean; message: string }> => {
  const response = await apiClient.post<{ success: boolean; message: string }>('/save-billing', data);
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
    onProgress(10, '📄 PDFからデータを抽出中...');
  }

  try {
    const response = await apiClient.post<ProcessPurchasePDFResponse>('/process-purchase-pdf', formData, {
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

export const savePurchaseRecord = async (
  data: SavePurchaseRecordRequest
): Promise<SavePurchaseRecordResponse> => {
  const response = await apiClient.post<SavePurchaseRecordResponse>('/save-purchase-record', data);
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

// 乖離チェック関連API
export const checkDiscrepancy = async (): Promise<CheckDiscrepancyResponse> => {
  const response = await apiClient.get<CheckDiscrepancyResponse>('/check-discrepancy');
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
