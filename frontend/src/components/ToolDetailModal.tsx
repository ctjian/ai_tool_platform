import { useState, useEffect } from 'react'
import { X, Copy, Check } from 'lucide-react'
import { addToast } from './ui'

interface Tool {
  id: string
  name: string
  icon: string
  description: string
  system_prompt: string
}

interface ToolDetailModalProps {
  tool: Tool | null
  onClose: () => void
  onSave?: (prompt: string) => Promise<void>
}

export const ToolDetailModal = ({ tool, onClose, onSave }: ToolDetailModalProps) => {
  const [prompt, setPrompt] = useState('')
  const [isEditing, setIsEditing] = useState(false)
  const [isSaving, setIsSaving] = useState(false)
  const [copied, setCopied] = useState(false)

  // 当tool改变时，更新prompt
  useEffect(() => {
    if (tool) {
      setPrompt(tool.system_prompt || '')
      setIsEditing(false)
    }
  }, [tool?.id])

  if (!tool) return null

  const handleCopy = () => {
    navigator.clipboard.writeText(prompt)
    setCopied(true)
    addToast('已复制到剪贴板', 'success')
    setTimeout(() => setCopied(false), 2000)
  }

  const handleSave = async () => {
    if (!onSave) return
    setIsSaving(true)
    try {
      await onSave(prompt)
      setIsEditing(false)
      addToast('保存成功', 'success')
    } catch (error) {
      console.error('Failed to save prompt:', error)
      addToast('保存失败', 'error')
    } finally {
      setIsSaving(false)
    }
  }

  const handleCancel = () => {
    setPrompt(tool?.system_prompt || '')
    setIsEditing(false)
  }

  return (
    <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50 p-4">
      <div className="bg-white rounded-lg shadow-lg max-w-2xl w-full max-h-[90vh] flex flex-col">
        {/* 头部 */}
        <div className="border-b border-gray-200 p-6 flex items-center justify-between flex-shrink-0">
          <div className="flex items-center gap-3">
            <span className="text-4xl">{tool.icon}</span>
            <div>
              <h2 className="text-xl font-bold text-gray-900">{tool.name}</h2>
              <p className="text-sm text-gray-600">{tool.description}</p>
            </div>
          </div>
          <button
            onClick={onClose}
            className="text-gray-500 hover:text-gray-700 transition"
          >
            <X size={24} />
          </button>
        </div>

        {/* 内容 */}
        <div className="flex-1 overflow-y-auto p-6">
          <div className="mb-4">
            <label className="block text-sm font-semibold text-gray-900 mb-2">
              系统提示词 (System Prompt)
            </label>
            <textarea
              value={prompt}
              onChange={(e) => setPrompt(e.target.value)}
              disabled={!isEditing}
              className="w-full h-64 p-4 border border-gray-300 rounded-lg font-mono text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500 disabled:bg-gray-50 disabled:text-gray-700 resize-none"
              placeholder="输入系统提示词..."
            />
          </div>

          <div className="text-xs text-gray-500">
            <p className="mb-2">💡 提示：系统提示词会在每次与该工具交互时发送给AI模型，用于指导AI的行为和回复风格。</p>
          </div>
        </div>

        {/* 页脚 */}
        <div className="border-t border-gray-200 p-6 flex items-center justify-end gap-3 flex-shrink-0">
          <button
            onClick={handleCopy}
            disabled={isSaving}
            className="flex items-center gap-2 px-4 py-2 text-gray-700 hover:bg-gray-100 rounded-lg transition disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {copied ? <Check size={18} /> : <Copy size={18} />}
            {copied ? '已复制' : '复制'}
          </button>

          {!isEditing ? (
            <>
              <button
                onClick={onClose}
                className="px-4 py-2 text-gray-700 hover:bg-gray-100 rounded-lg transition"
              >
                关闭
              </button>
              <button
                onClick={() => setIsEditing(true)}
                className="px-4 py-2 bg-indigo-600 text-white hover:bg-indigo-700 rounded-lg transition"
              >
                编辑
              </button>
            </>
          ) : (
            <>
              <button
                onClick={handleCancel}
                disabled={isSaving}
                className="px-4 py-2 text-gray-700 hover:bg-gray-100 rounded-lg transition disabled:opacity-50 disabled:cursor-not-allowed"
              >
                取消
              </button>
              <button
                onClick={handleSave}
                disabled={isSaving}
                className="px-4 py-2 bg-indigo-600 text-white hover:bg-indigo-700 rounded-lg transition disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {isSaving ? '保存中...' : '保存'}
              </button>
            </>
          )}
        </div>
      </div>
    </div>
  )
}
