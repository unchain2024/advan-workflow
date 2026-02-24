import { create } from 'zustand';
import type { DeliveryNote, DeliveryItem, CompanyInfo, PreviousBilling, Discrepancy } from '../types';

interface AppState {
  // 乖離チェック状態
  discrepancies: Discrepancy[];
  discrepancyLoading: boolean;
  setDiscrepancies: (d: Discrepancy[]) => void;
  setDiscrepancyLoading: (l: boolean) => void;

  // セッション状態
  salesPerson: string;
  selectedYear: number;
  selectedMonth: number;
  showEditForm: boolean;
  spreadsheetSaved: boolean;
  allDeliveryNotes: DeliveryNote[];
  currentDeliveryNote: DeliveryNote | null;
  currentCompanyInfo: CompanyInfo | null;
  currentPreviousBilling: PreviousBilling | null;
  currentInvoicePath: string | null;
  currentYearMonth: string | null;
  currentDeliveryPdf: string | null;
  deliveryPdfUrls: string[];

  // アクション
  setSalesPerson: (name: string) => void;
  setSelectedYear: (year: number) => void;
  setSelectedMonth: (month: number) => void;
  setShowEditForm: (show: boolean) => void;
  setSpreadsheetSaved: (saved: boolean) => void;
  addDeliveryNote: (note: DeliveryNote) => void;
  setCurrentDeliveryNote: (note: DeliveryNote | null) => void;
  setCurrentCompanyInfo: (info: CompanyInfo | null) => void;
  setCurrentPreviousBilling: (billing: PreviousBilling | null) => void;
  setCurrentInvoicePath: (path: string | null) => void;
  setCurrentYearMonth: (yearMonth: string | null) => void;
  setCurrentDeliveryPdf: (path: string | null) => void;
  addDeliveryPdfUrl: (url: string) => void;

  // 処理結果をまとめてセット
  setProcessResult: (result: {
    deliveryNote: DeliveryNote;
    companyInfo: CompanyInfo | null;
    previousBilling: PreviousBilling;
    invoicePath: string;
    yearMonth: string;
  }) => void;

  // すべてクリア
  clearAll: () => void;
}

export const useAppStore = create<AppState>((set) => ({
  // 乖離チェック初期状態
  discrepancies: [],
  discrepancyLoading: false,
  setDiscrepancies: (d) => set({ discrepancies: d }),
  setDiscrepancyLoading: (l) => set({ discrepancyLoading: l }),

  // 初期状態
  salesPerson: '',
  selectedYear: new Date().getFullYear(),
  selectedMonth: new Date().getMonth() + 1,
  showEditForm: false,
  spreadsheetSaved: false,
  allDeliveryNotes: [],
  currentDeliveryNote: null,
  currentCompanyInfo: null,
  currentPreviousBilling: null,
  currentInvoicePath: null,
  currentYearMonth: null,
  currentDeliveryPdf: null,
  deliveryPdfUrls: [],

  // アクション
  setSalesPerson: (name) => set({ salesPerson: name }),
  setSelectedYear: (year) => set({ selectedYear: year }),
  setSelectedMonth: (month) => set({ selectedMonth: month }),
  setShowEditForm: (show) => set({ showEditForm: show }),
  setSpreadsheetSaved: (saved) => set({ spreadsheetSaved: saved }),
  addDeliveryNote: (note) => set((state) => ({ allDeliveryNotes: [...state.allDeliveryNotes, note] })),
  setCurrentDeliveryNote: (note) => set({ currentDeliveryNote: note }),
  setCurrentCompanyInfo: (info) => set({ currentCompanyInfo: info }),
  setCurrentPreviousBilling: (billing) => set({ currentPreviousBilling: billing }),
  setCurrentInvoicePath: (path) => set({ currentInvoicePath: path }),
  setCurrentYearMonth: (yearMonth) => set({ currentYearMonth: yearMonth }),
  setCurrentDeliveryPdf: (path) => set({ currentDeliveryPdf: path }),
  addDeliveryPdfUrl: (url) => set((state) => ({ deliveryPdfUrls: [...state.deliveryPdfUrls, url] })),

  setProcessResult: (result) => set({
    currentDeliveryNote: result.deliveryNote,
    currentCompanyInfo: result.companyInfo,
    currentPreviousBilling: result.previousBilling,
    currentInvoicePath: result.invoicePath,
    currentYearMonth: result.yearMonth,
    spreadsheetSaved: false,
    showEditForm: false,
  }),

  clearAll: () => set({
    showEditForm: false,
    spreadsheetSaved: false,
    allDeliveryNotes: [],
    currentDeliveryNote: null,
    currentCompanyInfo: null,
    currentPreviousBilling: null,
    currentInvoicePath: null,
    currentYearMonth: null,
    currentDeliveryPdf: null,
    deliveryPdfUrls: [],
  }),
}));

// --- 導出セレクタ（allDeliveryNotes から算出） ---

export const selectCumulativeSubtotal = (state: AppState) =>
  state.allDeliveryNotes.reduce((acc, n) => acc + n.subtotal, 0);

export const selectCumulativeTax = (state: AppState) =>
  state.allDeliveryNotes.reduce((acc, n) => acc + n.tax, 0);

export const selectCumulativeTotal = (state: AppState) =>
  state.allDeliveryNotes.reduce((acc, n) => acc + n.subtotal + n.tax, 0);

export const selectCumulativeItemsCount = (state: AppState) =>
  state.allDeliveryNotes.reduce((acc, n) => acc + n.items.length, 0);

export const selectCumulativeItems = (state: AppState): DeliveryItem[] =>
  state.allDeliveryNotes.flatMap((n) => n.items);
