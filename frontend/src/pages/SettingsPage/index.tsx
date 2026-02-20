import { APIConfigPage } from './APIConfigPage';

export const SettingsPage = () => {
  return (
    <div className="max-w-4xl mx-auto">
      <div className="mb-8">
        <h1 className="text-3xl font-bold text-gray-900">设置</h1>
        <p className="text-gray-600 mt-2">管理 API 配置</p>
      </div>
      <APIConfigPage />
    </div>
  );
};
