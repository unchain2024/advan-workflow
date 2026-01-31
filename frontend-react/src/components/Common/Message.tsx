import React from 'react';

interface MessageProps {
  type: 'success' | 'info' | 'warning' | 'error';
  children: React.ReactNode;
  className?: string;
}

export const Message: React.FC<MessageProps> = ({ type, children, className = '' }) => {
  const typeClasses = {
    success: 'bg-green-50 text-green-800 border-l-green-500',
    info: 'bg-blue-50 text-blue-800 border-l-blue-500',
    warning: 'bg-orange-50 text-orange-800 border-l-orange-500',
    error: 'bg-red-50 text-red-800 border-l-red-500',
  };

  const icons = {
    success: '✅',
    info: 'ℹ️',
    warning: '⚠️',
    error: '❌',
  };

  return (
    <div
      className={`px-4 py-3 border-l-4 rounded ${typeClasses[type]} ${className}`}
    >
      <span className="mr-2">{icons[type]}</span>
      {children}
    </div>
  );
};
