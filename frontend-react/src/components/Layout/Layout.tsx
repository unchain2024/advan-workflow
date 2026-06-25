import React from 'react';
import { Sidebar } from './Sidebar';

interface LayoutProps {
  children: React.ReactNode;
}

export const Layout: React.FC<LayoutProps> = ({ children }) => {
  return (
    <div className="flex min-h-screen bg-white">
      <Sidebar />
      <div className="ml-72 flex-1 flex flex-col overflow-x-hidden" style={{ maxWidth: 'calc(100vw - 288px)' }}>
        <main className="flex-1 p-8">
          {children}
        </main>
      </div>
    </div>
  );
};
