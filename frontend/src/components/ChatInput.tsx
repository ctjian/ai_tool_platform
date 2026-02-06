import React, { useEffect, useRef, useState } from 'react'
import { Send, Loader, Plus, X, Image as ImageIcon } from 'lucide-react'

interface ImageFile {
  file: File
  preview: string
  id: string
}

interface ChatInputProps {
  value: string
  onChange: (value: string) => void
  onSend: () => void
  disabled?: boolean
  loading?: boolean
  images?: ImageFile[]
  onImagesChange?: (images: ImageFile[]) => void
}

function ChatInput({
  value,
  onChange,
  onSend,
  disabled = false,
  loading = false,
  images = [],
  onImagesChange,
}: ChatInputProps) {
  const containerShadowClass = loading ? 'shadow-none' : 'shadow-sm'
  const fileInputRef = useRef<HTMLInputElement>(null)
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const [previewImage, setPreviewImage] = useState<string | null>(null)

  const adjustTextareaHeight = () => {
    if (!textareaRef.current) return
    textareaRef.current.style.height = 'auto'
    const newHeight = Math.min(textareaRef.current.scrollHeight, 200)
    textareaRef.current.style.height = `${newHeight}px`
  }

  useEffect(() => {
    adjustTextareaHeight()
  }, [value])

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey && !disabled) {
      e.preventDefault()
      onSend()
    }
  }

  const handlePaste = async (e: React.ClipboardEvent) => {
    const items = e.clipboardData?.items
    if (!items) return

    for (let i = 0; i < items.length; i++) {
      const item = items[i]
      if (item.type.indexOf('image') !== -1) {
        e.preventDefault()
        const file = item.getAsFile()
        if (file) {
          await addImageFile(file)
        }
      }
    }
  }

  const handleFileSelect = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files
    if (!files) return

    for (let i = 0; i < files.length; i++) {
      if (images.length >= 5) {
        alert('最多只能上传5张图片')
        break
      }
      await addImageFile(files[i])
    }

    // 清空 input 值，允许重复选择同一文件
    if (fileInputRef.current) {
      fileInputRef.current.value = ''
    }
  }

  const addImageFile = async (file: File) => {
    if (images.length >= 5) {
      alert('最多只能上传5张图片')
      return
    }

    // 检查文件类型
    if (!file.type.startsWith('image/')) {
      alert('只能上传图片文件')
      return
    }

    // 检查文件大小 (最大 10MB)
    if (file.size > 10 * 1024 * 1024) {
      alert('图片大小不能超过 10MB')
      return
    }

    const preview = URL.createObjectURL(file)
    const newImage: ImageFile = {
      file,
      preview,
      id: Date.now().toString() + Math.random()
    }

    onImagesChange?.([...images, newImage])
  }

  const removeImage = (id: string) => {
    const image = images.find(img => img.id === id)
    if (image) {
      URL.revokeObjectURL(image.preview)
    }
    onImagesChange?.(images.filter(img => img.id !== id))
  }

  return (
    <div className="relative">
      <div className={`w-full border border-gray-300 bg-white rounded-2xl ${containerShadowClass}`}>
        {/* 图片预览区域（内嵌输入框） */}
        {images.length > 0 && (
          <div className="flex gap-2 p-3 pb-0 flex-wrap">
            {images.map((img) => (
              <div key={img.id} className="relative group">
                <img
                  src={img.preview}
                  alt="预览"
                  className="w-20 h-20 object-cover rounded-lg border border-gray-200 cursor-pointer"
                  onClick={() => setPreviewImage(img.preview)}
                />
                <button
                  onClick={() => removeImage(img.id)}
                  className="absolute -top-2 -right-2 bg-black text-white rounded-full w-5 h-5 flex items-center justify-center hover:bg-gray-800 transition"
                >
                  <X size={14} />
                </button>
              </div>
            ))}
          </div>
        )}

        {/* 输入区域 */}
        <div className="relative flex items-center gap-2 p-3">
          {/* 添加图片按钮 */}
          <button
            type="button"
            onClick={() => fileInputRef.current?.click()}
            disabled={disabled || images.length >= 5}
            className="flex-shrink-0 w-10 h-10 flex items-center justify-center hover:opacity-60 transition disabled:opacity-50 disabled:cursor-not-allowed"
            title="上传图片"
          >
            <Plus size={20} className="text-gray-600" />
          </button>

          {/* 隐藏的文件输入 */}
          <input
            ref={fileInputRef}
            type="file"
            accept="image/*"
            multiple
            onChange={handleFileSelect}
            className="hidden"
          />

          {/* 文本输入框 */}
          <div className="flex-1 relative">
            <textarea
              ref={textareaRef}
              value={value}
              onChange={(e) => {
                onChange(e.target.value)
                adjustTextareaHeight()
              }}
              onKeyDown={handleKeyDown}
              onPaste={handlePaste}
              placeholder="有问题，尽管问"
              disabled={disabled || loading}
              className={`w-full pl-2 pr-12 py-2 bg-transparent text-gray-900 resize-none focus:outline-none disabled:bg-transparent disabled:cursor-not-allowed text-base placeholder-gray-500`}
              rows={1}
              style={{ minHeight: '40px', maxHeight: '200px' }}
            />
            <button
              onClick={onSend}
              disabled={disabled || loading || (!value.trim() && images.length === 0)}
              className="absolute right-0 top-1/2 -translate-y-1/2 flex items-center justify-center bg-gray-800 text-white w-10 h-10 rounded-full hover:bg-gray-900 transition disabled:opacity-30 disabled:cursor-not-allowed"
            >
              {loading ? (
                <Loader size={18} className="animate-spin" />
              ) : (
                <Send size={18} />
              )}
            </button>
          </div>
        </div>
      </div>

      {/* 图片放大预览 */}
      {previewImage && (
        <div
          className="fixed inset-0 bg-black/70 z-50 flex items-center justify-center p-6"
          onClick={() => setPreviewImage(null)}
        >
          <img
            src={previewImage}
            alt="放大预览"
            className="max-h-full max-w-full rounded-lg shadow-2xl"
            onClick={(e) => e.stopPropagation()}
          />
        </div>
      )}
    </div>
  )
}

export default ChatInput
