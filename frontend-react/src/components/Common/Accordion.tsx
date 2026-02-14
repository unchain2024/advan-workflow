import React, { useState } from 'react';

interface AccordionProps {
  title: string;
  defaultOpen?: boolean;
  children: React.ReactNode;
}

export const Accordion: React.FC<AccordionProps> = ({
  title,
  defaultOpen = false,
  children,
}) => {
  const [isOpen, setIsOpen] = useState(defaultOpen);

  return (
    <div className="border border-gray-200 rounded-lg mb-2">
      <button
        type="button"
        className="w-full px-4 py-3 text-left bg-gray-50 hover:bg-gray-100 rounded-lg transition-colors flex items-center justify-between"
        onClick={() => setIsOpen(!isOpen)}
      >
        <span className="font-semibold">{title}</span>
        <span className="text-gray-500">
          {isOpen ? '▼' : '▶'}
        </span>
      </button>
      <div className={isOpen ? 'p-4 border-t border-gray-200' : 'hidden'}>
        {children}
      </div>
    </div>
  );
};
