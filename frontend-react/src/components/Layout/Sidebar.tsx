import React, { useState } from 'react';
import { Link, useLocation } from 'react-router-dom';

interface NavItem {
  path: string;
  label: string;
}

interface NavGroup {
  title: string;
  items: NavItem[];
}

const navGroups: NavGroup[] = [
  {
    title: '売上計上',
    items: [
      { path: '/', label: '売上計上' },
      { path: '/monthly-invoice', label: '月次請求書' },
      { path: '/payment', label: '入金額入力' },
      { path: '/reconciliation', label: '乖離確認' },
    ],
  },
  {
    title: '仕入れ計上',
    items: [
      { path: '/purchase', label: '仕入れ計上' },
      { path: '/purchase-monthly', label: '月次一覧' },
      { path: '/purchase-payment', label: '入金管理' },
    ],
  },
  {
    title: '設定',
    items: [
      { path: '/settings', label: '自社情報設定' },
    ],
  },
];

const NavGroupSection: React.FC<{
  group: NavGroup;
  isOpen: boolean;
  onToggle: () => void;
}> = ({ group, isOpen, onToggle }) => {
  const location = useLocation();
  const hasActive = group.items.some((item) => item.path === location.pathname);

  return (
    <div>
      <button
        onClick={onToggle}
        className={`w-full flex items-center justify-between px-4 py-3 rounded-lg text-sm font-medium transition-colors ${
          hasActive && !isOpen
            ? 'bg-primary/10 text-primary'
            : 'text-gray-700 hover:bg-gray-200'
        }`}
      >
        <span>{group.title}</span>
        <svg
          className={`w-4 h-4 text-gray-400 transition-transform duration-200 ${
            isOpen ? 'rotate-180' : ''
          }`}
          fill="none"
          viewBox="0 0 24 24"
          stroke="currentColor"
          strokeWidth={2}
        >
          <path strokeLinecap="round" strokeLinejoin="round" d="M19 9l-7 7-7-7" />
        </svg>
      </button>

      <div
        className="overflow-hidden transition-all duration-200 ease-in-out"
        style={{
          maxHeight: isOpen ? `${group.items.length * 44}px` : '0px',
          opacity: isOpen ? 1 : 0,
        }}
      >
        <div className="ml-3 border-l-2 border-gray-200 mt-1 space-y-0.5">
          {group.items.map((item) => {
            const isActive = location.pathname === item.path;
            return (
              <Link
                key={item.path}
                to={item.path}
                className={`block pl-4 pr-4 py-2 rounded-r-lg text-sm transition-colors ${
                  isActive
                    ? 'bg-primary text-white border-l-2 border-primary -ml-[2px]'
                    : 'text-gray-600 hover:bg-gray-100 hover:text-gray-900'
                }`}
              >
                {item.label}
              </Link>
            );
          })}
        </div>
      </div>
    </div>
  );
};

export const Sidebar: React.FC = () => {
  const location = useLocation();

  // 現在のパスが属するグループを初期展開
  const [openGroups, setOpenGroups] = useState<Set<string>>(() => {
    const initial = new Set<string>();
    for (const group of navGroups) {
      if (group.items.some((item) => item.path === location.pathname)) {
        initial.add(group.title);
      }
    }
    return initial;
  });

  const handleToggle = (title: string) => {
    setOpenGroups((prev) => {
      const next = new Set(prev);
      if (next.has(title)) {
        next.delete(title);
      } else {
        next.add(title);
      }
      return next;
    });
  };

  return (
    <div className="w-72 bg-gray-50 border-r border-gray-200 h-screen fixed left-0 top-0 flex flex-col">
      <div className="p-5">
        <h2 className="text-lg font-bold text-gray-800 mb-5">売上計上システム</h2>

        <nav className="space-y-1">
          {navGroups.map((group) => (
            <NavGroupSection
              key={group.title}
              group={group}
              isOpen={openGroups.has(group.title)}
              onToggle={() => handleToggle(group.title)}
            />
          ))}
        </nav>
      </div>

      <div className="mt-auto p-5 border-t border-gray-200">
        <p className="text-xs text-gray-400">v1.0.0</p>
      </div>
    </div>
  );
};
