// Review note:
// - 当消息处于 __waiting__ 阶段时，读取 message.extra.status_steps 渲染论文检索进度列表。
// - 每个步骤显示运行/完成/失败状态，完成时展示耗时（秒）。
import React, { forwardRef, useMemo, useState } from 'react'
import { Message } from '../types/api'
import { useAppStore } from '../store/app'
import ReactMarkdown from 'react-markdown'
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter'
import a11yOneLight from 'react-syntax-highlighter/dist/esm/styles/prism/a11y-one-light'
import remarkGfm from 'remark-gfm'
import remarkMath from 'remark-math'
import rehypeKatex from 'rehype-katex'
import { Copy, Check, RotateCcw, ChevronLeft, ChevronRight, Loader2, AlertCircle } from 'lucide-react'
import { addToast } from './ui'
import 'katex/dist/katex.min.css'

interface MessageListProps {
  messages: Message[]
  onRetry?: (assistantMessageId: string) => void
}

const MessageListInner = forwardRef<HTMLDivElement, MessageListProps>(
  ({ messages, onRetry }, ref) => {
    const [copiedId, setCopiedId] = useState<string | null>(null)
    const [previewImage, setPreviewImage] = useState<string | null>(null)
    const { versionIndices, setVersionIndices, setMessages } = useAppStore()

    const handleCopy = async (content: string, msgId: string) => {
      try {
        if (navigator.clipboard && window.isSecureContext) {
          await navigator.clipboard.writeText(content)
        } else {
          // fallback for non-secure context
          const textarea = document.createElement('textarea')
          textarea.value = content
          textarea.setAttribute('readonly', '')
          textarea.style.position = 'fixed'
          textarea.style.top = '-9999px'
          document.body.appendChild(textarea)
          textarea.select()
          document.execCommand('copy')
          document.body.removeChild(textarea)
        }
        setCopiedId(msgId)
        addToast('已复制到剪贴板', 'success')
        setTimeout(() => setCopiedId(null), 2000)
      } catch (e) {
        addToast('复制失败，请手动复制', 'error')
      }
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
    const parseRetryVersions = (retryVersions: Message['retry_versions']): string[] => {
      if (!retryVersions) return []
      try {
        // retry_versions 可能是JSON字符串或数组
        if (typeof retryVersions === 'string') {
          return JSON.parse(retryVersions)
        }
        return retryVersions
      } catch {
        return []
      }
    }

    const getMessageContent = (msg: Message): string => {
      if (msg.role === 'assistant' && msg.retry_versions) {
        const versions = parseRetryVersions(msg.retry_versions)
        if (versions.length === 0) return msg.content
        
        const selectedVersion = versionIndices[msg.id] ?? 0
        if (selectedVersion === 0) {
          return msg.content
        } else if (selectedVersion > 0 && selectedVersion <= versions.length) {
          return versions[selectedVersion - 1]
        }
      }
      return msg.content
    }

    const extractCostMeta = (content: string, rawCost: any): { text: string; cost: any | null } => {
      let parsedCost = rawCost
      if (typeof rawCost === 'string') {
        try {
          parsedCost = JSON.parse(rawCost)
        } catch {
          parsedCost = null
        }
      }
      return { text: content, cost: parsedCost || null }
    }

    const formatCost = (value: number): string => {
      if (!Number.isFinite(value)) return '0'
      if (value === 0) return '0'
      if (value < 0.0001) return value.toExponential(2)
      return value.toFixed(6).replace(/0+$/, '').replace(/\.$/, '')
    }

    // 获取版本总数
    const getTotalVersions = (msg: Message): number => {
      if (msg.role === 'assistant' && msg.retry_versions) {
        const versions = parseRetryVersions(msg.retry_versions)
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
          <div className="my-3 rounded-2xl bg-gray-50 border border-gray-200 overflow-hidden">
            <div className="flex items-center justify-between px-4 py-2 text-xs text-gray-500">
              <span>{match[1]}</span>
              <button
                onClick={() => handleCopy(String(children).replace(/\n$/, ''), `code-${Date.now()}`)}
                className="flex items-center gap-1 text-gray-500 hover:text-gray-700"
              >
                <Copy size={14} />
                复制代码
              </button>
            </div>
            <div className="px-4 pb-4">
              <SyntaxHighlighter
                style={a11yOneLight}
                language={match[1]}
                PreTag="div"
                codeTagProps={{
                  style: {
                    background: 'transparent',
                    whiteSpace: 'pre-wrap',
                    wordBreak: 'break-word',
                  },
                }}
                wrapLongLines
                customStyle={{
                  background: 'transparent',
                  margin: 0,
                  padding: 0,
                  whiteSpace: 'pre-wrap',
                  wordBreak: 'break-word',
                  overflowX: 'visible',
                }}
                {...props}
              >
                {String(children).replace(/\n$/, '')}
              </SyntaxHighlighter>
            </div>
          </div>
        ) : (
          <code
            className="bg-gray-100 px-1.5 py-0.5 rounded text-red-600 font-mono text-sm"
            {...props}
          >
            {children}
          </code>
        )
      },
      table: ({ children }: any) => (
        <div className="my-3 overflow-x-auto">
          <table className="min-w-full border border-gray-200 rounded-lg overflow-hidden text-sm">
            {children}
          </table>
        </div>
      ),
      thead: ({ children }: any) => (
        <thead className="bg-gray-50 text-gray-700">{children}</thead>
      ),
      tbody: ({ children }: any) => (
        <tbody className="divide-y divide-gray-200">{children}</tbody>
      ),
      tr: ({ children }: any) => (
        <tr className="hover:bg-gray-50">{children}</tr>
      ),
      th: ({ children }: any) => (
        <th className="text-left font-semibold px-4 py-2 border-b border-gray-200">{children}</th>
      ),
      td: ({ children }: any) => (
        <td className="px-4 py-2 border-b border-gray-200 text-gray-800">{children}</td>
      ),
    }

    const visibleMessages = useMemo(
      () => messages.filter((msg) => msg.role !== 'system'),
      [messages]
    )

    return (
      <div ref={ref} className="h-full min-h-0 overflow-y-auto overscroll-contain px-6 py-4 bg-white">
        <div className="max-w-3xl mx-auto space-y-6">
            {visibleMessages.map((msg) => {
              const totalVersions = getTotalVersions(msg)
              const currentVersionIndex = versionIndices[msg.id] ?? 0
              const displayVersionIndex = totalVersions > 0
                ? (currentVersionIndex === 0 ? totalVersions : currentVersionIndex)
                : 0
              const rawContent = getMessageContent(msg)
              const { text: displayContent, cost } = extractCostMeta(rawContent, msg.cost_meta)
              const isWaiting = msg.role === 'assistant' && displayContent === '__waiting__'
              const statusSteps = Array.isArray((msg as any).extra?.status_steps)
                ? [...((msg as any).extra.status_steps as any[])].sort((a, b) => {
                    const ao = Number(a?.order ?? 0)
                    const bo = Number(b?.order ?? 0)
                    return ao - bo
                  })
                : []
              const hasArxivStatus = statusSteps.some((step: any) => {
                const key = String(step?.key || '')
                return [
                  'arxiv_detected',
                  'download_pdf',
                  'parse_source',
                  'parse_pdf',
                  'chunk_paper',
                  'paper_ready',
                  'embed_chunks',
                  'retrieve_chunks',
                  'retrieval_ready',
                ].includes(key)
              })
              const hasThinking = msg.role === 'assistant' && (msg.thinking && msg.thinking.trim().length > 0)
              const showThinking = msg.role === 'assistant' && (hasThinking || isWaiting)
              const thinkingCollapsed = msg.thinking_collapsed ?? true
              const thinkingDone = msg.thinking_done ?? !isWaiting
              const thinkingLabel = thinkingDone ? '思考完成' : '正在思考'
              
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
                    {/* 文本内容（原始文本，不渲染） */}
                    <div className="text-gray-900 max-h-64 overflow-y-auto pr-1 whitespace-pre-wrap break-words">
                      {msg.content}
                    </div>
                    </div>
                  </div>
                ) : (
                    <div className="flex justify-start">
                    <div className="max-w-full group relative">
                      <div className="text-gray-800">
                        {showThinking && (
                          <details
                            className="mt-2 text-xs text-gray-500"
                            open={!thinkingCollapsed}
                            onToggle={(e) => {
                              const open = (e.currentTarget as HTMLDetailsElement).open
                              setMessages((msgs) =>
                                msgs.map((m) =>
                                  m.id === msg.id
                                    ? { ...m, thinking_collapsed: !open }
                                    : m
                                )
                              )
                            }}
                          >
                            <summary className="thinking-summary cursor-pointer select-none flex items-center gap-1">
                              <span className="thinking-text">{thinkingLabel}</span>
                              <span
                                className={`thinking-caret ${thinkingDone ? '' : 'thinking-caret-animate'} ${
                                  thinkingCollapsed ? '' : 'rotate-90'
                                }`}
                              >
                                ›
                              </span>
                            </summary>
                            {hasThinking && (
                              <div className="mt-2 rounded-md border-l-4 border-gray-200 bg-gray-50 px-3 py-2 text-gray-700">
                                <ReactMarkdown
                                  remarkPlugins={[remarkGfm, remarkMath]}
                                  rehypePlugins={[rehypeKatex]}
                                  components={markdownComponents}
                                >
                                  {convertLatexDelimiters(msg.thinking || '')}
                                </ReactMarkdown>
                              </div>
                            )}
                          </details>
                        )}
                        {!isWaiting && (
                          <ReactMarkdown
                            remarkPlugins={[remarkGfm, remarkMath]}
                            rehypePlugins={[rehypeKatex]}
                            components={markdownComponents}
                          >
                            {convertLatexDelimiters(displayContent)}
                          </ReactMarkdown>
                        )}
                        {isWaiting && (
                          <div className="mt-2 rounded-2xl border border-gray-200 bg-white px-4 py-3 text-sm text-gray-700 shadow-sm">
                            <div className="flex items-center gap-2 text-gray-800 font-medium">
                              <Loader2 size={15} className="animate-spin" />
                              <span>{hasArxivStatus ? '论文检索处理中' : '正在生成回答'}</span>
                            </div>
                            {hasArxivStatus && statusSteps.length > 0 && (
                              <div className="mt-3 space-y-1.5">
                                {statusSteps.map((step: any, idx: number) => {
                                  const status = String(step?.status || 'running')
                                  const isDone = status === 'done'
                                  const isError = status === 'error'
                                  const elapsedMs = Number(step?.elapsed_ms)
                                  const elapsedLabel = Number.isFinite(elapsedMs) && isDone
                                    ? `${Math.max(0, elapsedMs / 1000).toFixed(1)}s`
                                    : ''
                                  return (
                                    <div
                                      key={step?.step_id || `${idx}`}
                                      className="flex items-start justify-between gap-3 rounded-lg px-2 py-1.5 hover:bg-gray-50"
                                    >
                                      <div className="flex items-start gap-2 min-w-0">
                                        <span className="mt-0.5">
                                          {isDone ? (
                                            <Check size={14} className="text-green-600" />
                                          ) : isError ? (
                                            <AlertCircle size={14} className="text-red-500" />
                                          ) : (
                                            <Loader2 size={14} className="animate-spin text-gray-500" />
                                          )}
                                        </span>
                                        <span className={`text-xs leading-5 ${isError ? 'text-red-600' : 'text-gray-700'}`}>
                                          {String(step?.message || '')}
                                          {isDone ? ' √' : ''}
                                        </span>
                                      </div>
                                      {elapsedLabel && (
                                        <span className="shrink-0 rounded-full bg-gray-100 px-2 py-0.5 text-[11px] text-gray-500">
                                          {elapsedLabel}
                                        </span>
                                      )}
                                    </div>
                                  )
                                })}
                              </div>
                            )}
                          </div>
                        )}
                      </div>
                      {cost && (
                        <div className="mt-2 text-xs text-gray-500">
                          费用 {cost.currency === 'USD' ? '$' : ''}{formatCost(cost.total_cost)}{' '}
                          (prompt {cost.prompt_tokens}, completion {cost.completion_tokens}, total {cost.total_tokens})
                        </div>
                      )}
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
                        </button>
                        <button
                          onClick={() => onRetry?.(msg.id)}
                          className="flex items-center gap-1 px-2 py-1 hover:bg-gray-100 rounded"
                          title="重试"
                        >
                          <RotateCcw size={14} className="text-gray-600" />
                        </button>
                      </div>
                    </div>
                  </div>
                )}
              </div>
            )
            })}
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
)

const MessageList = React.memo(MessageListInner)
MessageList.displayName = 'MessageList'

export default MessageList
