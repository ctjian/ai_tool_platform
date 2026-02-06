import { useState } from 'react';
import { Tabs } from '../../components/ui';
import { APIConfigPage } from './APIConfigPage';
import { ToolManagementPage } from './ToolManagementPage';
import { CategoryManagementPage } from './CategoryManagementPage';

export const SettingsPage = () => {
  const tabs = [
    {
      label: 'API配置',
      icon: '⚙️',
      content: <APIConfigPage />,
    },
    {
      label: '工具管理',
      icon: '🛠️',
      content: <ToolManagementPage />,
    },
    {
      label: '分类管理',
      icon: '📂',
      content: <CategoryManagementPage />,
    },
  ];

  return (
    <div className="max-w-6xl mx-auto">
      <div className="mb-8">
        <h1 className="text-3xl font-bold text-gray-900">设置</h1>
        <p className="text-gray-600 mt-2">管理API配置、工具和分类</p>
      </div>
      <Tabs tabs={tabs} />
    </div>
  );
};
