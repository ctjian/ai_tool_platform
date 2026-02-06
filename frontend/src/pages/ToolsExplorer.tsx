import { useEffect, useState, useCallback } from 'react';
import { useAppStore } from '../store/app';
import { Input, Card, CardContent, Loading } from '../components/ui';
import { ToolDetailModal } from '../components/ToolDetailModal';
import apiClient from '../api/client';
import { Eye } from 'lucide-react';

interface Tool {
  id: string;
  name: string;
  category_id: string;
  icon: string;
  description: string;
  system_prompt: string;
}

interface Category {
  id: string;
  name: string;
  icon: string;
}

export const ToolsExplorer = () => {
  const [tools, setTools] = useState<Tool[]>([]);
  const [categories, setCategories] = useState<Category[]>([]);
  const [searchQuery, setSearchQuery] = useState('');
  const [selectedCategory, setSelectedCategory] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [selectedTool, setSelectedTool] = useState<Tool | null>(null);
  const { setCurrentTool, setConversations } = useAppStore();

  useEffect(() => {
    loadData();
  }, []);

  const loadData = async () => {
    try {
      const [toolsRes, categoriesRes] = await Promise.all([
        apiClient.getTools(),
        apiClient.getCategories(),
      ]);
      setTools(toolsRes.data.tools || toolsRes.data);
      setCategories(categoriesRes.data.categories || categoriesRes.data);
      setLoading(false);
    } catch (error) {
      console.error('Failed to load data:', error);
      setLoading(false);
    }
  };

  // 防抖搜索
  const debouncedSearch = useCallback(
    (() => {
      let timeout: ReturnType<typeof setTimeout>;
      return (query: string) => {
        clearTimeout(timeout);
        timeout = setTimeout(() => {
          setSearchQuery(query);
        }, 300);
      };
    })(),
    []
  );

  const filteredTools = tools.filter((tool) => {
    const matchesQuery =
      tool.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
      tool.description.toLowerCase().includes(searchQuery.toLowerCase());
    const matchesCategory =
      !selectedCategory || tool.category_id === selectedCategory;
    return matchesQuery && matchesCategory;
  });

  const sortedCategories = [...categories].sort((a, b) => {
    const orderA = (a as any).order ?? 0;
    const orderB = (b as any).order ?? 0;
    return orderA - orderB;
  });

  const uncategorizedTools = filteredTools.filter(
    (tool) => !categories.find((c) => c.id === tool.category_id)
  );

  const handleSelectTool = async (tool: Tool) => {
    setCurrentTool(tool as any);
    try {
      // 加载所有对话，而不只是该工具的对话
      const res = await apiClient.getConversations();
      setConversations(res.data.conversations || []);
    } catch (error) {
      console.error('Failed to load conversations:', error);
    }
  };

  const handleSavePrompt = async (prompt: string) => {
    if (!selectedTool) return;
    // 这里可以调用后端API来保存提示词
    // 暂时只在前端更新
    console.log('Saving prompt for tool:', selectedTool.id, prompt);
    // 如果有后端API，可以在这里调用
  };

  if (loading) return <Loading />;

  return (
    <div className="max-w-6xl mx-auto">
      <div className="mb-8">
        <h1 className="text-3xl font-bold text-gray-900">提示词广场</h1>
        <p className="text-gray-600 mt-2">浏览和选择提示词工具</p>
      </div>

      {/* 搜索和过滤 */}
      <div className="flex flex-col md:flex-row gap-4 mb-6">
        <div className="flex-1">
          <Input
            placeholder="搜索工具名称或描述..."
            onChange={(e) => debouncedSearch(e.target.value)}
            className="w-full"
          />
        </div>

        <select
          value={selectedCategory || ''}
          onChange={(e) => setSelectedCategory(e.target.value || null)}
          className="px-4 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-indigo-500"
        >
          <option value="">所有分类</option>
          {categories.map((cat) => (
            <option key={cat.id} value={cat.id}>
              {cat.icon} {cat.name}
            </option>
          ))}
        </select>
      </div>

      {/* 工具网格 */}
      {selectedCategory ? (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {filteredTools.length > 0 ? (
            filteredTools.map((tool) => {
              const category = categories.find((c) => c.id === tool.category_id);
              return (
                <div key={tool.id} className="relative group">
                  <Card
                    hover
                    className="cursor-pointer h-full"
                    onClick={() => handleSelectTool(tool)}
                  >
                    <CardContent className="p-4 flex flex-col h-full">
                      <div className="text-4xl mb-3">{tool.icon}</div>
                      <h3 className="font-semibold text-gray-900 mb-1">{tool.name}</h3>
                      <p className="text-xs text-gray-500 mb-2">
                        {category?.name}
                      </p>
                      <p className="text-gray-600 text-sm line-clamp-2 flex-grow">
                        {tool.description}
                      </p>
                    </CardContent>
                  </Card>
                  
                  {/* 查看提示词按钮 */}
                  <button
                    onClick={(e) => {
                      e.stopPropagation();
                      setSelectedTool(tool);
                    }}
                    className="absolute top-3 right-3 bg-white border border-gray-300 text-gray-700 p-2 rounded-lg transition shadow-sm hover:bg-gray-100 active:bg-gray-200"
                    title="查看和编辑提示词"
                  >
                    <Eye size={18} />
                  </button>
                </div>
              );
            })
          ) : (
            <div className="col-span-full text-center py-12">
              <p className="text-gray-500">未找到匹配的工具</p>
            </div>
          )}
        </div>
      ) : (
        <div className="space-y-8">
          {sortedCategories.map((category) => {
            const categoryTools = filteredTools.filter(
              (tool) => tool.category_id === category.id
            );
            if (categoryTools.length === 0) return null;
            return (
              <div key={category.id}>
                <div className="flex items-center gap-2 mb-4">
                  <span className="text-xl">{category.icon}</span>
                  <h2 className="text-lg font-semibold text-gray-900">{category.name}</h2>
                </div>
                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                  {categoryTools.map((tool) => (
                    <div key={tool.id} className="relative group">
                      <Card
                        hover
                        className="cursor-pointer h-full"
                        onClick={() => handleSelectTool(tool)}
                      >
                        <CardContent className="p-4 flex flex-col h-full">
                          <div className="text-4xl mb-3">{tool.icon}</div>
                          <h3 className="font-semibold text-gray-900 mb-1">{tool.name}</h3>
                          <p className="text-gray-600 text-sm line-clamp-2 flex-grow">
                            {tool.description}
                          </p>
                        </CardContent>
                      </Card>

                      {/* 查看提示词按钮 */}
                      <button
                        onClick={(e) => {
                          e.stopPropagation();
                          setSelectedTool(tool);
                        }}
                        className="absolute top-3 right-3 bg-white border border-gray-300 text-gray-700 p-2 rounded-lg transition shadow-sm hover:bg-gray-100 active:bg-gray-200"
                        title="查看和编辑提示词"
                      >
                        <Eye size={18} />
                      </button>
                    </div>
                  ))}
                </div>
              </div>
            );
          })}

          {uncategorizedTools.length > 0 && (
            <div>
              <div className="flex items-center gap-2 mb-4">
                <span className="text-xl">📁</span>
                <h2 className="text-lg font-semibold text-gray-900">未分类</h2>
              </div>
              <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                {uncategorizedTools.map((tool) => (
                  <div key={tool.id} className="relative group">
                    <Card
                      hover
                      className="cursor-pointer h-full"
                      onClick={() => handleSelectTool(tool)}
                    >
                      <CardContent className="p-4 flex flex-col h-full">
                        <div className="text-4xl mb-3">{tool.icon}</div>
                        <h3 className="font-semibold text-gray-900 mb-1">{tool.name}</h3>
                        <p className="text-gray-600 text-sm line-clamp-2 flex-grow">
                          {tool.description}
                        </p>
                      </CardContent>
                    </Card>

                    {/* 查看提示词按钮 */}
                    <button
                      onClick={(e) => {
                        e.stopPropagation();
                        setSelectedTool(tool);
                      }}
                      className="absolute top-3 right-3 bg-white border border-gray-300 text-gray-700 p-2 rounded-lg transition shadow-sm hover:bg-gray-100 active:bg-gray-200"
                      title="查看和编辑提示词"
                    >
                      <Eye size={18} />
                    </button>
                  </div>
                ))}
              </div>
            </div>
          )}

          {filteredTools.length === 0 && (
            <div className="text-center py-12">
              <p className="text-gray-500">未找到匹配的工具</p>
            </div>
          )}
        </div>
      )}

      {/* 工具详情模态窗口 */}
      <ToolDetailModal
        tool={selectedTool}
        onClose={() => setSelectedTool(null)}
        onSave={handleSavePrompt}
      />
    </div>
  );
};
