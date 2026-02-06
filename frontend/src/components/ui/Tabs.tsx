import { ReactNode, useState } from 'react';

interface TabsProps {
  tabs: Array<{
    label: string;
    content: ReactNode;
    icon?: ReactNode;
  }>;
  defaultTab?: number;
  onChange?: (index: number) => void;
}

export const Tabs = ({ tabs, defaultTab = 0, onChange }: TabsProps) => {
  const [activeTab, setActiveTab] = useState(defaultTab);

  const handleTabChange = (index: number) => {
    setActiveTab(index);
    onChange?.(index);
  };

  return (
    <div className="w-full">
      <div className="border-b border-gray-200 flex gap-2 overflow-x-auto">
        {tabs.map((tab, index) => (
          <button
            key={index}
            onClick={() => handleTabChange(index)}
            className={`
              px-4 py-3 font-medium text-sm whitespace-nowrap flex items-center gap-2 transition-colors
              border-b-2 -mb-[2px]
              ${activeTab === index
                ? 'border-indigo-500 text-indigo-600'
                : 'border-transparent text-gray-600 hover:text-gray-900'
              }
            `}
          >
            {tab.icon}
            {tab.label}
          </button>
        ))}
      </div>
      <div className="mt-4">
        {tabs[activeTab].content}
      </div>
    </div>
  );
};
