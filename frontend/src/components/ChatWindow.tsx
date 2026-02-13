// Review note:
// - 输入框上方展示 active papers（可打开 PDF，可单独 x 取消激活）。
// - 右侧资源面板展示会话 registry，可重新激活被误删的 paper。
import { useState, useRef, useEffect, useMemo, useCallback } from 'react'
import { useAppStore } from '../store/app'
import apiClient from '../api/client'
import MessageList from './MessageList'
import ChatInput from './ChatInput'
import { Plus, Download, ChevronDown, Check, FileText, X, Copy, AlertCircle, Library } from 'lucide-react'
import { addToast } from './ui'
import { ConversationPapersState, Message } from '../types/api'

interface ImageFile {
  file: File
  preview: string
  id: string
}

// 将文件转换为 base64
const fileToBase64 = (file: File): Promise<string> => {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => {
      const result = reader.result as string
      resolve(result)
    }
    reader.onerror = reject
    reader.readAsDataURL(file)
  })
}

const DEFAULT_SYSTEM_PROMPT = `你在对话中应当表现得自然、清晰、有条理。

优先进行真正的交流，而不仅是给出答案。
在回答问题时，关注用户的意图、语气和上下文，并相应调整表达方式。

假设用户是理性且有理解能力的，不要居高临下，也不要过度简化。

使用结构化表达来提升可读性，但避免生硬或学术化的语气。

在适当的时候表现出理解、耐心和共情，但不要过度拟人或制造情绪。

当存在不确定性时，应坦诚说明；当无法满足请求时，应清晰、礼貌地拒绝，并提供最接近的替代帮助。

目标是让用户感到被认真对待，而不是被说服、被教育或被敷衍。`

const getSystemPromptFromMessages = (msgs: Message[]): string => {
  for (let i = msgs.length - 1; i >= 0; i--) {
    if (msgs[i].role === 'system') {
      const content = (msgs[i].content || '').trim()
      if (content) return msgs[i].content
    }
  }
  return ''
}

