import React, { forwardRef, useState } from 'react'
import { Message } from '../types/api'
import { useAppStore } from '../store/app'
import ReactMarkdown from 'react-markdown'
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter'
import { dracula } from 'react-syntax-highlighter/dist/esm/styles/prism'
import remarkGfm from 'remark-gfm'
import remarkMath from 'remark-math'
import rehypeKatex from 'rehype-katex'
import { Copy, Check, RotateCcw, ChevronLeft, ChevronRight } from 'lucide-react'
import { addToast } from './ui'
import 'katex/dist/katex.min.css'

interface MessageListProps {
  messages: Message[]
  onRetry?: (assistantMessageId: string) => void
}

const MessageList = forwardRef<HTMLDivElement, MessageListProps>(
  ({ messages, onRetry }, ref) => {
    const [copiedId, setCopiedId] = useState<string | null>(null)
    const [previewImage, setPreviewImage] = useState<string | null>(null)
    const { versionIndices, setVersionIndices } = useAppStore()

    const handleCopy = (content: string, msgId: string) => {
      navigator.clipboard.writeText(content)
      setCopiedId(msgId)
      addToast('已复制到剪贴板', 'success')
      setTimeout(() => setCopiedId(null), 2000)
    }

    // 将 \(...\) 转换为 $...$ 和 \[...\] 转换为 $$...$$
    const convertLatexDelimiters = (content: string): string => {
      // 转换 \[...\] 为 $$...$$（块级）
      content = content.replace(/\\\[([\s\S]*?)\\\]/g, (_match, p1) => `$$${p1}$$`)
      // 转换 \(...\) 为 $...$ （内联）
      content = content.replace(/\\\(([\s\S]*?)\\\)/g, (_match, p1) => `$${p1}$`)
      return content
    }

    // 获取消息的显示内容（考虑版本选择）
    const getMessageContent = (msg: Message): string => {
      if (msg.role === 'assistant' && msg.retry_versions) {
        let versions: string[] = []
        try {
          // retry_versions 可能是JSON字符串或数组
          if (typeof msg.retry_versions === 'string') {
            versions = JSON.parse(msg.retry_versions)
          } else {
            versions = msg.retry_versions
          }
        } catch {
          return msg.content
        }
        
        const selectedVersion = versionIndices[msg.id] ?? 0
        if (selectedVersion === 0) {
          return msg.content
        } else if (selectedVersion > 0 && selectedVersion <= versions.length) {
          return versions[selectedVersion - 1]
        }
      }
      return msg.content
    }

    // 获取版本总数
    const getTotalVersions = (msg: Message): number => {
      if (msg.role === 'assistant' && msg.retry_versions) {
        let versions: string[] = []
        try {
          // retry_versions 可能是JSON字符串或数组
          if (typeof msg.retry_versions === 'string') {
            versions = JSON.parse(msg.retry_versions)
          } else {
            versions = msg.retry_versions
          }
        } catch {
          return 0
        }
        return versions.length > 0 ? versions.length + 1 : 0 // 当前版本 + 所有重试版本
      }
      return 0
    }

    const markdownComponents = {
      h1: ({ children }: any) => (
        <h1 className="text-2xl font-semibold mt-4 mb-2">{children}</h1>
      ),
      h2: ({ children }: any) => (
        <h2 className="text-xl font-semibold mt-4 mb-2">{children}</h2>
      ),
      h3: ({ children }: any) => (
        <h3 className="text-lg font-semibold mt-3 mb-2">{children}</h3>
      ),
      h4: ({ children }: any) => (
        <h4 className="text-base font-semibold mt-3 mb-2">{children}</h4>
      ),
      p: ({ children }: any) => (
        <p className="my-2 leading-relaxed">{children}</p>
      ),
      ul: ({ children }: any) => (
        <ul className="list-disc pl-5 my-2 space-y-1">{children}</ul>
      ),
      ol: ({ children }: any) => (
        <ol className="list-decimal pl-5 my-2 space-y-1">{children}</ol>
      ),
      li: ({ children }: any) => (
        <li className="leading-relaxed">{children}</li>
      ),
      strong: ({ children }: any) => (
        <strong className="font-semibold">{children}</strong>
      ),
      hr: () => <hr className="my-4 border-gray-200" />,
      blockquote: ({ children }: any) => (
        <blockquote className="border-l-4 border-gray-200 pl-3 my-2 text-gray-700">
          {children}
        </blockquote>
      ),
      code: ({ inline, className, children, ...props }: any) => {
        const match = /language-(\w+)/.exec(className || '')
        return !inline && match ? (
          <SyntaxHighlighter
            style={dracula}
            language={match[1]}
            PreTag="div"
            {...props}
          >
            {String(children).replace(/\n$/, '')}
          </SyntaxHighlighter>
        ) : (
          <code
            className="bg-gray-100 px-1.5 py-0.5 rounded text-red-600 font-mono text-sm"
            {...props}
          >
            {children}
          </code>
        )
      },
    }

    return (
      <div className="flex-1 overflow-y-auto px-6 py-4 bg-white">
        <div className="max-w-3xl mx-auto space-y-6">
            {messages.map((msg) => {
              const totalVersions = getTotalVersions(msg)
              const currentVersionIndex = versionIndices[msg.id] ?? 0
              const displayVersionIndex = totalVersions > 0
                ? (currentVersionIndex === 0 ? totalVersions : currentVersionIndex)
                : 0
              const displayContent = getMessageContent(msg)
              
              return (
              <div key={msg.id} className="flex flex-col">
                {msg.role === 'user' ? (
                  <div className="flex justify-end">
                    <div className="max-w-[80%] bg-gray-100 text-gray-900 rounded-2xl px-4 py-2.5">
                                            {/* 图片预览 */}
                                            {msg.images && msg.images.length > 0 && (
                                              <div className="flex gap-2 mb-2 flex-wrap">
                                                {msg.images.map((img, idx) => (
                                                  <img
                                                    key={idx}
                                                    src={img}
                                                    alt={`图片 ${idx + 1}`}
                                                    className="max-w-xs max-h-48 rounded-lg object-contain cursor-pointer"
                                                    onClick={() => setPreviewImage(img)}
                                                  />
                                                ))}
                                              </div>
                                            )}
                                            {/* 文本内容 */}
                      <div className="text-gray-900">
                        <ReactMarkdown
                          remarkPlugins={[remarkGfm, remarkMath]}
                          rehypePlugins={[rehypeKatex]}
                          components={markdownComponents}
                        >
                          {convertLatexDelimiters(msg.content)}
                        </ReactMarkdown>
                      </div>
                    </div>
                  </div>
                ) : (
                  <div className="flex justify-start">
                    <div className="max-w-full group relative">
                      <div className="text-gray-800">
                        <ReactMarkdown
                          remarkPlugins={[remarkGfm, remarkMath]}
                          rehypePlugins={[rehypeKatex]}
                          components={markdownComponents}
                        >
                          {convertLatexDelimiters(displayContent)}
                        </ReactMarkdown>
                      </div>
                      <div className="mt-2 flex items-center gap-2 text-xs text-gray-500">
                        {/* 版本选择器 */}
                        {totalVersions > 0 && (
                          <div className="flex items-center gap-1 px-2 py-1 bg-transparent rounded-none shadow-none ring-0 border-0">
                            <button
                              onClick={() => {
                                const newIndex = currentVersionIndex === 0 ? totalVersions - 1 : currentVersionIndex - 1
                                setVersionIndices({ ...versionIndices, [msg.id]: newIndex })
                              }}
                              className="hover:text-gray-800 shadow-none ring-0 focus:outline-none focus:ring-0"
                              title="上一个版本"
                            >
                              <ChevronLeft size={14} />
                            </button>
                            <span className="text-gray-600 text-xs min-w-[30px] text-center font-semibold">
                              {displayVersionIndex}/{totalVersions}
                            </span>
                            <button
                              onClick={() => {
                                const newIndex = (currentVersionIndex + 1) % totalVersions
                                setVersionIndices({ ...versionIndices, [msg.id]: newIndex })
                              }}
                              className="hover:text-gray-800 shadow-none ring-0 focus:outline-none focus:ring-0"
                              title="下一个版本"
                            >
                              <ChevronRight size={14} />
                            </button>
                          </div>
                        )}
                        <button
                          onClick={() => handleCopy(displayContent, msg.id)}
                          className="flex items-center gap-1 px-2 py-1 hover:bg-gray-100 rounded"
                          title="复制消息"
                        >
                          {copiedId === msg.id ? (
                            <Check size={14} className="text-green-600" />
                          ) : (
                            <Copy size={14} className="text-gray-600" />
                          )}
                          复制
                        </button>
                        <button
                          onClick={() => onRetry?.(msg.id)}
                          className="flex items-center gap-1 px-2 py-1 hover:bg-gray-100 rounded"
                          title="重试"
                        >
                          <RotateCcw size={14} className="text-gray-600" />
                          重试
                        </button>
                      </div>
                    </div>
                  </div>
                )}
              </div>
            )
            })}
        </div>
        <div ref={ref} />

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
)

MessageList.displayName = 'MessageList'

export default MessageList
