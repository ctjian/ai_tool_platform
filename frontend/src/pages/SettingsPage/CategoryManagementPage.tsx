import { useEffect, useState } from 'react';
import { Card, Button, Modal, ModalFooter, Input, Form, FormGroup, addToast, Loading } from '../../components/ui';
import apiClient from '../../api/client';
import { useAppStore } from '../../store/app';
import type { Category } from '../../types/api';
import { getDeletePassword } from '../../utils/deletePassword';

export const CategoryManagementPage = () => {
  const [categories, setCategories] = useState<Category[]>([]);
  const [loading, setLoading] = useState(true);
  const [showModal, setShowModal] = useState(false);
  const [editingCategory, setEditingCategory] = useState<Category | null>(null);
  const [formData, setFormData] = useState({
    id: '',
    name: '',
    icon: '📁',
    description: '',
    order: 0,
  });
  const [deleteTarget, setDeleteTarget] = useState<Category | null>(null);
  const [deletePassword, setDeletePassword] = useState('');
  const [deleteError, setDeleteError] = useState('');
  const [deleteLoading, setDeleteLoading] = useState(false);
  const { setCategories: setStoreCategories, setTools: setStoreTools, setCurrentTool, currentTool } = useAppStore();
  const requiredDeletePassword = getDeletePassword();

  useEffect(() => {
    loadCategories();
  }, []);

  const loadCategories = async () => {
    try {
      const response = await apiClient.getCategories();
      const data = response.data.categories || response.data;
      setCategories(data);
      setStoreCategories(data);
      const toolsRes = await apiClient.getTools();
      setStoreTools(toolsRes.data.tools || toolsRes.data);
      setLoading(false);
    } catch (error) {
      console.error('Failed to load categories:', error);
      addToast('加载分类失败', 'error');
      setLoading(false);
    }
  };

  const handleOpenModal = (category?: Category) => {
    if (category) {
      setEditingCategory(category);
      setFormData({
        id: category.id,
        name: category.name,
        icon: category.icon,
        description: category.description,
        order: category.order,
      });
    } else {
      setEditingCategory(null);
      setFormData({
        id: '',
        name: '',
        icon: '📁',
        description: '',
        order: categories.length,
      });
    }
    setShowModal(true);
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();

    if (!formData.id || !formData.name) {
      addToast('请填写分类ID和名称', 'error');
      return;
    }

    try {
      if (editingCategory) {
        await apiClient.updateCategory(editingCategory.id, {
          name: formData.name,
          icon: formData.icon,
          description: formData.description,
          order: formData.order,
        });
        addToast('分类已更新', 'success');
      } else {
        await apiClient.createCategory({
          id: formData.id.trim(),
          name: formData.name,
          icon: formData.icon,
          description: formData.description,
          order: formData.order,
        });
        addToast('分类已添加', 'success');
      }
      setShowModal(false);
      loadCategories();
    } catch (error) {
      console.error('Failed to save category:', error);
      addToast('操作失败', 'error');
    }
  };

  const handleRequestDelete = (category: Category) => {
    setDeleteTarget(category);
    setDeletePassword('');
    setDeleteError('');
  };

  const handleConfirmDelete = async () => {
    if (!deleteTarget) return;
    if (deletePassword.trim() !== requiredDeletePassword) {
      setDeleteError('密码错误');
      return;
    }
    setDeleteLoading(true);
    try {
      await apiClient.deleteCategory(deleteTarget.id);
      addToast('分类已删除', 'success');
      if (currentTool?.category_id === deleteTarget.id) {
        setCurrentTool(null);
      }
      await loadCategories();
      setDeleteTarget(null);
    } catch (error) {
      console.error('Failed to delete category:', error);
      addToast('删除失败', 'error');
    } finally {
      setDeleteLoading(false);
    }
  };

  if (loading) return <Loading />;

  return (
    <div className="space-y-4">
      <div className="flex justify-between items-center">
        <h2 className="text-lg font-semibold">分类管理</h2>
        <Button variant="primary" onClick={() => handleOpenModal()}>
          + 添加分类
        </Button>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        {categories.map((category) => (
          <Card key={category.id} hover>
            <div className="flex items-start justify-between">
              <div className="flex items-start gap-3">
                <span className="text-2xl">{category.icon}</span>
                <div>
                  <h3 className="font-semibold text-gray-900">{category.name}</h3>
                  <p className="text-sm text-gray-600">{category.description}</p>
                </div>
              </div>
              <div className="flex gap-2">
                <button
                  onClick={() => handleOpenModal(category)}
                  className="text-indigo-600 hover:text-indigo-700 text-sm"
                >
                  编辑
                </button>
                <button
                  onClick={() => handleRequestDelete(category)}
                  className="text-red-600 hover:text-red-700 text-sm"
                >
                  删除
                </button>
              </div>
            </div>
          </Card>
        ))}
      </div>

      <Modal isOpen={showModal} onClose={() => setShowModal(false)} title={editingCategory ? '编辑分类' : '添加分类'}>
        <Form onSubmit={handleSubmit} className="space-y-4">
          <FormGroup>
            <Input
              label="分类ID"
              value={formData.id}
              onChange={(e) => setFormData((p) => ({ ...p, id: e.target.value }))}
              placeholder="例如 academic-writing"
              disabled={Boolean(editingCategory)}
              required
            />
          </FormGroup>

          <FormGroup>
            <Input
              label="分类名称"
              value={formData.name}
              onChange={(e) => setFormData((p) => ({ ...p, name: e.target.value }))}
              placeholder="输入分类名称"
              required
            />
          </FormGroup>

          <FormGroup>
            <Input
              label="分类图标"
              value={formData.icon}
              onChange={(e) => setFormData((p) => ({ ...p, icon: e.target.value }))}
              placeholder="📁"
            />
          </FormGroup>

          <FormGroup>
            <Input
              label="分类描述"
              value={formData.description}
              onChange={(e) => setFormData((p) => ({ ...p, description: e.target.value }))}
              placeholder="输入分类描述"
            />
          </FormGroup>

          <ModalFooter>
            <Button variant="secondary" onClick={() => setShowModal(false)}>
              取消
            </Button>
            <Button type="submit" variant="primary">
              {editingCategory ? '更新' : '添加'}
            </Button>
          </ModalFooter>
        </Form>
      </Modal>

      <Modal
        isOpen={Boolean(deleteTarget)}
        onClose={() => setDeleteTarget(null)}
        title="删除验证"
      >
        <div className="space-y-4">
          <p className="text-sm text-gray-600">
            删除分类将同时删除该分类下的工具，此操作不可恢复。
          </p>
          <Input
            label="删除密码"
            type="password"
            value={deletePassword}
            onChange={(e) => {
              setDeletePassword(e.target.value);
              if (deleteError) setDeleteError('');
            }}
            placeholder="请输入删除密码"
            error={deleteError}
          />
        </div>
        <ModalFooter>
          <Button variant="secondary" onClick={() => setDeleteTarget(null)}>
            取消
          </Button>
          <Button
            variant="primary"
            onClick={handleConfirmDelete}
            disabled={deleteLoading}
          >
            {deleteLoading ? '删除中...' : '确认删除'}
          </Button>
        </ModalFooter>
      </Modal>
    </div>
  );
};