function ChatWindow() {
  const {
    currentTool,
    currentConversation,
    messages,
    setMessages,
    setCurrentConversation,
    setConversations,
    apiConfig,
    availableModels,
    availableModelGroups,
    setApiConfig,
    hasBackendApiKey,
    chatLoading,
    setChatLoading,
    versionIndices,
    setVersionIndices,
    contextRounds,
    setContextRounds,
  } = useAppStore()

  const [inputValue, setInputValue] = useState('')
  const [images, setImages] = useState<ImageFile[]>([])
  const [isStreaming, setIsStreaming] = useState(false)
  const [isModelMenuOpen, setIsModelMenuOpen] = useState(false)
  const [promptPanelOpen, setPromptPanelOpen] = useState(false)
  const [paperPanelOpen, setPaperPanelOpen] = useState(false)
  const [focusedPaperId, setFocusedPaperId] = useState<string | null>(null)
  const [systemPromptDraft, setSystemPromptDraft] = useState('')
  const [promptSaving, setPromptSaving] = useState(false)
  const [paperState, setPaperState] = useState<ConversationPapersState>({
    active_ids: [],
    papers: [],
  })
  const [selectedVendor, setSelectedVendor] = useState<string>('')
  const vendorOffsetPx = useMemo(() => {
    if (availableModelGroups.length === 0) return 0
    const idx = Math.max(
      0,
      availableModelGroups.findIndex((g) => g.name === selectedVendor)
    )
    const itemHeight = 36
    const listPaddingTop = 8
    return idx * itemHeight + listPaddingTop
  }, [availableModelGroups, selectedVendor])
  const messagesContainerRef = useRef<HTMLDivElement>(null)
  const isStreamingRef = useRef(false)
  const autoScrollPausedRef = useRef(false)
  const lastScrollTopRef = useRef(0)
  const isProgrammaticScrollRef = useRef(false)
  const abortControllerRef = useRef<AbortController | null>(null)
  const sendMessageRef = useRef<
    | ((
        messageContent: string,
        imageDataList: string[],
        options?: { skipInputReset?: boolean; autoTitle?: boolean; retryMessageId?: string }
      ) => Promise<void>)
    | null
  >(null)
  const hasVisibleMessages = useMemo(
    () => messages.some((m) => m.role !== 'system'),
    [messages]
  )
  const activePapers = useMemo(
    () => (paperState.papers || []).filter((p) => p.is_active),
    [paperState]
  )

  const refreshConversationPapers = useCallback(async (convId?: string | null) => {
    if (!convId) {
      setPaperState({ active_ids: [], papers: [] })
      return
    }
    try {
      const res = await apiClient.getConversationPapers(convId)
      setPaperState(res.data || { active_ids: [], papers: [] })
    } catch (error) {
      console.error('Failed to load conversation papers:', error)
      setPaperState({ active_ids: [], papers: [] })
    }
  }, [])

  const handleDeactivatePaper = useCallback(async (canonicalId: string) => {
    if (!currentConversation?.id) return
    try {
      const res = await apiClient.deactivateConversationPaper(currentConversation.id, canonicalId)
      setPaperState(res.data || { active_ids: [], papers: [] })
    } catch (error) {
      console.error('Failed to deactivate paper:', error)
      addToast('取消激活失败', 'error')
    }
  }, [currentConversation?.id])

  const handleActivatePaper = useCallback(async (canonicalId: string) => {
    if (!currentConversation?.id) return
    try {
      const res = await apiClient.activateConversationPapers(currentConversation.id, [canonicalId])
      setPaperState(res.data || { active_ids: [], papers: [] })
    } catch (error) {
      console.error('Failed to activate paper:', error)
      addToast('激活失败', 'error')
    }
  }, [currentConversation?.id])

  useEffect(() => {
    isStreamingRef.current = isStreaming
  }, [isStreaming])

  useEffect(() => {
    const container = messagesContainerRef.current
    if (!container) return
    const handleScroll = () => {
      const threshold = 80
      const currentTop = container.scrollTop
      const distanceToBottom = container.scrollHeight - currentTop - container.clientHeight
      const atBottom = distanceToBottom < threshold
      const delta = currentTop - lastScrollTopRef.current
      const scrollingUp = delta < 0
      const scrollingDown = delta > 0

      // 向上滚动永远认为是用户意图（即使此时程序也在滚动）
      if (scrollingUp && isStreamingRef.current) {
        autoScrollPausedRef.current = true
      }

      if (!isProgrammaticScrollRef.current) {
        if (isStreamingRef.current) {
          if (scrollingDown && atBottom) {
            // 用户向下滚动回到底部，恢复自动滚动
            autoScrollPausedRef.current = false
          }
        } else if (atBottom) {
          // 非流式时，始终允许自动滚动到底部
          autoScrollPausedRef.current = false
        }
      }

      lastScrollTopRef.current = currentTop
    }
    const handleWheel = (e: WheelEvent) => {
      if (!isStreamingRef.current) return
      if (e.deltaY < 0) {
        // 贴底时滚轮上滑可能几乎不改变 scrollTop，这里直接按用户意图暂停跟随
        autoScrollPausedRef.current = true
      }
    }
    handleScroll()
    container.addEventListener('scroll', handleScroll, { passive: true })
    container.addEventListener('wheel', handleWheel, { passive: true })
    return () => {
      container.removeEventListener('scroll', handleScroll)
      container.removeEventListener('wheel', handleWheel)
    }
  }, [hasVisibleMessages, currentConversation?.id])

  useEffect(() => {
    const container = messagesContainerRef.current
    if (!container) return
    if (autoScrollPausedRef.current) return
    isProgrammaticScrollRef.current = true
    container.scrollTo({
      top: container.scrollHeight,
      behavior: isStreaming ? 'auto' : 'smooth',
    })
    requestAnimationFrame(() => {
      isProgrammaticScrollRef.current = false
    })
  }, [messages, isStreaming])

  useEffect(() => {
    if (promptPanelOpen) return
    if (currentTool) {
      setSystemPromptDraft(currentTool.system_prompt || '')
      return
    }
    const fromMessages = getSystemPromptFromMessages(messages)
    setSystemPromptDraft(fromMessages || DEFAULT_SYSTEM_PROMPT)
  }, [
    promptPanelOpen,
    currentTool?.id,
    currentTool?.system_prompt,
    currentConversation?.id,
    messages,
  ])


  useEffect(() => {
    if (availableModelGroups.length === 0) return
    const storedVendor = localStorage.getItem('selectedModelVendor') || ''
    const model = apiConfig.model
    const matched = availableModelGroups.find(g => g.models.includes(model))
    const initialVendor = matched?.name || storedVendor || availableModelGroups[0]?.name || ''
    setSelectedVendor(initialVendor)
  }, [availableModelGroups, apiConfig.model])

  const vendorModels = useMemo(() => {
    const group = availableModelGroups.find(g => g.name === selectedVendor)
    return group?.models || []
  }, [availableModelGroups, selectedVendor])

  // 当切换对话时，加载该对话的消息
  useEffect(() => {
    const loadMessages = async () => {
      if (!currentConversation) {
        setMessages([])
        return
      }

      // 如果正在聊天中（loading 或 streaming），不重新加载消息
      // 这样可以避免覆盖正在流式输出的内容
      if (chatLoading || isStreaming) {
        return
      }

      try {
        const res = await apiClient.getConversation(currentConversation.id)
        setMessages(res.data.messages || [])
      } catch (error) {
        console.error('Failed to load messages:', error)
        setMessages([])
      }
    }

    loadMessages()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [currentConversation?.id])

  useEffect(() => {
    refreshConversationPapers(currentConversation?.id ?? null)
  }, [currentConversation?.id, refreshConversationPapers])

  // 创建新对话（仅重置为新会话态，首次发送时再落库）
  const handleNewConversation = () => {
    if (!currentTool) return
    setCurrentConversation(null)
    setMessages([])
  }

  // 导出对话
  const handleExportConversation = async () => {
    if (!currentConversation) return

    try {
      const res = await apiClient.exportConversation(currentConversation.id)
      const element = document.createElement('a')
      element.setAttribute('href', 'data:text/markdown;charset=utf-8,' + encodeURIComponent(res.data.markdown))
      element.setAttribute('download', `${currentConversation.id}.md`)
      element.style.display = 'none'
      document.body.appendChild(element)
      element.click()
      document.body.removeChild(element)
    } catch (error) {
      console.error('Failed to export conversation:', error)
    }
  }

  // 停止生成
  const handleStopGeneration = () => {
    setIsStreaming(false)
    setChatLoading(false)
    addToast('已停止生成', 'info')
    if (currentConversation?.id) {
      apiClient.stopChat(currentConversation.id).catch(() => {})
    }
  }

  const handleSaveSystemPrompt = async () => {
    if (currentTool) return
    let conv = currentConversation
    try {
      setPromptSaving(true)
      if (!conv) {
        const newConv = await apiClient.createConversation(
          null,
          `通用聊天 - ${new Date().toLocaleString()}`
        )
        conv = newConv.data
        setCurrentConversation(conv)
        setConversations(prev => [conv!, ...prev])
      }
      if (!conv) return
      await apiClient.updateConversation(conv.id, {
        system_prompt: systemPromptDraft,
      })
      const refresh = await apiClient.getConversation(conv.id)
      setMessages(refresh.data.messages || [])
      addToast('系统提示词已保存', 'success')
    } catch (error) {
      console.error('Failed to save system prompt:', error)
      addToast('保存失败', 'error')
    } finally {
      setPromptSaving(false)
    }
  }

  const handleCopySystemPrompt = async () => {
    try {
      await navigator.clipboard.writeText(systemPromptDraft || '')
      addToast('已复制提示词', 'success')
    } catch (error) {
      console.error('Failed to copy system prompt:', error)
      addToast('复制失败', 'error')
    }
  }

  const sendMessageWithPayload = async (
    messageContent: string,
    imageDataList: string[],
    options?: { skipInputReset?: boolean; autoTitle?: boolean; retryMessageId?: string }
  ) => {
    if ((!messageContent.trim() && imageDataList.length === 0) || chatLoading) return
    
    // 检查是否有 API Key（前端或后端）
    if (!apiConfig.api_key && !hasBackendApiKey) {
      addToast('请先配置 API Key', 'warning')
      return
    }
    // 必须选择模型
    if (!apiConfig.model) {
      addToast('请先选择模型', 'warning')
      return
    }

    const shouldAutoTitle = options?.autoTitle ?? false
    const retryMessageId = options?.retryMessageId

    let waitingMessageId: string | null = null
    let conversationId: string | null = currentConversation?.id || null
    const clearWaitingMessage = () => {
      if (!waitingMessageId) return
      setMessages((msgs) => msgs.filter(m => m.id !== waitingMessageId))
    }
    let flushTimer: number | null = null
    const stopFlush = () => {
      if (flushTimer !== null) {
        clearInterval(flushTimer)
        flushTimer = null
      }
    }
    try {
      setChatLoading(true)

      // 如果没有会话，先创建一个
      let conversationTitle = currentConversation?.title
      if (!conversationId) {
        const newConv = await apiClient.createConversation(
          currentTool?.id || null,
          currentTool
            ? `${currentTool.name} - ${new Date().toLocaleString()}`
            : `通用聊天 - ${new Date().toLocaleString()}`
        )
        conversationId = newConv.data.id
        conversationTitle = newConv.data.title
        setCurrentConversation(newConv.data)
        setConversations(prev => [newConv.data, ...prev])  // 使用函数式更新
      }

      // 如果是重试，不添加新的用户消息，而是使用原来的
      if (!retryMessageId) {
        // 添加用户消息到本地
        const userMessage = {
          id: Date.now().toString(),
          conversation_id: conversationId,
          role: 'user' as const,
          content: messageContent,
          images: imageDataList,
          created_at: new Date().toISOString(),
        }
        setMessages((msgs) => [...(Array.isArray(msgs) ? msgs : []), userMessage])
      }

      if (!options?.skipInputReset) {
        setInputValue('')
        setImages([])
      }

      // 调用聊天API - 使用完整的API配置
      setIsStreaming(true)
      const controller = new AbortController()
      abortControllerRef.current = controller
      const response = await apiClient.chat({
        conversation_id: conversationId,
        tool_id: currentTool?.id ?? null,
        message: messageContent,
        images: imageDataList,
        context_rounds: contextRounds,
        api_config: {
          api_key: apiConfig.api_key,
          base_url: apiConfig.base_url,
          model: apiConfig.model,
          temperature: apiConfig.temperature,
          max_tokens: apiConfig.max_tokens,
          top_p: apiConfig.top_p,
          frequency_penalty: apiConfig.frequency_penalty,
          presence_penalty: apiConfig.presence_penalty,
        },
        retry_message_id: retryMessageId,
        selected_versions: versionIndices,
      }, controller.signal)

      // 处理流式SSE响应 - 使用缓冲区减少重新渲染
      let assistantMessageId = retryMessageId || ''
      let assistantCreated = !!retryMessageId // 只有重试时才认为已创建（不需要创建新消息）
      let thinkingBuffer = ''
      let statusStepOrder = 0
      let pendingContent = ''
      let pendingThinking = ''
      const flushIntervalMs = 50
      const contentChunkSize = 24
      const thinkingChunkSize = 48
      const flushBuffers = (forceAll: boolean) => {
        if (!pendingContent && !pendingThinking) {
          if (forceAll) stopFlush()
          return
        }
        const contentChunk = forceAll ? pendingContent : pendingContent.slice(0, contentChunkSize)
        const thinkingChunk = forceAll ? pendingThinking : pendingThinking.slice(0, thinkingChunkSize)
        pendingContent = pendingContent.slice(contentChunk.length)
        pendingThinking = pendingThinking.slice(thinkingChunk.length)
        if (!contentChunk && !thinkingChunk) return
        setMessages((msgs) => {
          const targetId = assistantCreated ? assistantMessageId : waitingMessageId
          if (!targetId) return msgs
          const msgIdx = msgs.findIndex(m => m.id === targetId)
          if (msgIdx < 0) return msgs
          const updatedMsgs = [...msgs]
          const prev = updatedMsgs[msgIdx] as any
          const next: any = { ...prev }
          if (contentChunk) {
            next.content = (prev.content || '') + contentChunk
          }
          if (thinkingChunk) {
            next.thinking = (prev.thinking || '') + thinkingChunk
            next.thinking_collapsed = prev.thinking_collapsed ?? true
            next.thinking_done = false
          }
          updatedMsgs[msgIdx] = next
          return updatedMsgs
        })
        if (!pendingContent && !pendingThinking) {
          stopFlush()
        }
      }
      const startFlush = () => {
        if (flushTimer !== null) return
        flushTimer = window.setInterval(() => flushBuffers(false), flushIntervalMs)
      }
      let firstTokenReceived = false // 标记是否接收到第一个token
      if (!retryMessageId) {
        waitingMessageId = `waiting-${Date.now()}`
        const waitingMessage = {
          id: waitingMessageId,
          conversation_id: conversationId,
          role: 'assistant' as const,
          content: '__waiting__',
          extra: { status_steps: [] },
          thinking_collapsed: true,
          thinking_done: false,
          created_at: new Date().toISOString(),
        }
        setMessages((msgs) => [...(Array.isArray(msgs) ? msgs : []), waitingMessage])
      }

      for await (const { event, data } of apiClient.readStream(response)) {
        if (event === 'start') {
          // 开始事件，包含message_id
          if (data && typeof data === 'object' && 'message_id' in data) {
            assistantMessageId = (data as any).message_id || assistantMessageId
          }
          continue
        } else if (event === 'status') {
          const status = data && typeof data === 'object' ? (data as any) : null
          if (!status) continue
          const stepId = String(status.step_id || '')
          const key = String(status.key || '')
          const statusText = String(status.message || '')
          if (!stepId || !statusText) continue
          const statusKind = String(status.status || 'running')
          const elapsedMs = Number(status.elapsed_ms)
          const elapsedSafe = Number.isFinite(elapsedMs) ? Math.max(0, elapsedMs) : undefined
          const filename = status.filename ? String(status.filename) : undefined
          const paperId = status.paper_id ? String(status.paper_id) : undefined
          const targetId = assistantCreated ? assistantMessageId : waitingMessageId
          if (!targetId) continue

          setMessages((msgs) => {
            const msgIdx = msgs.findIndex((m) => m.id === targetId)
            if (msgIdx < 0) return msgs
            const updated = [...msgs]
            const msg: any = { ...updated[msgIdx] }
            const extra = { ...(msg.extra || {}) }
            const oldSteps = Array.isArray(extra.status_steps) ? [...extra.status_steps] : []
            const oldIdx = oldSteps.findIndex((s: any) => s && s.step_id === stepId)
            if (oldIdx >= 0) {
              oldSteps[oldIdx] = {
                ...oldSteps[oldIdx],
                key,
                message: statusText,
                status: statusKind,
                elapsed_ms: elapsedSafe ?? oldSteps[oldIdx]?.elapsed_ms,
                filename: filename ?? oldSteps[oldIdx]?.filename,
                paper_id: paperId ?? oldSteps[oldIdx]?.paper_id,
              }
            } else {
              oldSteps.push({
                step_id: stepId,
                key,
                message: statusText,
                status: statusKind,
                elapsed_ms: elapsedSafe,
                filename,
                paper_id: paperId,
                order: statusStepOrder++,
              })
            }
            extra.status_steps = oldSteps
            msg.extra = extra
            updated[msgIdx] = msg
            return updated
          })
          continue
        } else if (event === 'thinking') {
          if (data && typeof data === 'object' && 'content' in data) {
            const chunk = (data as any).content as string
            thinkingBuffer += chunk
            pendingThinking += chunk
            startFlush()
          }
          continue
        } else if (event === 'token') {
          // token 事件 - 来自后端的实际内容
          if (data && typeof data === 'object' && 'content' in data) {
            const token = (data as any).content

            // 第一次收到内容时，创建或更新助手消息
            if (!assistantCreated) {
              if (!assistantMessageId) {
                assistantMessageId = Date.now().toString()
              }
              const initialMessage = {
                id: assistantMessageId,
                conversation_id: conversationId,
                role: 'assistant' as const,
                content: token,
                thinking: thinkingBuffer || undefined,
                thinking_collapsed: thinkingBuffer ? true : undefined,
                thinking_done: thinkingBuffer ? false : true,
                created_at: new Date().toISOString(),
              }
              setMessages((msgs) => {
                const filtered = waitingMessageId ? msgs.filter(m => m.id !== waitingMessageId) : msgs
                return [...filtered, initialMessage]
              })
              assistantCreated = true
              firstTokenReceived = true
              thinkingBuffer = ''
              pendingThinking = ''
            } else if (!firstTokenReceived && retryMessageId) {
              // 重试时第一次收到token，清空旧内容，只保留新内容
              firstTokenReceived = true
              setMessages((msgs) => {
                const msgIdx = msgs.findIndex(m => m.id === assistantMessageId)
                if (msgIdx >= 0) {
                  const updatedMsgs = [...msgs]
                  updatedMsgs[msgIdx] = {
                    ...updatedMsgs[msgIdx],
                    content: token, // 替换而不是追加
                    thinking: thinkingBuffer || '',
                    thinking_collapsed: thinkingBuffer ? true : updatedMsgs[msgIdx].thinking_collapsed,
                    thinking_done: thinkingBuffer ? false : updatedMsgs[msgIdx].thinking_done,
                  }
                  return updatedMsgs
                }
                return msgs
              })
              thinkingBuffer = ''
              pendingThinking = ''
            } else {
              // 追加到待刷新缓冲区，按固定步长匀速输出
              pendingContent += token
              startFlush()
            }
          }
        } else if (event === 'done') {
          // 最后把剩余内容快速刷完
          flushBuffers(true)
          pendingContent = ''
          pendingThinking = ''
          stopFlush()
          setIsStreaming(false)
          setChatLoading(false)
          
          // 如果后端返回了完整的消息对象（包含retry_versions），用它更新消息
          if (data && typeof data === 'object' && 'message' in data) {
            const completeMessage = (data as any).message
            setMessages((msgs) => {
              const msgIdx = msgs.findIndex(m => m.id === assistantMessageId)
              if (msgIdx >= 0) {
                const updatedMsgs = [...msgs]
                const prev = updatedMsgs[msgIdx] as any
                updatedMsgs[msgIdx] = {
                  ...completeMessage,
                  thinking_collapsed: prev?.thinking_collapsed ?? (completeMessage.thinking ? true : undefined),
                  thinking_done: true,
                }
                return updatedMsgs
              }
              return msgs
            })
            // 收到完整消息后，默认选中最新版本
            setVersionIndices({ ...versionIndices, [assistantMessageId]: 0 })
          } else if (assistantMessageId) {
            // 兜底：确保消息ID正确（避免使用临时ID导致重试记录丢失）
            setMessages((msgs) => {
              const msgIdx = msgs.findIndex(m => m.id === assistantMessageId)
              if (msgIdx >= 0) return msgs
              // 如果找不到，尝试用最新一条assistant消息替换ID
              const lastIdx = [...msgs].reverse().findIndex(m => m.role === 'assistant')
              if (lastIdx >= 0) {
                const realIdx = msgs.length - 1 - lastIdx
                const updatedMsgs = [...msgs]
                updatedMsgs[realIdx] = { ...updatedMsgs[realIdx], id: assistantMessageId }
                return updatedMsgs
              }
              return msgs
            })
          }
          clearWaitingMessage()
          if (assistantMessageId) {
            setMessages((msgs) =>
              msgs.map((m) =>
                m.id === assistantMessageId ? { ...m, thinking_done: true } : m
              )
            )
          }
          break
        } else if (event === 'stopped') {
          // 停止事件 - 也需要刷新缓冲区
          flushBuffers(true)
          pendingContent = ''
          pendingThinking = ''
          stopFlush()
          setIsStreaming(false)
          setChatLoading(false)
          
          if (data && typeof data === 'object' && 'message' in data) {
            const completeMessage = (data as any).message
            setMessages((msgs) => {
              const msgIdx = msgs.findIndex(m => m.id === assistantMessageId)
              if (msgIdx >= 0) {
                const updatedMsgs = [...msgs]
                const prev = updatedMsgs[msgIdx] as any
                updatedMsgs[msgIdx] = {
                  ...completeMessage,
                  thinking_collapsed: prev?.thinking_collapsed ?? (completeMessage.thinking ? true : undefined),
                  thinking_done: true,
                }
                return updatedMsgs
              }
              return msgs
            })
            setVersionIndices({ ...versionIndices, [assistantMessageId]: 0 })
          } else if (assistantMessageId) {
            setMessages((msgs) => {
              const msgIdx = msgs.findIndex(m => m.id === assistantMessageId)
              if (msgIdx >= 0) return msgs
              const lastIdx = [...msgs].reverse().findIndex(m => m.role === 'assistant')
              if (lastIdx >= 0) {
                const realIdx = msgs.length - 1 - lastIdx
                const updatedMsgs = [...msgs]
                updatedMsgs[realIdx] = { ...updatedMsgs[realIdx], id: assistantMessageId }
                return updatedMsgs
              }
              return msgs
            })
          }

          clearWaitingMessage()
          if (assistantMessageId) {
            setMessages((msgs) =>
              msgs.map((m) =>
                m.id === assistantMessageId ? { ...m, thinking_done: true } : m
              )
            )
          }
          break
        } else if (event === 'error') {
          // 错误事件
          if (data && typeof data === 'object' && 'error' in data) {
            throw new Error((data as any).error)
          }
          flushBuffers(true)
          pendingContent = ''
          pendingThinking = ''
          stopFlush()
          setIsStreaming(false)
          setChatLoading(false)
          clearWaitingMessage()
          if (assistantMessageId) {
            setMessages((msgs) =>
              msgs.map((m) =>
                m.id === assistantMessageId ? { ...m, thinking_done: true } : m
              )
            )
          }
          break
        }
      }

      setIsStreaming(false)
      clearWaitingMessage()
      if (conversationId) {
        await refreshConversationPapers(conversationId)
      }

      // 在第一次回复后自动生成标题（重试时不生成）
      if (shouldAutoTitle && conversationId && conversationTitle && !retryMessageId) {
        apiClient.generateConversationTitle(conversationId, {
          api_key: apiConfig.api_key,
          base_url: apiConfig.base_url,
          model: apiConfig.model,
          temperature: apiConfig.temperature,
          max_tokens: apiConfig.max_tokens,
          top_p: apiConfig.top_p,
          frequency_penalty: apiConfig.frequency_penalty,
          presence_penalty: apiConfig.presence_penalty,
        })
          .then(titleRes => {
            if (titleRes.data.success) {
              const newTitle = titleRes.data.title
              if (currentConversation?.id === conversationId) {
                setCurrentConversation({
                  ...currentConversation,
                  title: newTitle,
                })
              }
              // 更新对话列表中的标题，并保持顺序不变（已经在开头了）
              setConversations(prevConversations =>
                prevConversations.map(c =>
                  c.id === conversationId ? { ...c, title: newTitle } : c
                )
              )
            }
          })
          .catch(err => {
            console.error('Failed to generate title:', err)
          })
      }
    } catch (error: any) {
      if (error?.name === 'AbortError') {
        clearWaitingMessage()
        stopFlush()
        setIsStreaming(false)
        return
      }
      console.error('Failed to send message:', error)
      clearWaitingMessage()
      const errorText =
        typeof error?.message === 'string'
          ? error.message
          : '发送失败，请重试'

      // 在对话区显示错误作为一条assistant消息
      const errorMessage = {
        id: `error-${Date.now()}`,
        conversation_id: currentConversation?.id || conversationId || '',
        role: 'assistant' as const,
        content: `⚠️ ${errorText}`,
        created_at: new Date().toISOString(),
      }
      setMessages((msgs) => [...(Array.isArray(msgs) ? msgs : []), errorMessage])

      addToast('发送失败，请重试', 'error')
      setIsStreaming(false) // 确保错误时也停止流式传输状态
    } finally {
      stopFlush()
      setChatLoading(false)
      abortControllerRef.current = null
    }
  }

  useEffect(() => {
    sendMessageRef.current = sendMessageWithPayload
  }, [sendMessageWithPayload])

  // 发送消息
  const handleSendMessage = async () => {
    if ((!inputValue.trim() && images.length === 0) || chatLoading) return
    if (!apiConfig.api_key && !hasBackendApiKey) {
      addToast('请先配置 API Key', 'warning')
      return
    }

    const isFirstMessage = !currentConversation || messages.length === 0

    // 转换图片为 base64
    const imageDataList: string[] = []
    for (const img of images) {
      const base64 = await fileToBase64(img.file)
      imageDataList.push(base64)
    }

    await sendMessageWithPayload(inputValue, imageDataList, {
      skipInputReset: false,
      autoTitle: isFirstMessage,
    })
  }

  const handleRetryMessage = useCallback(async (assistantMessageId: string) => {
    if (chatLoading) return
    const idx = messages.findIndex(m => m.id === assistantMessageId)
    if (idx <= 0) return

    // 找到该助手消息之前最近的用户消息
    let userMsg = null as (typeof messages)[number] | null
    for (let i = idx - 1; i >= 0; i--) {
      if (messages[i].role === 'user') {
        userMsg = messages[i]
        break
      }
    }
    if (!userMsg) return

    // 重试前将版本选择重置为最新
    setVersionIndices({ ...versionIndices, [assistantMessageId]: 0 })

    // 立即显示等待提示，等待流式输出
    setMessages((msgs) => {
      const msgIdx = msgs.findIndex(m => m.id === assistantMessageId)
      if (msgIdx >= 0) {
        const updated = [...msgs]
        updated[msgIdx] = {
          ...updated[msgIdx],
          content: '__waiting__',
          thinking: '',
          thinking_collapsed: true,
          thinking_done: false,
          cost_meta: null,
          extra: {
            ...(updated[msgIdx] as any).extra,
            status_steps: [],
          },
        }
        return updated
      }
      return msgs
    })

    // 发送消息，但标记为重试（会替换而不是新增消息）
    await sendMessageRef.current?.(userMsg.content, userMsg.images || [], {
      skipInputReset: true,
      autoTitle: false,
      retryMessageId: assistantMessageId,  // 传递要替换的消息ID
    })
  }, [messages, chatLoading, versionIndices])

  const renderActivePaperChips = () => {
    if (!activePapers.length) return null
    return (
      <div className="mb-3 flex flex-wrap gap-2">
        {activePapers.map((paper) => (
          <div
            key={paper.canonical_id}
            className="group inline-flex items-center rounded-full border border-gray-200 bg-gray-50 pr-1"
            title={paper.title || paper.paper_id}
          >
            <button
              type="button"
              onClick={() => {
                setFocusedPaperId(paper.canonical_id)
                setPaperPanelOpen(true)
                window.setTimeout(() => {
                  setFocusedPaperId((prev) => (prev === paper.canonical_id ? null : prev))
                }, 1000)
              }}
              className="px-3 py-1.5 text-xs text-gray-800 hover:text-gray-900"
            >
              {paper.filename}
            </button>
            <button
              type="button"
              onClick={() => handleDeactivatePaper(paper.canonical_id)}
              className="mr-1 h-5 w-5 rounded-full text-gray-500 transition hover:bg-gray-200 hover:text-gray-700"
              title="取消激活"
            >
              <X size={12} className="mx-auto" />
            </button>
          </div>
        ))}
      </div>
    )
  }

  return (
    <div className="flex-1 flex flex-col bg-white text-gray-900 h-full overflow-hidden relative min-h-0">
      {/* 工具栏 */}
      <div className="border-b border-gray-200 px-6 py-4 flex items-center justify-between bg-white flex-shrink-0">
        <div className="flex items-center gap-4">
          {currentTool ? (
            <>
              <span className="text-2xl">{currentTool.icon}</span>
              <div>
                <h2 className="font-bold text-gray-900">{currentTool.name}</h2>
                <p className="text-xs text-gray-600">{currentTool.description}</p>
              </div>
            </>
          ) : (
            <>
              {/* <span className="text-2xl">💬</span> */}
              <div>
                <h2 className="font-bold text-gray-900">通用聊天</h2>
                <p className="text-xs text-gray-600">与AI助手直接对话</p>
              </div>
            </>
          )}
        </div>
        <div className="flex-1 flex justify-center">
          {availableModels.length > 0 ? (
            <div className="relative inline-block">
              <button
                className="inline-flex items-center gap-2 px-4 py-2 rounded-full border border-gray-200 bg-gray-50 text-sm text-gray-800 hover:bg-gray-100 transition"
                onClick={() => setIsModelMenuOpen((v) => !v)}
              >
                <span className="text-gray-500">选择模型</span>
                <span className="text-gray-900 font-medium">{apiConfig.model}</span>
                <ChevronDown size={16} className="text-gray-500" />
              </button>
              {isModelMenuOpen && (
                <>
                  <div
                    className="fixed inset-0 z-40"
                    onClick={() => setIsModelMenuOpen(false)}
                  />
                  <div className="absolute top-full mt-2 z-50">
                    <div className="relative">
                      <div className="bg-white border border-gray-200 rounded-lg shadow-lg min-w-44">
                        {availableModelGroups.length > 0 ? (
                          availableModelGroups.map((group) => (
                            <button
                              key={group.name}
                              onClick={() => {
                                setSelectedVendor(group.name)
                                localStorage.setItem('selectedModelVendor', group.name)
                              }}
                              className={`w-full text-left px-4 py-2 text-sm transition flex items-center justify-between ${
                                selectedVendor === group.name
                                  ? 'bg-gray-100 text-gray-900'
                                  : 'text-gray-700 hover:bg-gray-50'
                              }`}
                            >
                              <span>{group.name}</span>
                              <ChevronDown size={14} className="text-gray-400 rotate-[-90deg]" />
                            </button>
                          ))
                        ) : (
                          <div className="px-4 py-2 text-sm text-gray-500">无分组</div>
                        )}
                      </div>
                      <div
                        className="bg-white border border-gray-200 rounded-lg shadow-lg min-w-56 absolute"
                        style={{ top: vendorOffsetPx, left: 'calc(100% + 8px)' }}
                      >
                      {vendorModels.length > 0 ? (
                        vendorModels.map((m) => (
                          <button
                            key={`${selectedVendor}-${m}`}
                            onClick={() => {
                              setApiConfig({ model: m })
                              setIsModelMenuOpen(false)
                            }}
                            className="w-full text-left px-4 py-2 text-sm hover:bg-gray-50 transition flex items-center gap-2"
                          >
                            <span className="flex-1 text-gray-900">{m}</span>
                            {apiConfig.model === m && <Check size={16} className="text-gray-600" />}
                          </button>
                        ))
                      ) : (
                        <div className="px-4 py-2 text-sm text-gray-500">请选择厂商</div>
                      )}
                      </div>
                    </div>
                  </div>
                </>
              )}
            </div>
          ) : (
            <div className="text-xs text-gray-500">
              未加载模型列表，请确认后端已重启并配置 `OPENAI_MODELS`
            </div>
          )}
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => setPaperPanelOpen(true)}
            className="flex items-center gap-2 px-3 py-2 hover:bg-gray-100 rounded-lg transition text-sm text-gray-600 hover:text-gray-900"
          >
            <Library size={18} />
            资源
            {paperState.papers.length > 0 && (
              <span className="text-xs text-gray-500">
                {activePapers.length}/{paperState.papers.length}
              </span>
            )}
          </button>
          <button
            onClick={() => setPromptPanelOpen(true)}
            className="flex items-center gap-2 px-3 py-2 hover:bg-gray-100 rounded-lg transition text-sm text-gray-600 hover:text-gray-900"
          >
            <FileText size={18} />
            系统提示词
          </button>
          <div className="flex items-center gap-2">
            <span className="text-xs text-gray-500">上下文轮数</span>
            <select
              value={contextRounds}
              onChange={(e) => setContextRounds(parseInt(e.target.value, 10))}
              className="text-xs border border-gray-200 rounded-md px-2 py-1 bg-white text-gray-700 focus:outline-none focus:ring-1 focus:ring-gray-300"
            >
              {Array.from({ length: 21 }, (_, i) => i).map((n) => (
                <option key={n} value={n}>{n}</option>
              ))}
            </select>
            <button
              type="button"
              className="text-gray-400 hover:text-gray-600 cursor-help"
              title="0=不带历史（仅发送当前消息）"
              aria-label="0=不带历史（仅发送当前消息）"
            >
              <AlertCircle size={14} />
            </button>
          </div>
          {currentTool && (
            <button
              onClick={handleNewConversation}
              className="flex items-center gap-2 px-3 py-2 hover:bg-gray-100 rounded-lg transition text-sm text-gray-600 hover:text-gray-900"
            >
              <Plus size={18} />
              新建
            </button>
          )}
          <button
            onClick={handleExportConversation}
            disabled={!currentConversation}
            className="flex items-center gap-2 px-3 py-2 hover:bg-gray-100 rounded-lg transition text-sm text-gray-600 hover:text-gray-900 disabled:opacity-50 disabled:cursor-not-allowed"
          >
            <Download size={18} />
            导出
          </button>
        </div>
      </div>

      {/* 主内容区域 - 根据是否有消息调整布局 */}
      {!hasVisibleMessages ? (
        /* 无消息时：标题和输入框垂直居中 */
        <div className="flex-1 flex flex-col items-center justify-center px-4 pb-20">
          <h1 className="text-3xl font-semibold text-gray-800 mb-8">有什么可以帮忙的？</h1>
          <div className="w-full max-w-3xl">
            {renderActivePaperChips()}
            <ChatInput
              value={inputValue}
              onChange={setInputValue}
              onSend={handleSendMessage}
              onStop={handleStopGeneration}
              disabled={chatLoading}
              loading={chatLoading}
              images={images}
              onImagesChange={setImages}
            />
            {!apiConfig.api_key && !hasBackendApiKey && (
              <p className="text-xs text-yellow-600 mt-2 text-center">
                ⚠️ 提示：可在设置中配置 API Key
              </p>
            )}
          </div>
        </div>
      ) : (
        /* 有消息时：正常的消息列表 + 底部输入框布局 */
        <>
          <div className="flex-1 bg-white min-h-0 overflow-hidden">
            <MessageList messages={messages} ref={messagesContainerRef} onRetry={handleRetryMessage} />
          </div>
          <div className="p-4 bg-white flex-shrink-0">
            <div className="max-w-3xl mx-auto">
              {renderActivePaperChips()}
              <ChatInput
                value={inputValue}
                onChange={setInputValue}
                onSend={handleSendMessage}
                onStop={handleStopGeneration}
                disabled={chatLoading}
                loading={chatLoading}
                images={images}
                onImagesChange={setImages}
              />
              {!apiConfig.api_key && !hasBackendApiKey && (
                <p className="text-xs text-yellow-600 mt-2">
                  ⚠️ 提示：可在设置中配置 API Key
                </p>
              )}
            </div>
          </div>
        </>
      )}

      {/* 资源面板：展示会话 registry，支持重新激活论文 */}
      <div
        className={`absolute inset-0 z-20 transition ${
          paperPanelOpen ? 'bg-black/20' : 'pointer-events-none'
        }`}
        onClick={() => setPaperPanelOpen(false)}
      />
      <div
        className={`absolute right-0 top-0 h-full w-[360px] max-w-[90vw] bg-white border-l border-gray-200 shadow-xl z-30 transform transition-transform duration-200 ${
          paperPanelOpen ? 'translate-x-0' : 'translate-x-full'
        }`}
      >
        <div className="flex items-center justify-between px-4 py-3 border-b border-gray-200">
          <div>
            <h3 className="text-sm font-semibold text-gray-900">会话资源</h3>
            <p className="text-xs text-gray-500">显示当前会话涉及的全部论文，可手动激活/取消激活</p>
          </div>
          <button
            onClick={() => setPaperPanelOpen(false)}
            className="p-1 rounded hover:bg-gray-100 text-gray-500"
          >
            <X size={16} />
          </button>
        </div>
        <div className="p-4 h-[calc(100%-56px)] overflow-y-auto">
          {!currentConversation && (
            <div className="text-sm text-gray-500">请先发送一条消息创建会话。</div>
          )}
          {currentConversation && paperState.papers.length === 0 && (
            <div className="text-sm text-gray-500">当前会话还没有论文资源。</div>
          )}
          <div className="space-y-3">
            {paperState.papers.map((paper) => (
              <div
                key={paper.canonical_id}
                className={`rounded-xl border bg-white p-3 transition hover:border-gray-300 hover:shadow-sm ${
                  focusedPaperId === paper.canonical_id
                    ? 'paper-focus-animate border-emerald-400 ring-2 ring-emerald-100'
                    : 'border-gray-200'
                }`}
              >
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0 flex-1">
                    <a
                      href={paper.pdf_url}
                      target="_blank"
                      rel="noreferrer"
                      className="text-sm font-semibold text-gray-900 hover:underline break-all"
                    >
                      {paper.filename}
                    </a>
                    <p className="mt-1 text-xs text-gray-500 break-all">
                      {paper.title || `arXiv:${paper.paper_id}`}
                    </p>
                    <p className="mt-2 text-[11px] text-gray-400">arXiv:{paper.paper_id}</p>
                  </div>
                  <div className="flex flex-col items-end gap-1">
                    <label className="inline-flex cursor-pointer items-center">
                      <input
                        type="checkbox"
                        checked={paper.is_active}
                        onChange={(e) => {
                          if (e.target.checked) {
                            handleActivatePaper(paper.canonical_id)
                          } else {
                            handleDeactivatePaper(paper.canonical_id)
                          }
                        }}
                        className="peer sr-only"
                      />
                      <span className="relative h-6 w-11 rounded-full bg-gray-200 transition peer-checked:bg-emerald-500 peer-focus:outline-none peer-focus:ring-2 peer-focus:ring-emerald-200 after:absolute after:left-0.5 after:top-0.5 after:h-5 after:w-5 after:rounded-full after:bg-white after:shadow-sm after:transition-transform peer-checked:after:translate-x-5" />
                    </label>
                    <span className={`text-[11px] ${paper.is_active ? 'text-emerald-600' : 'text-gray-400'}`}>
                      {paper.is_active ? '已激活' : '未激活'}
                    </span>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* 系统提示词面板 - 方案A：右侧抽屉 */}
      <div
        className={`absolute inset-0 z-30 transition ${
          promptPanelOpen ? 'bg-black/20' : 'pointer-events-none'
        }`}
        onClick={() => setPromptPanelOpen(false)}
      />
      <div
        className={`absolute right-0 top-0 h-full w-[360px] max-w-[90vw] bg-white border-l border-gray-200 shadow-xl z-40 transform transition-transform duration-200 ${
          promptPanelOpen ? 'translate-x-0' : 'translate-x-full'
        }`}
      >
        <div className="flex items-center justify-between px-4 py-3 border-b border-gray-200">
          <div>
            <h3 className="text-sm font-semibold text-gray-900">系统提示词</h3>
            <p className="text-xs text-gray-500">
              {currentTool ? '提示词广场（只读）' : '仅作用于当前会话'}
            </p>
          </div>
          <button
            onClick={() => setPromptPanelOpen(false)}
            className="p-1 rounded hover:bg-gray-100 text-gray-500"
          >
            <X size={16} />
          </button>
        </div>
        <div className="p-4 flex flex-col gap-3 h-[calc(100%-48px)]">
          <textarea
            value={systemPromptDraft}
            onChange={(e) => setSystemPromptDraft(e.target.value)}
            readOnly={!!currentTool}
            placeholder={currentTool ? '该工具未设置系统提示词' : '输入系统提示词...'}
            className={`flex-1 w-full rounded-lg border px-3 py-2 text-sm leading-6 resize-none focus:outline-none ${
              currentTool
                ? 'border-gray-200 bg-gray-50 text-gray-700'
                : 'border-gray-200 bg-white text-gray-900 focus:ring-2 focus:ring-gray-200'
            }`}
          />
          <div className="flex items-center justify-between">
            <span className="text-xs text-gray-500">
              {currentTool ? '提示词来源：提示词广场' : '未设置时使用默认系统提示词'}
            </span>
            <div className="flex items-center gap-2">
              <button
                onClick={handleCopySystemPrompt}
                className="flex items-center gap-1 px-3 py-1.5 text-xs rounded-md border border-gray-200 text-gray-600 hover:bg-gray-50"
              >
                <Copy size={14} />
                复制
              </button>
              {!currentTool && (
                <button
                  onClick={handleSaveSystemPrompt}
                  disabled={promptSaving}
                  className="px-3 py-1.5 text-xs rounded-md bg-gray-900 text-white hover:bg-gray-800 disabled:opacity-60"
                >
                  {promptSaving ? '保存中...' : '保存'}
                </button>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}

export default ChatWindow
