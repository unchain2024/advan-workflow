import React from 'react';

interface MetricCardProps {
  label: string;
  value: string | number;
}

export const MetricCard: React.FC<MetricCardProps> = ({ label, value }) => {
  return (
    <div className="bg-gray-50 border border-gray-200 rounded-lg p-4 m-2">
      <div className="text-sm text-gray-600 mb-1">{label}</div>
      <div className="text-2xl font-bold text-gray-800">{value}</div>
    </div>
  );
};
