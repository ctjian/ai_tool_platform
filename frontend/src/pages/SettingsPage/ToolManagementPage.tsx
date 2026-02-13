import { useEffect, useState } from 'react';
import { Button, Modal, ModalFooter, Input, Select, Form, FormGroup, addToast, Loading } from '../../components/ui';
import apiClient from '../../api/client';
import type { Category, Tool } from '../../types/api';

export const ToolManagementPage = () => {
  const [tools, setTools] = useState<Tool[]>([]);
  const [categories, setCategories] = useState<Category[]>([]);
  const [loading, setLoading] = useState(true);
  const [showModal, setShowModal] = useState(false);
  const [editingTool, setEditingTool] = useState<Tool | null>(null);
  const [formData, setFormData] = useState({
    name: '',
    category_id: '',
    icon: '🛠️',
    description: '',
    system_prompt: '',
  });

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
      addToast('加载数据失败', 'error');
      setLoading(false);
    }
  };

  const handleOpenModal = (tool?: Tool) => {
    if (tool) {
      setEditingTool(tool);
      setFormData({
        name: tool.name,
        category_id: tool.category_id,
        icon: tool.icon,
        description: tool.description,
        system_prompt: tool.system_prompt,
      });
    } else {
      setEditingTool(null);
      setFormData({
        name: '',
        category_id: '',
        icon: '🛠️',
        description: '',
        system_prompt: '',
      });
    }
    setShowModal(true);
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();

    if (!formData.name || !formData.category_id || !formData.description || !formData.system_prompt) {
      addToast('请填写所有必填字段', 'error');
      return;
    }

    try {
      if (editingTool) {
        // TODO: 等待后端实现PUT /tools/{id}
        // await apiClient.updateTool(editingTool.id, formData);
        addToast('暂不支持编辑工具', 'info');
      } else {
        // TODO: 等待后端实现POST /tools
        // await apiClient.createTool(formData);
        addToast('暂不支持添加工具', 'info');
      }
      setShowModal(false);
      loadData();
    } catch (error) {
      addToast('操作失败', 'error');
    }
  };

  const handleDelete = async (_toolId: string) => {
    if (!confirm('确定要删除这个工具吗？')) return;

    try {
      // TODO: 等待后端实现DELETE /tools/{id}
      // await apiClient.deleteTool(toolId);
      addToast('暂不支持删除工具', 'info');
      loadData();
    } catch (error) {
      addToast('删除失败', 'error');
    }
  };

  if (loading) return <Loading />;

  return (
    <div className="space-y-4">
      <div className="flex justify-between items-center">
        <h2 className="text-lg font-semibold">工具管理</h2>
        <Button variant="primary" onClick={() => handleOpenModal()}>
          + 添加工具
        </Button>
      </div>

      <div className="overflow-x-auto">
        <table className="w-full">
          <thead>
            <tr className="border-b border-gray-200">
              <th className="text-left py-3 px-4 font-semibold text-gray-900">名称</th>
              <th className="text-left py-3 px-4 font-semibold text-gray-900">分类</th>
              <th className="text-left py-3 px-4 font-semibold text-gray-900">描述</th>
              <th className="text-left py-3 px-4 font-semibold text-gray-900">操作</th>
            </tr>
          </thead>
          <tbody>
            {tools.map((tool) => (
              <tr key={tool.id} className="border-b border-gray-100 hover:bg-gray-50">
                <td className="py-3 px-4">
                  <div className="flex items-center gap-2">
                    <span className="text-xl">{tool.icon}</span>
                    {tool.name}
                  </div>
                </td>
                <td className="py-3 px-4">{categories.find((c) => c.id === tool.category_id)?.name}</td>
                <td className="py-3 px-4 text-gray-600 truncate">{tool.description}</td>
                <td className="py-3 px-4">
                  <button
                    onClick={() => handleOpenModal(tool)}
                    className="text-indigo-600 hover:text-indigo-700 mr-4"
                  >
                    编辑
                  </button>
                  <button
                    onClick={() => handleDelete(tool.id)}
                    className="text-red-600 hover:text-red-700"
                  >
                    删除
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <Modal isOpen={showModal} onClose={() => setShowModal(false)} title={editingTool ? '编辑工具' : '添加工具'}>
        <Form onSubmit={handleSubmit} className="space-y-4">
          <FormGroup>
            <Input
              label="工具名称"
              value={formData.name}
              onChange={(e) => setFormData((p) => ({ ...p, name: e.target.value }))}
              placeholder="输入工具名称"
              required
            />
          </FormGroup>

          <FormGroup>
            <Select
              label="分类"
              options={categories.map((c) => ({ value: c.id, label: c.name }))}
              value={formData.category_id}
              onChange={(v) => setFormData((p) => ({ ...p, category_id: v }))}
            />
          </FormGroup>

          <FormGroup>
            <Input
              label="图标"
              value={formData.icon}
              onChange={(e) => setFormData((p) => ({ ...p, icon: e.target.value }))}
              placeholder="🛠️"
            />
          </FormGroup>

          <FormGroup>
            <Input
              label="描述"
              value={formData.description}
              onChange={(e) => setFormData((p) => ({ ...p, description: e.target.value }))}
              placeholder="输入工具描述"
              required
            />
          </FormGroup>

          <FormGroup>
            <label className="block text-sm font-medium text-gray-700 mb-2">系统提示词</label>
            <textarea
              value={formData.system_prompt}
              onChange={(e) => setFormData((p) => ({ ...p, system_prompt: e.target.value }))}
              className="w-full px-4 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-indigo-500 h-32 resize-none"
              placeholder="输入系统提示词..."
              required
            />
          </FormGroup>

          <ModalFooter>
            <Button variant="secondary" onClick={() => setShowModal(false)}>
              取消
            </Button>
            <Button type="submit" variant="primary">
              {editingTool ? '更新' : '添加'}
            </Button>
          </ModalFooter>
        </Form>
      </Modal>
    </div>
  );
};
