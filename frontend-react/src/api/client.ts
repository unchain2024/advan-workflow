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
} from '../types';

const API_BASE_URL = '/api';

const apiClient = axios.create({
  baseURL: API_BASE_URL,
  headers: {
    'Content-Type': 'application/json',
  },
});

export const processPDF = async (
  file: File,
  onProgress?: (progress: number, message: string) => void
): Promise<ProcessPDFResponse> => {
  const formData = new FormData();
  formData.append('file', file);

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
