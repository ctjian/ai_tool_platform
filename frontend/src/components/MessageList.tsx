// Review note:
// - 聊天页改为虚拟滚动，只渲染视口附近的消息，避免长会话拖垮 DOM。
// - 单条消息组件独立 memo，流式输出时未变化的历史消息不再全量重渲染。
import React, {
  forwardRef,
  useCallback,
  useEffect,
  useImperativeHandle,
  useMemo,
  useRef,
  useState,
} from 'react'
import { Message } from '../types/api'
import { useAppStore } from '../store/app'
import {
  Copy,
  Check,
  RotateCcw,
  ChevronLeft,
  ChevronRight,
  Loader2,
  AlertCircle,
  Pencil,
  X,
  FileText,
} from 'lucide-react'
import { addToast } from './ui'
import MarkdownRenderer from './MarkdownRenderer'

interface MessageListProps {
  messages: Message[]
  onRetry?: (assistantMessageId: string) => void
  onOpenRoundPrompt?: (msg: Message) => void
  onSubmitUserEdit?: (payload: {
    userMessageId: string
    assistantMessageId: string
    content: string
  }) => Promise<void> | void
}

interface UserReplyInfo {
  completed: boolean
  assistantId: string | null
}

interface MessageRowProps {
  msg: Message
  versionIndex: number
  isLatestRetryable: boolean
  userReplyCompleted: boolean
  replyAssistantId: string | null
  isCopied: boolean
  isEditingUser: boolean
  editingContent: string
  onHeightChange: (messageId: string, height: number) => void
  onCopy: (content: string, msgId: string) => Promise<void>
  onPreviewImage: (url: string) => void
  onBeginEdit: (msg: Message, assistantId: string | null) => void
  onCancelEdit: () => void
  onEditingContentChange: (value: string) => void
  onConfirmEdit: (msg: Message, assistantId: string | null, content: string) => void
  onToggleThinking: (msgId: string, open: boolean) => void
  onSetVersionIndex: (msgId: string, nextIndex: number) => void
  onOpenRoundPrompt?: (msg: Message) => void
  onRetry?: (assistantMessageId: string) => void
}

const ESTIMATED_ITEM_HEIGHT = 220
const MIN_OVERSCAN_PX = 800

const parseRetryVersions = (retryVersions: Message['retry_versions']): string[] => {
  if (!retryVersions) return []
  try {
    if (typeof retryVersions === 'string') {
      return JSON.parse(retryVersions)
    }
    return retryVersions
  } catch {
    return []
  }
}

const getMessageContent = (msg: Message, versionIndex: number): string => {
  if (msg.role === 'assistant' && msg.retry_versions) {
    const versions = parseRetryVersions(msg.retry_versions)
    if (versions.length === 0) return msg.content
    if (versionIndex === 0) {
      return msg.content
    }
    if (versionIndex > 0 && versionIndex <= versions.length) {
      return versions[versionIndex - 1]
    }
  }
  return msg.content
}

const getTotalVersions = (msg: Message): number => {
  if (msg.role === 'assistant' && msg.retry_versions) {
    const versions = parseRetryVersions(msg.retry_versions)
    return versions.length > 0 ? versions.length + 1 : 0
  }
  return 0
}

const extractCostMeta = (content: string, rawCost: unknown): { text: string; cost: Record<string, any> | null } => {
  let parsedCost = rawCost
  if (typeof rawCost === 'string') {
    try {
      parsedCost = JSON.parse(rawCost)
    } catch {
      parsedCost = null
    }
  }
  return {
    text: content,
    cost: parsedCost && typeof parsedCost === 'object' ? (parsedCost as Record<string, any>) : null,
  }
}

const formatCost = (value: number): string => {
  if (!Number.isFinite(value)) return '0'
  if (value === 0) return '0'
  if (value < 0.0001) return value.toExponential(2)
  return value.toFixed(6).replace(/0+$/, '').replace(/\.$/, '')
}

const getStatusSteps = (msg: Message): any[] => {
  const steps = Array.isArray((msg as any).extra?.status_steps)
    ? [...((msg as any).extra.status_steps as any[])]
    : []
  steps.sort((a, b) => {
    const ao = Number(a?.order ?? 0)
    const bo = Number(b?.order ?? 0)
    return ao - bo
  })
  return steps
}

