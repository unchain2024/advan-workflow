import React from 'react';
import { Link, useLocation } from 'react-router-dom';

export const Sidebar: React.FC = () => {
  const location = useLocation();

  const navItems = [
    { path: '/', label: '📤 納品書アップロード' },
    { path: '/payment', label: '💰 入金額入力' },
    { path: '/settings', label: '⚙️ 自社情報設定' },
  ];

  return (
    <div className="w-80 bg-gray-50 border-r border-gray-200 h-screen fixed left-0 top-0 flex flex-col">
      <div className="p-6">
        <h2 className="text-xl font-bold text-gray-800 mb-6">📄 納品書処理システム</h2>

        <nav className="space-y-2">
          {navItems.map((item) => {
            const isActive = location.pathname === item.path;
            return (
              <Link
                key={item.path}
                to={item.path}
                className={`block px-4 py-3 rounded-lg transition-colors ${
                  isActive
                    ? 'bg-primary text-white'
                    : 'text-gray-700 hover:bg-gray-200'
                }`}
              >
                {item.label}
              </Link>
            );
          })}
        </nav>
      </div>

      <div className="mt-auto p-6 border-t border-gray-200">
        <h3 className="text-sm font-semibold text-gray-600 mb-2">ℹ️ システム情報</h3>
        <p className="text-xs text-gray-500">バージョン: 1.0.0</p>
        <p className="text-xs text-gray-500">
          最終更新: {new Date().toLocaleDateString('ja-JP')}
        </p>
      </div>
    </div>
  );
};
