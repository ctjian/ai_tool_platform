import { ReactNode, useState } from 'react';

interface DropdownProps {
  trigger: ReactNode;
  children: ReactNode;
  align?: 'left' | 'right';
}

export const Dropdown = ({ trigger, children, align = 'left' }: DropdownProps) => {
  const [isOpen, setIsOpen] = useState(false);

  return (
    <div className="relative inline-block">
      <div onClick={() => setIsOpen(!isOpen)}>{trigger}</div>
      {isOpen && (
        <>
          <div
            className="fixed inset-0 z-40"
            onClick={() => setIsOpen(false)}
          />
          <div
            className={`
              absolute top-full mt-2 bg-white border border-gray-200 rounded-lg shadow-lg z-50
              min-w-48 ${align === 'right' ? 'right-0' : 'left-0'}
            `}
          >
            {children}
          </div>
        </>
      )}
    </div>
  );
};

interface DropdownItemProps {
  children: ReactNode;
  onClick?: () => void;
  divider?: boolean;
}

export const DropdownItem = ({ children, onClick, divider = false }: DropdownItemProps) => {
  if (divider) {
    return <div className="border-t border-gray-200 my-1" />;
  }

  return (
    <button
      onClick={onClick}
      className="w-full text-left px-4 py-2 hover:bg-gray-100 text-gray-900 transition-colors flex items-center gap-2"
    >
      {children}
    </button>
  );
};