const MessageRow = React.memo(
  ({
    msg,
    versionIndex,
    isLatestRetryable,
    userReplyCompleted,
    replyAssistantId,
    isCopied,
    isEditingUser,
    editingContent,
    onHeightChange,
    onCopy,
    onPreviewImage,
    onBeginEdit,
    onCancelEdit,
    onEditingContentChange,
    onConfirmEdit,
    onToggleThinking,
    onSetVersionIndex,
    onOpenRoundPrompt,
    onRetry,
  }: MessageRowProps) => {
    const rowRef = useRef<HTMLDivElement | null>(null)

    useEffect(() => {
      const node = rowRef.current
      if (!node) return
      const measure = () => {
        onHeightChange(msg.id, node.getBoundingClientRect().height)
      }
      measure()
      const observer = new ResizeObserver(() => {
        measure()
      })
      observer.observe(node)
      return () => observer.disconnect()
    }, [msg.id, onHeightChange])

    const totalVersions = getTotalVersions(msg)
    const displayVersionIndex =
      totalVersions > 0 ? (versionIndex === 0 ? totalVersions : versionIndex) : 0
    const rawContent = getMessageContent(msg, versionIndex)
    const { text: displayContent, cost } = extractCostMeta(rawContent, msg.cost_meta)
    const isWaiting = msg.role === 'assistant' && displayContent === '__waiting__'
    const statusSteps = getStatusSteps(msg)
    const hasStatusSteps = statusSteps.length > 0
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
        'query_rewrite',
        'retrieve_chunks',
        'retrieval_ready',
      ].includes(key)
    })
    const hasThinking = msg.role === 'assistant' && Boolean(msg.thinking && msg.thinking.trim().length > 0)
    const showThinking = msg.role === 'assistant' && (hasThinking || isWaiting)
    const thinkingCollapsed = msg.thinking_collapsed ?? true
    const thinkingDone = msg.thinking_done ?? !isWaiting
    const thinkingLabel = thinkingDone ? '思考完成' : '正在思考'
    const hasRoundPrompt = msg.role === 'assistant' && Boolean(msg.has_round_prompt)

    return (
      <div ref={rowRef} className="flex flex-col">
        {msg.role === 'user' ? (
          <div className="flex justify-end">
            <div className={`group ${isEditingUser ? 'w-full max-w-full' : 'max-w-[80%]'}`}>
              <div className="bg-gray-100 text-gray-900 rounded-2xl px-4 py-2.5">
                {msg.images && msg.images.length > 0 && (
                  <div className="flex gap-2 mb-2 flex-wrap">
                    {msg.images.map((img, idx) => (
                      <img
                        key={idx}
                        src={img}
                        alt={`图片 ${idx + 1}`}
                        className="max-w-xs max-h-48 rounded-lg object-contain cursor-pointer"
                        onClick={() => onPreviewImage(img)}
                      />
                    ))}
                  </div>
                )}
                {isEditingUser ? (
                  <div className="space-y-2">
                    <textarea
                      value={editingContent}
                      onChange={(e) => onEditingContentChange(e.target.value)}
                      rows={4}
                      className="w-full resize-none bg-gray-100 px-0 py-0 text-base text-gray-900 focus:outline-none focus:ring-0 border-0"
                    />
                    <div className="flex justify-end gap-2">
                      <button
                        onClick={onCancelEdit}
                        className="h-8 w-8 rounded-md border border-gray-200 bg-white text-gray-600 hover:bg-gray-50 hover:text-gray-800 flex items-center justify-center"
                        title="取消编辑"
                      >
                        <X size={14} />
                      </button>
                      <button
                        onClick={() => onConfirmEdit(msg, replyAssistantId, editingContent)}
                        className="h-8 w-8 rounded-md border border-gray-200 bg-white text-gray-600 hover:bg-gray-50 hover:text-gray-800 flex items-center justify-center"
                        title="确认编辑"
                      >
                        <Check size={14} />
                      </button>
                    </div>
                  </div>
                ) : (
                  <div className="text-gray-900 max-h-64 overflow-y-auto pr-1 whitespace-pre-wrap break-words">
                    {msg.content}
                  </div>
                )}
              </div>
              {userReplyCompleted && !isEditingUser && (
                <div className="mt-1 flex justify-end gap-1.5 opacity-0 group-hover:opacity-100 transition-opacity">
                  <button
                    onClick={() => void onCopy(msg.content || '', `${msg.id}-user-copy`)}
                    className="h-8 w-8 rounded-md border border-gray-200 bg-white text-gray-600 hover:bg-gray-50 hover:text-gray-800 flex items-center justify-center"
                    title="复制"
                  >
                    {isCopied ? <Check size={14} className="text-green-600" /> : <Copy size={14} />}
                  </button>
                  <button
                    onClick={() => onBeginEdit(msg, replyAssistantId)}
                    className="h-8 w-8 rounded-md border border-gray-200 bg-white text-gray-600 hover:bg-gray-50 hover:text-gray-800 flex items-center justify-center"
                    title="编辑"
                  >
                    <Pencil size={14} />
                  </button>
                </div>
              )}
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
                      onToggleThinking(msg.id, open)
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
                        <MarkdownRenderer content={msg.thinking || ''} preset="chat" normalizeLatexDelimiters />
                      </div>
                    )}
                  </details>
                )}
                {!isWaiting && (
                  <MarkdownRenderer content={displayContent} preset="chat" normalizeLatexDelimiters />
                )}
                {isWaiting && (
                  <div className="mt-2 rounded-2xl border border-gray-200 bg-white px-4 py-3 text-sm text-gray-700 shadow-sm">
                    <div className="flex items-center gap-2 text-gray-800 font-medium">
                      <Loader2 size={15} className="animate-spin" />
                      <span>{hasArxivStatus ? '论文检索处理中' : '正在处理请求'}</span>
                    </div>
                    {hasStatusSteps && (
                      <div className="mt-3 space-y-1.5">
                        {statusSteps.map((step: any, idx: number) => {
                          const status = String(step?.status || 'running')
                          const isDone = status === 'done'
                          const isError = status === 'error'
                          const elapsedMs = Number(step?.elapsed_ms)
                          const elapsedLabel =
                            Number.isFinite(elapsedMs) && isDone
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
                  费用 {cost.currency === 'USD' ? '$' : ''}
                  {formatCost(Number(cost.total_cost || 0))} (prompt {cost.prompt_tokens}, completion{' '}
                  {cost.completion_tokens}, total {cost.total_tokens})
                </div>
              )}
              <div className="mt-2 flex items-center gap-2 text-xs text-gray-500">
                {totalVersions > 0 && (
                  <div className="flex items-center gap-1 px-2 py-1 bg-transparent rounded-none shadow-none ring-0 border-0">
                    <button
                      onClick={() => {
                        const nextIndex = versionIndex === 0 ? totalVersions - 1 : versionIndex - 1
                        onSetVersionIndex(msg.id, nextIndex)
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
                        const nextIndex = (versionIndex + 1) % totalVersions
                        onSetVersionIndex(msg.id, nextIndex)
                      }}
                      className="hover:text-gray-800 shadow-none ring-0 focus:outline-none focus:ring-0"
                      title="下一个版本"
                    >
                      <ChevronRight size={14} />
                    </button>
                  </div>
                )}
                <button
                  onClick={() => void onCopy(displayContent, msg.id)}
                  className="flex items-center gap-1 px-2 py-1 hover:bg-gray-100 rounded"
                  title="复制消息"
                >
                  {isCopied ? <Check size={14} className="text-green-600" /> : <Copy size={14} className="text-gray-600" />}
                </button>
                {hasRoundPrompt && (
                  <button
                    onClick={() => onOpenRoundPrompt?.(msg)}
                    className="flex items-center gap-1 px-2 py-1 hover:bg-gray-100 rounded"
                    title="查看本轮提示词"
                    aria-label="查看本轮提示词"
                  >
                    <FileText size={14} className="text-gray-600" />
                  </button>
                )}
                {isLatestRetryable && (
                  <button
                    onClick={() => onRetry?.(msg.id)}
                    className="flex items-center gap-1 px-2 py-1 hover:bg-gray-100 rounded"
                    title="重试"
                  >
                    <RotateCcw size={14} className="text-gray-600" />
                  </button>
                )}
              </div>
            </div>
          </div>
        )}
      </div>
    )
  },
  (prev, next) =>
    prev.msg === next.msg &&
    prev.versionIndex === next.versionIndex &&
    prev.isLatestRetryable === next.isLatestRetryable &&
    prev.userReplyCompleted === next.userReplyCompleted &&
    prev.replyAssistantId === next.replyAssistantId &&
    prev.isCopied === next.isCopied &&
    prev.isEditingUser === next.isEditingUser &&
    prev.editingContent === next.editingContent
)

