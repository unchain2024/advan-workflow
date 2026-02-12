import { create } from 'zustand';
import type { DeliveryNote, DeliveryItem, CompanyInfo, PreviousBilling } from '../types';

interface AppState {
  // セッション状態
  salesPerson: string;
  selectedYear: number;
  selectedMonth: number;
  showEditForm: boolean;
  spreadsheetSaved: boolean;
  currentDeliveryNote: DeliveryNote | null;
  currentCompanyInfo: CompanyInfo | null;
  currentPreviousBilling: PreviousBilling | null;
  currentInvoicePath: string | null;
  currentYearMonth: string | null;
  currentDeliveryPdf: string | null;
  deliveryPdfUrls: string[];
  cumulativeSubtotal: number;
  cumulativeTax: number;
  cumulativeTotal: number;
  cumulativeItemsCount: number;
  cumulativeItems: DeliveryItem[];

  // アクション
  setSalesPerson: (name: string) => void;
  setSelectedYear: (year: number) => void;
  setSelectedMonth: (month: number) => void;
  setShowEditForm: (show: boolean) => void;
  setSpreadsheetSaved: (saved: boolean) => void;
  setCurrentDeliveryNote: (note: DeliveryNote | null) => void;
  setCurrentCompanyInfo: (info: CompanyInfo | null) => void;
  setCurrentPreviousBilling: (billing: PreviousBilling | null) => void;
  setCurrentInvoicePath: (path: string | null) => void;
  setCurrentYearMonth: (yearMonth: string | null) => void;
  setCurrentDeliveryPdf: (path: string | null) => void;
  addDeliveryPdfUrl: (url: string) => void;
  addCumulativeItems: (items: DeliveryItem[]) => void;

  // 処理結果をまとめてセット
  setProcessResult: (result: {
    deliveryNote: DeliveryNote;
    companyInfo: CompanyInfo | null;
    previousBilling: PreviousBilling;
    invoicePath: string;
    yearMonth: string;
    cumulativeSubtotal: number;
    cumulativeTax: number;
    cumulativeTotal: number;
    cumulativeItemsCount: number;
  }) => void;

  // すべてクリア
  clearAll: () => void;
}

export const useAppStore = create<AppState>((set) => ({
  // 初期状態
  salesPerson: '',
  selectedYear: new Date().getFullYear(),
  selectedMonth: new Date().getMonth() + 1,
  showEditForm: false,
  spreadsheetSaved: false,
  currentDeliveryNote: null,
  currentCompanyInfo: null,
  currentPreviousBilling: null,
  currentInvoicePath: null,
  currentYearMonth: null,
  currentDeliveryPdf: null,
  deliveryPdfUrls: [],
  cumulativeSubtotal: 0,
  cumulativeTax: 0,
  cumulativeTotal: 0,
  cumulativeItemsCount: 0,
  cumulativeItems: [],

  // アクション
  setSalesPerson: (name) => set({ salesPerson: name }),
  setSelectedYear: (year) => set({ selectedYear: year }),
  setSelectedMonth: (month) => set({ selectedMonth: month }),
  setShowEditForm: (show) => set({ showEditForm: show }),
  setSpreadsheetSaved: (saved) => set({ spreadsheetSaved: saved }),
  setCurrentDeliveryNote: (note) => set({ currentDeliveryNote: note }),
  setCurrentCompanyInfo: (info) => set({ currentCompanyInfo: info }),
  setCurrentPreviousBilling: (billing) => set({ currentPreviousBilling: billing }),
  setCurrentInvoicePath: (path) => set({ currentInvoicePath: path }),
  setCurrentYearMonth: (yearMonth) => set({ currentYearMonth: yearMonth }),
  setCurrentDeliveryPdf: (path) => set({ currentDeliveryPdf: path }),
  addDeliveryPdfUrl: (url) => set((state) => ({ deliveryPdfUrls: [...state.deliveryPdfUrls, url] })),
  addCumulativeItems: (items) => set((state) => ({ cumulativeItems: [...state.cumulativeItems, ...items] })),

  setProcessResult: (result) => set({
    currentDeliveryNote: result.deliveryNote,
    currentCompanyInfo: result.companyInfo,
    currentPreviousBilling: result.previousBilling,
    currentInvoicePath: result.invoicePath,
    currentYearMonth: result.yearMonth,
    cumulativeSubtotal: result.cumulativeSubtotal,
    cumulativeTax: result.cumulativeTax,
    cumulativeTotal: result.cumulativeTotal,
    cumulativeItemsCount: result.cumulativeItemsCount,
    spreadsheetSaved: false,
    showEditForm: false,
  }),

  clearAll: () => set({
    salesPerson: '',
    selectedYear: new Date().getFullYear(),
    selectedMonth: new Date().getMonth() + 1,
    showEditForm: false,
    spreadsheetSaved: false,
    currentDeliveryNote: null,
    currentCompanyInfo: null,
    currentPreviousBilling: null,
    currentInvoicePath: null,
    currentYearMonth: null,
    currentDeliveryPdf: null,
    deliveryPdfUrls: [],
    cumulativeSubtotal: 0,
    cumulativeTax: 0,
    cumulativeTotal: 0,
    cumulativeItemsCount: 0,
    cumulativeItems: [],
  }),
}));
