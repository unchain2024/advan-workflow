import React from 'react';

interface MetricCardProps {
  label: string;
  value: string | number;
  highlight?: boolean;
}

export const MetricCard: React.FC<MetricCardProps> = ({ label, value, highlight }) => {
  return (
    <div className={`rounded-lg p-4 m-2 border ${highlight ? 'bg-blue-50 border-blue-300' : 'bg-gray-50 border-gray-200'}`}>
      <div className="text-sm text-gray-600 mb-1">{label}</div>
      <div className={`text-2xl font-bold ${highlight ? 'text-blue-800' : 'text-gray-800'}`}>{value}</div>
    </div>
  );
};
