import React, { useEffect } from 'react';
import { Sidebar } from './Sidebar';
import { DiscrepancyBar } from '../Common/DiscrepancyBar';
import { checkDiscrepancy } from '../../api/client';
import { useAppStore } from '../../store/useAppStore';

interface LayoutProps {
  children: React.ReactNode;
}

export const Layout: React.FC<LayoutProps> = ({ children }) => {
  const setDiscrepancies = useAppStore((s) => s.setDiscrepancies);
  const setDiscrepancyLoading = useAppStore((s) => s.setDiscrepancyLoading);

  useEffect(() => {
    const runCheck = async () => {
      setDiscrepancyLoading(true);
      try {
        const result = await checkDiscrepancy();
        setDiscrepancies(result.discrepancies);
      } catch (e) {
        console.error('乖離チェックエラー:', e);
      } finally {
        setDiscrepancyLoading(false);
      }
    };
    runCheck();
  }, [setDiscrepancies, setDiscrepancyLoading]);

  return (
    <div className="flex min-h-screen bg-white">
      <Sidebar />
      <div className="ml-72 flex-1 flex flex-col overflow-x-hidden" style={{ maxWidth: 'calc(100vw - 288px)' }}>
        <DiscrepancyBar />
        <main className="flex-1 p-8">
          {children}
        </main>
      </div>
    </div>
  );
};
