import React, { useEffect, useRef, useState } from 'react'
import { Send, Plus, X, Square, FileText } from 'lucide-react'

interface ImageFile {
  file: File
  preview: string
  id: string
}

interface PdfFile {
  file: File
  id: string
  name: string
  size: number
}

interface ChatInputProps {
  value: string
  onChange: (value: string) => void
  onSend: () => void
  onStop?: () => void
  disabled?: boolean
  loading?: boolean
  images?: ImageFile[]
  onImagesChange?: (images: ImageFile[]) => void
  pdfFiles?: PdfFile[]
  onPdfFilesChange?: (pdfFiles: PdfFile[]) => void
}

function ChatInput({
  value,
  onChange,
  onSend,
  onStop,
  disabled = false,
  loading = false,
  images = [],
  onImagesChange,
  pdfFiles = [],
  onPdfFilesChange,
}: ChatInputProps) {
  const containerShadowClass = loading ? 'shadow-none' : 'shadow-sm'
  const fileInputRef = useRef<HTMLInputElement>(null)
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const [previewImage, setPreviewImage] = useState<string | null>(null)
  const prevImagesRef = useRef<ImageFile[]>([])

  const adjustTextareaHeight = () => {
    if (!textareaRef.current) return
    textareaRef.current.style.height = 'auto'
    const newHeight = Math.min(textareaRef.current.scrollHeight, 200)
    textareaRef.current.style.height = `${newHeight}px`
  }

  useEffect(() => {
    adjustTextareaHeight()
  }, [value])

  // 统一回收已移除的预览 URL，避免 blob 404 报错
  useEffect(() => {
    const prevImages = prevImagesRef.current
    const currentIds = new Set(images.map(img => img.id))
    for (const img of prevImages) {
      if (!currentIds.has(img.id)) {
        URL.revokeObjectURL(img.preview)
        if (previewImage === img.preview) {
          setPreviewImage(null)
        }
      }
    }
    prevImagesRef.current = images
  }, [images, previewImage])

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey && !disabled) {
      e.preventDefault()
      onSend()
    }
  }

  const handlePaste = (e: React.ClipboardEvent) => {
    const items = e.clipboardData?.items
    if (!items) return
    let nextImages = [...images]
    let nextPdfFiles = [...pdfFiles]
    let hasFilePaste = false
    let changed = false
    let pdfChanged = false

    for (let i = 0; i < items.length; i++) {
      const item = items[i]
      if (item.kind !== 'file') continue
      const file = item.getAsFile()
      if (!file) continue
      const itemType = (item.type || '').toLowerCase()
      const isImage = file.type.startsWith('image/') || itemType.startsWith('image/')
      const isPdf = isPdfFile(file) || itemType.includes('pdf')
      if (!isImage && !isPdf) continue
      hasFilePaste = true

      if (isImage) {
        if (nextImages.length >= 5) {
          alert('最多只能上传5张图片')
          continue
        }
        if (file.size > 10 * 1024 * 1024) {
          alert('图片大小不能超过 10MB')
          continue
        }
        const preview = URL.createObjectURL(file)
        nextImages.push({
          file,
          preview,
          id: Date.now().toString() + Math.random()
        })
        changed = true
        continue
      }

      if (nextPdfFiles.length >= 5) {
        alert('单次最多上传5个PDF')
        continue
      }
      if (file.size > 20 * 1024 * 1024) {
        alert('PDF大小不能超过20MB')
        continue
      }
      nextPdfFiles.push({
        file,
        id: Date.now().toString() + Math.random(),
        name: file.name || 'uploaded.pdf',
        size: file.size,
      })
      pdfChanged = true
    }

    if (hasFilePaste) {
      e.preventDefault()
    }

    if (changed) {
      onImagesChange?.(nextImages)
    }
    if (pdfChanged) {
      onPdfFilesChange?.(nextPdfFiles)
    }
  }

  const handleFileSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files
    if (!files) return
    let nextImages = [...images]
    let nextPdfFiles = [...pdfFiles]
    let imageChanged = false
    let pdfChanged = false

    for (let i = 0; i < files.length; i++) {
      const file = files[i]
      if (file.type.startsWith('image/')) {
        if (nextImages.length >= 5) {
          alert('最多只能上传5张图片')
          continue
        }
        if (file.size > 10 * 1024 * 1024) {
          alert('图片大小不能超过 10MB')
          continue
        }
        const preview = URL.createObjectURL(file)
        nextImages.push({
          file,
          preview,
          id: Date.now().toString() + Math.random()
        })
        imageChanged = true
      } else if (isPdfFile(file)) {
        if (nextPdfFiles.length >= 5) {
          alert('单次最多上传5个PDF')
          continue
        }
        if (file.size > 20 * 1024 * 1024) {
          alert('PDF大小不能超过20MB')
          continue
        }
        nextPdfFiles.push({
          file,
          id: Date.now().toString() + Math.random(),
          name: file.name || 'uploaded.pdf',
          size: file.size,
        })
        pdfChanged = true
      }
    }

    if (imageChanged) {
      onImagesChange?.(nextImages)
    }
    if (pdfChanged) {
      onPdfFilesChange?.(nextPdfFiles)
    }

    // 清空 input 值，允许重复选择同一文件
    if (fileInputRef.current) {
      fileInputRef.current.value = ''
    }
  }

  const isPdfFile = (file: File) => {
    const lower = (file.name || '').toLowerCase()
    return file.type === 'application/pdf' || lower.endsWith('.pdf')
  }

  const removeImage = (id: string) => {
    onImagesChange?.(images.filter(img => img.id !== id))
  }

  const removePdf = (id: string) => {
    onPdfFilesChange?.(pdfFiles.filter((item) => item.id !== id))
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
        {pdfFiles.length > 0 && (
          <div className="flex flex-wrap gap-2 p-3 pb-0">
            {pdfFiles.map((item) => (
              <div
                key={item.id}
                className="group flex items-center gap-2 rounded-lg border border-gray-200 bg-gray-50 px-2 py-1.5 max-w-full"
              >
                <FileText size={14} className="text-gray-600 shrink-0" />
                <span className="text-xs text-gray-700 truncate max-w-[220px]" title={item.name}>
                  {item.name}
                </span>
                <button
                  onClick={() => removePdf(item.id)}
                  className="text-gray-500 hover:text-gray-700"
                  title="移除PDF"
                >
                  <X size={14} />
                </button>
              </div>
            ))}
          </div>
        )}

        {/* 输入区域 */}
        <div className="relative flex items-center gap-2 p-3">
          {/* 添加附件按钮 */}
          <button
            type="button"
            onClick={() => fileInputRef.current?.click()}
            disabled={disabled}
            className="flex-shrink-0 w-10 h-10 flex items-center justify-center hover:opacity-60 transition disabled:opacity-50 disabled:cursor-not-allowed"
            title="上传图片或PDF"
          >
            <Plus size={20} className="text-gray-600" />
          </button>

          {/* 隐藏的文件输入 */}
          <input
            ref={fileInputRef}
            type="file"
            accept="image/*,.pdf,application/pdf"
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
              onClick={() => {
                if (loading && onStop) {
                  onStop()
                } else {
                  onSend()
                }
              }}
              disabled={
                !loading &&
                (disabled || (!value.trim() && images.length === 0 && pdfFiles.length === 0))
              }
              className={`absolute right-0 top-1/2 -translate-y-1/2 flex items-center justify-center w-10 h-10 rounded-full transition ${
                loading
                  ? 'bg-red-500 hover:bg-red-600 text-white'
                  : 'bg-gray-800 hover:bg-gray-900 text-white'
              } disabled:opacity-30 disabled:cursor-not-allowed`}
            >
              {loading ? <Square size={18} /> : <Send size={18} />}
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
