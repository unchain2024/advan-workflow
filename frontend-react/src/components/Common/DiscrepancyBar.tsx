import React from 'react';
import { useNavigate } from 'react-router-dom';
import { useAppStore } from '../../store/useAppStore';

export const DiscrepancyBar: React.FC = () => {
  const discrepancies = useAppStore((s) => s.discrepancies);
  const navigate = useNavigate();

  if (discrepancies.length === 0) {
    return null;
  }

  return (
    <div
      className="bg-red-600 text-white px-6 py-3 cursor-pointer hover:bg-red-700 transition-colors flex items-center justify-between"
      onClick={() => navigate('/reconciliation')}
    >
      <span className="font-medium">
        DB とシートの金額に {discrepancies.length} 件の乖離があります
      </span>
      <span className="text-sm opacity-80">クリックして確認 &rarr;</span>
    </div>
  );
};
