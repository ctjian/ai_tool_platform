import { useEffect, useState } from 'react';
import { Card, Button, Modal, ModalFooter, Input, Form, FormGroup, addToast, Loading } from '../../components/ui';
import apiClient from '../../api/client';
import type { Category } from '../../types/api';

export const CategoryManagementPage = () => {
  const [categories, setCategories] = useState<Category[]>([]);
  const [loading, setLoading] = useState(true);
  const [showModal, setShowModal] = useState(false);
  const [editingCategory, setEditingCategory] = useState<Category | null>(null);
  const [formData, setFormData] = useState({
    name: '',
    icon: '📁',
    description: '',
    order: 0,
  });

  useEffect(() => {
    loadCategories();
  }, []);

  const loadCategories = async () => {
    try {
      const response = await apiClient.getCategories();
      setCategories(response.data.categories);
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
        name: category.name,
        icon: category.icon,
        description: category.description,
        order: category.order,
      });
    } else {
      setEditingCategory(null);
      setFormData({
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

    if (!formData.name) {
      addToast('请填写分类名称', 'error');
      return;
    }

    try {
      if (editingCategory) {
        // TODO: 等待后端实现 PUT /categories/{id}
        // await apiClient.updateCategory(editingCategory.id, formData);
        addToast('暂不支持编辑分类', 'info');
      } else {
        // TODO: 等待后端实现 POST /categories
        // await apiClient.createCategory(formData);
        addToast('暂不支持添加分类', 'info');
      }
      setShowModal(false);
      loadCategories();
    } catch (error) {
      addToast('操作失败', 'error');
    }
  };

  const handleDelete = async (_categoryId: string) => {
    if (!confirm('确定要删除这个分类吗？')) return;

    try {
      // TODO: 等待后端实现 DELETE /categories/{id}
      // await apiClient.deleteCategory(categoryId);
      addToast('暂不支持删除分类', 'info');
      loadCategories();
    } catch (error) {
      addToast('删除失败', 'error');
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
                  onClick={() => handleDelete(category.id)}
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
    </div>
  );
};
