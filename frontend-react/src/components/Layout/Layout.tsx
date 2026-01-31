import React from 'react';
import { Sidebar } from './Sidebar';

interface LayoutProps {
  children: React.ReactNode;
}

export const Layout: React.FC<LayoutProps> = ({ children }) => {
  return (
    <div className="flex min-h-screen bg-white">
      <Sidebar />
      <main className="ml-80 flex-1 p-8 overflow-x-hidden" style={{ maxWidth: 'calc(100vw - 320px)' }}>
        {children}
      </main>
    </div>
  );
};