MessageRow.displayName = 'MessageRow'

const MessageListInner = forwardRef<HTMLDivElement, MessageListProps>(
  ({ messages, onRetry, onOpenRoundPrompt, onSubmitUserEdit }, forwardedRef) => {
    const [copiedId, setCopiedId] = useState<string | null>(null)
    const [previewImage, setPreviewImage] = useState<string | null>(null)
    const [editingUserMessageId, setEditingUserMessageId] = useState<string | null>(null)
    const [editingContent, setEditingContent] = useState('')
    const [scrollTop, setScrollTop] = useState(0)
    const [viewportHeight, setViewportHeight] = useState(0)
    const [heightRevision, setHeightRevision] = useState(0)
    const { versionIndices, setVersionIndices, setMessages } = useAppStore()
    const containerRef = useRef<HTMLDivElement | null>(null)
    const itemHeightsRef = useRef<Record<string, number>>({})

    useImperativeHandle(forwardedRef, () => containerRef.current as HTMLDivElement)

    const handleCopy = useCallback(async (content: string, msgId: string) => {
      try {
        if (navigator.clipboard && window.isSecureContext) {
          await navigator.clipboard.writeText(content)
        } else {
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
        window.setTimeout(() => setCopiedId((current) => (current === msgId ? null : current)), 2000)
      } catch {
        addToast('复制失败，请手动复制', 'error')
      }
    }, [])

    const handleBeginEdit = useCallback((msg: Message, _assistantId: string | null) => {
      setEditingUserMessageId(msg.id)
      setEditingContent(msg.content || '')
    }, [])

    const handleCancelEdit = useCallback(() => {
      setEditingUserMessageId(null)
      setEditingContent('')
    }, [])

    const handleConfirmEdit = useCallback(
      (msg: Message, assistantId: string | null, content: string) => {
        const nextContent = content.trim()
        if (!nextContent) {
          addToast('编辑内容不能为空', 'warning')
          return
        }
        if (!assistantId) {
          addToast('未找到对应回复，无法提交编辑', 'error')
          return
        }
        setEditingUserMessageId(null)
        setEditingContent('')
        void Promise.resolve(
          onSubmitUserEdit?.({
            userMessageId: msg.id,
            assistantMessageId: assistantId,
            content: nextContent,
          })
        )
      },
      [onSubmitUserEdit]
    )

    const handleToggleThinking = useCallback(
      (msgId: string, open: boolean) => {
        setMessages((msgs) =>
          msgs.map((m) => (m.id === msgId ? { ...m, thinking_collapsed: !open } : m))
        )
      },
      [setMessages]
    )

    const handleSetVersionIndex = useCallback(
      (msgId: string, nextIndex: number) => {
        setVersionIndices({ ...versionIndices, [msgId]: nextIndex })
      },
      [setVersionIndices, versionIndices]
    )

    const visibleMessages = useMemo(
      () => messages.filter((msg) => msg.role !== 'system'),
      [messages]
    )

    const latestRetryableAssistantId = useMemo(() => {
      for (let i = visibleMessages.length - 1; i >= 0; i -= 1) {
        const msg = visibleMessages[i]
        if (msg.role !== 'assistant') continue
        const content = getMessageContent(msg, versionIndices[msg.id] ?? 0)
        if (!content || content === '__waiting__') continue
        return msg.id
      }
      return null
    }, [visibleMessages, versionIndices])

    const userReplyInfoById = useMemo(() => {
      const replyMap = new Map<string, UserReplyInfo>()
      let nextRole: 'assistant' | 'user' | null = null
      let nextAssistantId: string | null = null
      let nextAssistantCompleted = false

      for (let i = visibleMessages.length - 1; i >= 0; i -= 1) {
        const msg = visibleMessages[i]
        if (msg.role === 'assistant') {
          const nextContent = getMessageContent(msg, versionIndices[msg.id] ?? 0)
          nextRole = 'assistant'
          nextAssistantId = msg.id
          nextAssistantCompleted = Boolean(nextContent && nextContent.trim() && nextContent !== '__waiting__')
          continue
        }

        if (msg.role === 'user') {
          replyMap.set(msg.id, {
            completed: nextRole === 'assistant' ? nextAssistantCompleted : false,
            assistantId: nextRole === 'assistant' ? nextAssistantId : null,
          })
          nextRole = 'user'
          nextAssistantId = null
          nextAssistantCompleted = false
        }
      }

      return replyMap
    }, [visibleMessages, versionIndices])

    const reportHeight = useCallback((messageId: string, height: number) => {
      const safeHeight = Math.max(80, Math.ceil(height))
      if (itemHeightsRef.current[messageId] === safeHeight) return
      itemHeightsRef.current[messageId] = safeHeight
      setHeightRevision((value) => value + 1)
    }, [])

    useEffect(() => {
      const nextIds = new Set(visibleMessages.map((msg) => msg.id))
      let changed = false
      for (const key of Object.keys(itemHeightsRef.current)) {
        if (nextIds.has(key)) continue
        delete itemHeightsRef.current[key]
        changed = true
      }
      if (changed) {
        setHeightRevision((value) => value + 1)
      }
      if (editingUserMessageId && !nextIds.has(editingUserMessageId)) {
        setEditingUserMessageId(null)
        setEditingContent('')
      }
    }, [visibleMessages, editingUserMessageId])

    useEffect(() => {
      const node = containerRef.current
      if (!node) return
      const syncViewport = () => {
        setViewportHeight(node.clientHeight)
      }
      syncViewport()
      const observer = new ResizeObserver(syncViewport)
      observer.observe(node)
      return () => observer.disconnect()
    }, [])

    const handleScroll = useCallback((e: React.UIEvent<HTMLDivElement>) => {
      setScrollTop(e.currentTarget.scrollTop)
    }, [])

    const itemLayouts = useMemo(() => {
      let cursor = 0
      const layouts = visibleMessages.map((msg) => {
        const height = itemHeightsRef.current[msg.id] ?? ESTIMATED_ITEM_HEIGHT
        const top = cursor
        cursor += height + 24
        return {
          id: msg.id,
          top,
          height,
          bottom: cursor,
          message: msg,
        }
      })
      return {
        items: layouts,
        totalHeight: cursor > 0 ? cursor - 24 : 0,
      }
    }, [visibleMessages, heightRevision])

    const virtualRange = useMemo(() => {
      const overscan = Math.max(viewportHeight, MIN_OVERSCAN_PX)
      const startOffset = Math.max(0, scrollTop - overscan)
      const endOffset = scrollTop + viewportHeight + overscan
      const layouts = itemLayouts.items
      let startIndex = 0
      while (startIndex < layouts.length && layouts[startIndex].bottom < startOffset) {
        startIndex += 1
      }
      let endIndex = startIndex
      while (endIndex < layouts.length && layouts[endIndex].top <= endOffset) {
        endIndex += 1
      }
      return {
        startIndex: Math.max(0, startIndex),
        endIndex: Math.max(startIndex, endIndex),
      }
    }, [itemLayouts.items, scrollTop, viewportHeight])

    const virtualItems = useMemo(
      () => itemLayouts.items.slice(virtualRange.startIndex, virtualRange.endIndex),
      [itemLayouts.items, virtualRange.endIndex, virtualRange.startIndex]
    )

    return (
      <div
        ref={containerRef}
        className="h-full min-h-0 overflow-y-auto overscroll-contain px-6 py-4 bg-white"
        onScroll={handleScroll}
      >
        <div style={{ height: itemLayouts.totalHeight, position: 'relative' }}>
          {virtualItems.map((item) => {
            const msg = item.message
            const versionIndex = versionIndices[msg.id] ?? 0
            const replyInfo = userReplyInfoById.get(msg.id)
            const isUserCopied = copiedId === `${msg.id}-user-copy`
            const isAssistantCopied = copiedId === msg.id
            const isEditingUser = editingUserMessageId === msg.id
            return (
              <div
                key={msg.id}
                style={{
                  position: 'absolute',
                  top: item.top,
                  left: 0,
                  right: 0,
                }}
              >
                <div className="max-w-3xl mx-auto">
                  <MessageRow
                    msg={msg}
                    versionIndex={versionIndex}
                    isLatestRetryable={msg.id === latestRetryableAssistantId}
                    userReplyCompleted={replyInfo?.completed ?? false}
                    replyAssistantId={replyInfo?.assistantId ?? null}
                    isCopied={msg.role === 'user' ? isUserCopied : isAssistantCopied}
                    isEditingUser={isEditingUser}
                    editingContent={isEditingUser ? editingContent : ''}
                    onHeightChange={reportHeight}
                    onCopy={handleCopy}
                    onPreviewImage={setPreviewImage}
                    onBeginEdit={handleBeginEdit}
                    onCancelEdit={handleCancelEdit}
                    onEditingContentChange={setEditingContent}
                    onConfirmEdit={handleConfirmEdit}
                    onToggleThinking={handleToggleThinking}
                    onSetVersionIndex={handleSetVersionIndex}
                    onOpenRoundPrompt={onOpenRoundPrompt}
                    onRetry={onRetry}
                  />
                </div>
              </div>
            )
          })}
        </div>
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
