// Review note:
// - 输入框上方展示 active papers（可打开 PDF，可单独 x 取消激活）。
// - 右侧资源面板展示会话 registry，可重新激活被误删的 paper。
import { useState, useRef, useEffect, useMemo, useCallback } from 'react'
import { useAppStore } from '../store/app'
import apiClient from '../api/client'
import MessageList from './MessageList'
import ChatInput from './ChatInput'
import { Plus, Download, ChevronDown, Check, FileText, X, Copy, AlertCircle, Library, Trash2 } from 'lucide-react'
import { addToast } from './ui'
import { ConversationPapersState, Message, PaperSection, RoundPromptTrace } from '../types/api'

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

const DEFAULT_PDF_ONLY_PROMPT = '请总结该文档核心内容'

const DEFAULT_SYSTEM_PROMPT = `You are a playful and imaginative AI that's enhanced for creativity and fun. Tastefully use metaphors, narrative, analogies, humor, portmanteaus, neologisms, imagery, irony and other literary devices in your responses as context demands. Avoid cliches and direct similes. You often embellish responses with creative and unusual emojis. Do not use corny, awkward, or mawkish expressions. Avoid ungrounded or sycophantic flattery. Above all, your responses should be fun and delightful unless the subject is sad or serious. Your first duty is to contextually satisfy the prompt and the job to be done, and you fulfill that through the joyful exploration of ideas. DO NOT automatically write user-requested written artifacts (e.g. emails, letters, code comments, texts, social media posts, resumes, etc.) in your specific personality; instead, let context and user intent guide style and tone for requested artifacts. NEVER use variations of "aah," "ah," "ahhh," "ooo," "ooh," or "ohhh" at the beginning of your responses. DO NOT use em dashes. DO NOT use the words "mischief" or "mischievious" in responses.

## Additional Instruction

Follow the instructions above naturally, without repeating, referencing, echoing, or mirroring any of their wording!
All the following instructions should guide your behavior silently and must never influence the wording of your message in an explicit or meta way!`

const getSystemPromptFromMessages = (msgs: Message[]): string => {
  for (let i = msgs.length - 1; i >= 0; i--) {
    if (msgs[i].role === 'system') {
      const content = (msgs[i].content || '').trim()
      if (content) return msgs[i].content
    }
  }
  return ''
}

const getRoundPromptDisplayMessages = (trace: any): any[] => {
  if (!trace || !Array.isArray(trace.messages)) return []
  return [...trace.messages].sort((a: any, b: any) => {
    const ai = Number(a?.index || 0)
    const bi = Number(b?.index || 0)
    return ai - bi
  })
}

const formatRoundPromptText = (trace: any): string => {
  const displayMessages = getRoundPromptDisplayMessages(trace)
  if (!trace || displayMessages.length === 0) return ''
  const model = trace.model ? `模型: ${trace.model}` : ''
  const tool = trace.tool_id ? `工具: ${trace.tool_id}` : '工具: 通用聊天'
  const rounds = `上下文轮数: ${trace.context_rounds ?? '默认'}`
  const header = [model, tool, rounds].filter(Boolean).join('\n')
  const body = displayMessages
    .map((m: any) => {
      const role = String(m?.role || '')
      const content = String(m?.content || '')
      return `## ${role}\n${content}`
    })
    .join('\n\n---\n\n')
  return `${header}\n\n${body}`.trim()
}

const hasRoundPrompt = (message: Message | null | undefined): boolean =>
  Boolean(message?.has_round_prompt)

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
  const [pdfFiles, setPdfFiles] = useState<PdfFile[]>([])
  const [isStreaming, setIsStreaming] = useState(false)
  const [isModelMenuOpen, setIsModelMenuOpen] = useState(false)
  const [isThinkingMenuOpen, setIsThinkingMenuOpen] = useState(false)
  const [promptPanelOpen, setPromptPanelOpen] = useState(false)
  const [paperPanelOpen, setPaperPanelOpen] = useState(false)
  const [roundPromptPanelOpen, setRoundPromptPanelOpen] = useState(false)
  const [selectedRoundPrompt, setSelectedRoundPrompt] = useState<RoundPromptTrace | null>(null)
  const [selectedRoundPromptMessageId, setSelectedRoundPromptMessageId] = useState<string | null>(null)
  const [selectedRoundPromptLoading, setSelectedRoundPromptLoading] = useState(false)
  const [roundPromptCache, setRoundPromptCache] = useState<Record<string, RoundPromptTrace>>({})
  const [focusedPaperId, setFocusedPaperId] = useState<string | null>(null)
  const [systemPromptDraft, setSystemPromptDraft] = useState('')
  const [promptSaving, setPromptSaving] = useState(false)
  const [paperState, setPaperState] = useState<ConversationPapersState>({
    active_ids: [],
    papers: [],
  })
  const [paperSections, setPaperSections] = useState<Record<string, { ready: boolean; sections: PaperSection[] }>>({})
  const [paperSectionsOpen, setPaperSectionsOpen] = useState<Record<string, boolean>>({})
  const [paperSectionsLoading, setPaperSectionsLoading] = useState<Record<string, boolean>>({})
  const [selectedVendor, setSelectedVendor] = useState<string>('')
  const [thinkingSetting, setThinkingSetting] = useState(() => {
    return localStorage.getItem('modelThinkingSetting') || 'none'
  })
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

  const normalizeThinkingSetting = (value: string) => {
    const trimmed = (value || '').trim()
    if (!trimmed) return ''
    const withoutLeading = trimmed.startsWith('(') ? trimmed.slice(1) : trimmed
    const withoutTrailing = withoutLeading.endsWith(')') ? withoutLeading.slice(0, -1) : withoutLeading
    return withoutTrailing.trim()
  }

  const buildModelWithThinking = (model: string) => {
    const normalized = normalizeThinkingSetting(thinkingSetting)
    if (!normalized) return model
    return `${model}(${normalized})`
  }

  const thinkingOptions = [
    { value: 'none', label: '关闭' },
    { value: '', label: '默认', hint: '不强制，由模型默认策略决定' },
    { value: 'auto', label: 'auto', hint: '上游自动分配思考预算' },
    { value: 'low', label: 'low' },
    { value: 'medium', label: 'medium' },
    { value: 'high', label: 'high' },
    { value: 'xhigh', label: 'xhigh' },
  ]
  const displayModelLabel = apiConfig.model
  const thinkingLabel = thinkingOptions.find((opt) => opt.value === thinkingSetting)?.label || '默认'
  const lastScrollTopRef = useRef(0)
  const isProgrammaticScrollRef = useRef(false)
  const abortControllerRef = useRef<AbortController | null>(null)
  const sendMessageRef = useRef<
    | ((
        messageContent: string,
        imageDataList: string[],
        pdfFileList: PdfFile[],
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

  const loadPaperSections = useCallback(async (canonicalId: string) => {
    if (!currentConversation?.id) return
    if (paperSections[canonicalId]) return
    if (paperSectionsLoading[canonicalId]) return
    setPaperSectionsLoading((prev) => ({ ...prev, [canonicalId]: true }))
    try {
      const res = await apiClient.getConversationPaperSections(currentConversation.id, canonicalId)
      const payload = res.data || { ready: false, sections: [] }
      setPaperSections((prev) => ({
        ...prev,
        [canonicalId]: {
          ready: Boolean(payload.ready),
          sections: Array.isArray(payload.sections) ? payload.sections : [],
        },
      }))
    } catch (error) {
      console.error('Failed to load paper sections:', error)
      addToast('加载章节失败', 'error')
    } finally {
      setPaperSectionsLoading((prev) => ({ ...prev, [canonicalId]: false }))
    }
  }, [currentConversation?.id, paperSections, paperSectionsLoading])

  const handleToggleSections = useCallback((canonicalId: string) => {
    setPaperSectionsOpen((prev) => {
      const next = !prev[canonicalId]
      return { ...prev, [canonicalId]: next }
    })
    if (!paperSections[canonicalId]) {
      void loadPaperSections(canonicalId)
    }
  }, [paperSections, loadPaperSections])

  const handleSectionSelectionChange = useCallback(async (
    canonicalId: string,
    sectionId: string,
    checked: boolean
  ) => {
    if (!currentConversation?.id) return
    const paper = paperState.papers.find((p) => p.canonical_id === canonicalId)
    if (!paper) return
    const current = new Set(paper.section_filter?.section_ids || [])
    if (checked) {
      current.add(sectionId)
    } else {
      current.delete(sectionId)
    }
    try {
      const res = await apiClient.updateConversationPaperSectionFilter(
        currentConversation.id,
        canonicalId,
        Array.from(current)
      )
      setPaperState(res.data || { active_ids: [], papers: [] })
    } catch (error) {
      console.error('Failed to update section filter:', error)
      addToast('章节筛选更新失败', 'error')
    }
  }, [currentConversation?.id, paperState.papers])

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

  const handleDeletePaper = useCallback(async (canonicalId: string) => {
    if (!currentConversation?.id) return
    if (!confirm('确定要删除该资源及其本地文件吗？')) return
    try {
      const res = await apiClient.deleteConversationPaper(currentConversation.id, canonicalId)
      setPaperState(res.data || { active_ids: [], papers: [] })
      setFocusedPaperId((prev) => (prev === canonicalId ? null : prev))
      addToast('资源已删除', 'success')
    } catch (error) {
      console.error('Failed to delete paper resource:', error)
      addToast('删除资源失败', 'error')
    }
  }, [currentConversation?.id])

  useEffect(() => {
    isStreamingRef.current = isStreaming
  }, [isStreaming])

  useEffect(() => {
    setPaperSections({})
    setPaperSectionsOpen({})
    setPaperSectionsLoading({})
  }, [currentConversation?.id])

  useEffect(() => {
    setRoundPromptPanelOpen(false)
    setSelectedRoundPrompt(null)
    setSelectedRoundPromptMessageId(null)
    setSelectedRoundPromptLoading(false)
    setRoundPromptCache({})
  }, [currentConversation?.id])

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

  const systemPromptSeed = useMemo(() => {
    if (currentTool) {
      return currentTool.system_prompt || ''
    }
    const fromMessages = getSystemPromptFromMessages(messages)
    return fromMessages || DEFAULT_SYSTEM_PROMPT
  }, [
    currentTool,
    currentConversation?.id,
    messages.length,
  ])

  useEffect(() => {
    if (promptPanelOpen) return
    setSystemPromptDraft(systemPromptSeed)
  }, [promptPanelOpen, systemPromptSeed])


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
        autoScrollPausedRef.current = false
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

  const handleOpenRoundPrompt = useCallback(async (msg: Message) => {
    if (!currentConversation?.id) return
    if (!hasRoundPrompt(msg)) {
      addToast('该轮未记录提示词快照', 'warning')
      return
    }
    setPromptPanelOpen(false)
    setPaperPanelOpen(false)
    setSelectedRoundPromptMessageId(msg.id)
    setRoundPromptPanelOpen(true)
    const cached = roundPromptCache[msg.id]
    if (cached) {
      setSelectedRoundPrompt(cached)
      setSelectedRoundPromptLoading(false)
      return
    }
    setSelectedRoundPrompt(null)
    setSelectedRoundPromptLoading(true)
    try {
      const res = await apiClient.getMessageRoundPrompt(currentConversation.id, msg.id)
      const payload = res.data?.round_prompt
      const hasMessages = Array.isArray(payload?.messages) && payload.messages.length > 0
      if (!hasMessages || !payload) {
        setSelectedRoundPrompt(null)
        addToast('该轮未记录提示词快照', 'warning')
        return
      }
      setRoundPromptCache((prev) => ({ ...prev, [msg.id]: payload }))
      setSelectedRoundPrompt(payload)
    } catch (error) {
      console.error('Failed to load round prompt:', error)
      setSelectedRoundPrompt(null)
      addToast('加载本轮提示词失败', 'error')
    } finally {
      setSelectedRoundPromptLoading(false)
    }
  }, [currentConversation?.id, roundPromptCache])

  const handleCopyRoundPrompt = async () => {
    if (!selectedRoundPrompt) return
    try {
      const text = formatRoundPromptText(selectedRoundPrompt)
      if (!text) {
        addToast('该轮提示词为空', 'warning')
        return
      }
      await navigator.clipboard.writeText(text)
      addToast('已复制本轮提示词', 'success')
    } catch (error) {
      console.error('Failed to copy round prompt:', error)
      addToast('复制失败', 'error')
    }
  }

  const roundPromptDisplayMessages = useMemo(
    () => getRoundPromptDisplayMessages(selectedRoundPrompt),
    [selectedRoundPrompt]
  )

  const sendMessageWithPayload = async (
    messageContent: string,
    imageDataList: string[],
    pdfFileList: PdfFile[],
    options?: { skipInputReset?: boolean; autoTitle?: boolean; retryMessageId?: string }
  ) => {
    if ((!messageContent.trim() && imageDataList.length === 0 && pdfFileList.length === 0) || chatLoading) return
    
    // 检查是否有 API Key（后端）
    if (!hasBackendApiKey) {
      addToast('请先在后端环境变量中配置 API Key', 'warning')
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
        setPdfFiles([])
      }

      if (pdfFileList.length > 0) {
        const uploadRes = await apiClient.uploadConversationPdfFiles(
          conversationId,
          pdfFileList.map((item) => item.file)
        )
        setPaperState(uploadRes.data || { active_ids: [], papers: [] })
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
          api_key: '',
          base_url: '',
          model: buildModelWithThinking(apiConfig.model),
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
            if (!firstTokenReceived) {
              next.thinking_collapsed = false
            }
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
      const stopStreamingUi = () => {
        flushBuffers(true)
        pendingContent = ''
        pendingThinking = ''
        stopFlush()
        setIsStreaming(false)
        setChatLoading(false)
      }
      const upsertCompleteAssistantMessage = (completeMessage: any) => {
        setMessages((msgs) => {
          const candidateIds = [
            String(completeMessage?.id || ''),
            String(assistantMessageId || ''),
            String(waitingMessageId || ''),
          ].filter(Boolean)

          let msgIdx = -1
          for (const id of candidateIds) {
            msgIdx = msgs.findIndex((m) => m.id === id)
            if (msgIdx >= 0) break
          }
          if (msgIdx < 0) {
            const lastAssistantReverseIdx = [...msgs].reverse().findIndex((m) => m.role === 'assistant')
            if (lastAssistantReverseIdx >= 0) {
              msgIdx = msgs.length - 1 - lastAssistantReverseIdx
            }
          }
          if (msgIdx < 0) return msgs

          const updatedMsgs = [...msgs]
          const prev = updatedMsgs[msgIdx] as any
          updatedMsgs[msgIdx] = {
            ...completeMessage,
            thinking_collapsed: prev?.thinking_collapsed ?? (completeMessage.thinking ? true : undefined),
            thinking_done: true,
          }
          return updatedMsgs
        })
        const persistedId = String(completeMessage?.id || assistantMessageId || '')
        if (persistedId) {
          setVersionIndices({ ...versionIndices, [persistedId]: 0 })
        }
      }
      const ensureAssistantMessageId = () => {
        if (!assistantMessageId) return
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
      const markAssistantThinkingDone = () => {
        if (!assistantMessageId) return
        setMessages((msgs) =>
          msgs.map((m) =>
            m.id === assistantMessageId ? { ...m, thinking_done: true } : m
          )
        )
      }
      const finalizeAssistantTerminal = (
        completeMessage?: any,
        options?: { ensureAssistantId?: boolean }
      ) => {
        stopStreamingUi()
        if (completeMessage) {
          upsertCompleteAssistantMessage(completeMessage)
        } else if (options?.ensureAssistantId) {
          ensureAssistantMessageId()
        }
        clearWaitingMessage()
        markAssistantThinkingDone()
      }
      const syncConversationMessagesFromServer = async (expectedAssistantId?: string) => {
        if (!conversationId) return
        for (let attempt = 0; attempt < 2; attempt += 1) {
          try {
            const res = await apiClient.getConversation(conversationId)
            const serverMessages = res.data?.messages || []
            setMessages((prev) => {
              const uiStateById = new Map(
                prev.map((m: any) => [
                  m.id,
                  {
                    thinking_collapsed: m.thinking_collapsed,
                  },
                ])
              )
              return serverMessages.map((m: any) => {
                const ui = uiStateById.get(m.id)
                return {
                  ...m,
                  thinking_collapsed:
                    ui?.thinking_collapsed ?? (m.thinking ? true : undefined),
                  thinking_done: true,
                }
              })
            })

            if (!expectedAssistantId) return
            const expected = serverMessages.find((m: any) => m.id === expectedAssistantId)
            if (hasRoundPrompt(expected)) {
              return
            }
          } catch (error) {
            console.error('Failed to sync conversation messages from server:', error)
            return
          }
          await new Promise((resolve) => setTimeout(resolve, 120))
        }
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
                const waitingMsg = waitingMessageId
                  ? msgs.find((m) => m.id === waitingMessageId)
                  : null
                const waitingExtra =
                  waitingMsg && typeof (waitingMsg as any).extra === 'object'
                    ? { ...(waitingMsg as any).extra }
                    : undefined
                const filtered = waitingMessageId ? msgs.filter(m => m.id !== waitingMessageId) : msgs
                return [...filtered, { ...initialMessage, extra: waitingExtra }]
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
          const completeMessage =
            data && typeof data === 'object' && 'message' in data
              ? (data as any).message
              : undefined
          finalizeAssistantTerminal(completeMessage, { ensureAssistantId: true })
          await syncConversationMessagesFromServer(String(completeMessage?.id || ''))
          break
        } else if (event === 'stopped') {
          const completeMessage =
            data && typeof data === 'object' && 'message' in data
              ? (data as any).message
              : undefined
          finalizeAssistantTerminal(completeMessage, { ensureAssistantId: true })
          await syncConversationMessagesFromServer(String(completeMessage?.id || ''))
          break
        } else if (event === 'error') {
          // 错误事件
          if (data && typeof data === 'object' && 'error' in data) {
            throw new Error((data as any).error)
          }
          finalizeAssistantTerminal(undefined, { ensureAssistantId: false })
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
          api_key: '',
          base_url: '',
          model: buildModelWithThinking(apiConfig.model),
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
    if ((!inputValue.trim() && images.length === 0 && pdfFiles.length === 0) || chatLoading) return
    if (!hasBackendApiKey) {
      addToast('请先在后端环境变量中配置 API Key', 'warning')
      return
    }

    const isFirstMessage = !currentConversation || messages.length === 0

    // 转换图片为 base64
    const imageDataList: string[] = []
    for (const img of images) {
      const base64 = await fileToBase64(img.file)
      imageDataList.push(base64)
    }

    const finalMessage = inputValue.trim()
      ? inputValue
      : (pdfFiles.length > 0 ? DEFAULT_PDF_ONLY_PROMPT : inputValue)

    await sendMessageWithPayload(finalMessage, imageDataList, pdfFiles, {
      skipInputReset: false,
      autoTitle: isFirstMessage,
    })
  }

  const handleRetryMessage = useCallback(async (assistantMessageId: string) => {
    if (chatLoading) return
    const latestAssistant = [...messages].reverse().find(
      (m) => m.role === 'assistant' && Boolean((m.content || '').trim()) && m.content !== '__waiting__'
    )
    if (!latestAssistant || latestAssistant.id !== assistantMessageId) return
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
    await sendMessageRef.current?.(userMsg.content, userMsg.images || [], [], {
      skipInputReset: true,
      autoTitle: false,
      retryMessageId: assistantMessageId,  // 传递要替换的消息ID
    })
  }, [messages, chatLoading, versionIndices])

  const handleSubmitUserEdit = useCallback(async (payload: {
    userMessageId: string
    assistantMessageId: string
    content: string
  }) => {
    if (chatLoading) return
    const { userMessageId, assistantMessageId, content } = payload
    const nextContent = content.trim()
    if (!nextContent) {
      addToast('编辑内容不能为空', 'warning')
      return
    }
    const userMsg = messages.find((m) => m.id === userMessageId && m.role === 'user')
    if (!userMsg) {
      addToast('未找到对应用户消息', 'error')
      return
    }

    // 与重试一致：重置版本、清空目标 assistant，进入等待态
    setVersionIndices({ ...versionIndices, [assistantMessageId]: 0 })
    setMessages((msgs) =>
      msgs.map((m) => {
        if (m.id === userMessageId) {
          return { ...m, content: nextContent }
        }
        if (m.id === assistantMessageId) {
          return {
            ...m,
            content: '__waiting__',
            thinking: '',
            thinking_collapsed: true,
            thinking_done: false,
            cost_meta: null,
            extra: {
              ...(m as any).extra,
              status_steps: [],
            },
          }
        }
        return m
      })
    )

    await sendMessageRef.current?.(nextContent, userMsg.images || [], [], {
      skipInputReset: true,
      autoTitle: false,
      retryMessageId: assistantMessageId,
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
            <div className="flex items-center gap-2">
              <div className="relative inline-block w-[300px]">
                <button
                  className="inline-flex items-center gap-2 px-4 py-2 rounded-full border border-gray-200 bg-gray-50 text-sm text-gray-800 hover:bg-gray-100 transition w-full"
                  onClick={() => setIsModelMenuOpen((v) => !v)}
                >
                  <span className="text-gray-500">选择模型</span>
                  <span className="text-gray-900 font-medium flex-1 text-left truncate">{displayModelLabel}</span>
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
              <div className="relative inline-block w-[180px]">
                <button
                  className="inline-flex items-center gap-2 px-4 py-2 rounded-full border border-gray-200 bg-gray-50 text-sm text-gray-800 hover:bg-gray-100 transition w-full"
                  onClick={() => setIsThinkingMenuOpen((v) => !v)}
                  title="在模型名末尾追加 (值) 来控制思考预算或推理等级"
                >
                  <span className="text-gray-500">思考</span>
                  <span className="text-gray-900 font-medium flex-1 text-left truncate">{thinkingLabel}</span>
                  <ChevronDown size={16} className="text-gray-500" />
                </button>
                {isThinkingMenuOpen && (
                  <>
                    <div
                      className="fixed inset-0 z-40"
                      onClick={() => setIsThinkingMenuOpen(false)}
                    />
                    <div className="absolute top-full mt-2 z-50">
                      <div className="bg-white border border-gray-200 rounded-lg shadow-lg min-w-44">
                        {thinkingOptions.map((opt) => (
                          <button
                            key={opt.value || 'default'}
                            onClick={() => {
                              setThinkingSetting(opt.value)
                              localStorage.setItem('modelThinkingSetting', opt.value)
                              setIsThinkingMenuOpen(false)
                            }}
                            className={`w-full text-left px-4 py-2 text-sm transition flex items-start justify-between ${
                              thinkingSetting === opt.value
                                ? 'bg-gray-100 text-gray-900'
                                : 'text-gray-700 hover:bg-gray-50'
                            }`}
                          >
                            <span className="flex flex-col">
                              <span>{opt.label}</span>
                              {opt.hint && (
                                <span className="text-xs text-gray-500">{opt.hint}</span>
                              )}
                            </span>
                            {thinkingSetting === opt.value && (
                              <Check size={16} className="text-gray-600 mt-0.5" />
                            )}
                          </button>
                        ))}
                      </div>
                    </div>
                  </>
                )}
              </div>
            </div>
          ) : (
            <div className="text-xs text-gray-500">
              未加载模型列表，请确认后端已配置 `OPENAI_BASE_URL` 与 `OPENAI_API_KEY`，并能访问 `/v1/models`
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
              pdfFiles={pdfFiles}
              onPdfFilesChange={setPdfFiles}
            />
              {!hasBackendApiKey && (
                <p className="text-xs text-yellow-600 mt-2 text-center">
                  ⚠️ 提示：请在后端环境变量中配置 API Key
                </p>
              )}
          </div>
        </div>
      ) : (
        /* 有消息时：正常的消息列表 + 底部输入框布局 */
        <>
          <div className="flex-1 bg-white min-h-0 overflow-hidden">
            <MessageList
              messages={messages}
              ref={messagesContainerRef}
              onRetry={handleRetryMessage}
              onOpenRoundPrompt={handleOpenRoundPrompt}
              onSubmitUserEdit={handleSubmitUserEdit}
            />
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
                pdfFiles={pdfFiles}
                onPdfFilesChange={setPdfFiles}
              />
              {!hasBackendApiKey && (
                <p className="text-xs text-yellow-600 mt-2">
                  ⚠️ 提示：请在后端环境变量中配置 API Key
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
            <p className="text-xs text-gray-500">显示当前会话涉及的全部资源，可手动激活/取消激活/删除</p>
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
            {paperState.papers.map((paper) => {
              const sectionInfo = paperSections[paper.canonical_id]
              const sectionsOpen = Boolean(paperSectionsOpen[paper.canonical_id])
              const sectionLoading = Boolean(paperSectionsLoading[paper.canonical_id])
              const selectedSectionIds = new Set(paper.section_filter?.section_ids || [])
              const selectedCount = selectedSectionIds.size

              return (
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
                        {paper.title || (paper.source_type === 'upload_pdf' ? (paper.origin_name || paper.filename) : `arXiv:${paper.paper_id}`)}
                      </p>
                      <p className="mt-2 text-[11px] text-gray-400">
                        {paper.source_type === 'upload_pdf' ? `upload:${paper.paper_id}` : `arXiv:${paper.paper_id}`}
                      </p>
                    </div>
                    <div className="flex flex-col items-end gap-1">
                      <button
                        type="button"
                        onClick={() => handleDeletePaper(paper.canonical_id)}
                        className="inline-flex items-center gap-1 rounded-md border border-gray-200 px-2 py-1 text-[11px] text-gray-600 hover:bg-gray-50 hover:text-gray-800"
                        title="彻底删除资源"
                      >
                        <Trash2 size={12} />
                        删除
                      </button>
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

                  {paper.is_active && (
                    <div className="mt-3 border-t border-gray-100 pt-3">
                      <button
                        type="button"
                        onClick={() => handleToggleSections(paper.canonical_id)}
                        className="text-xs text-gray-600 hover:text-gray-900"
                      >
                        {sectionsOpen ? '收起章节筛选' : '展开章节筛选'}
                      </button>
                      {sectionsOpen && (
                        <div className="mt-2 space-y-2">
                          {sectionLoading && (
                            <div className="text-xs text-gray-400">加载章节中...</div>
                          )}
                          {!sectionLoading && (!sectionInfo?.ready || (sectionInfo.sections || []).length === 0) && (
                            <div className="text-xs text-gray-400">未识别到章节，暂不支持选择。</div>
                          )}
                          {!sectionLoading && sectionInfo?.ready && (sectionInfo.sections || []).length > 0 && (
                            <div className="max-h-48 overflow-y-auto space-y-1">
                              {sectionInfo.sections.map((sec) => {
                                const checked = selectedSectionIds.has(sec.section_id)
                                return (
                                  <label key={sec.section_id} className="flex items-center gap-2 text-xs text-gray-700">
                                    <input
                                      type="checkbox"
                                      checked={checked}
                                      onChange={(e) =>
                                        handleSectionSelectionChange(
                                          paper.canonical_id,
                                          sec.section_id,
                                          e.target.checked
                                        )
                                      }
                                    />
                                    <span className="truncate">{sec.title}</span>
                                  </label>
                                )
                              })}
                            </div>
                          )}
                          {selectedCount > 0 && (
                            <div className="text-[11px] text-emerald-600">
                              已选 {selectedCount} 个章节，回答将跳过检索。
                            </div>
                          )}
                        </div>
                      )}
                    </div>
                  )}
                </div>
              )
            })}
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

      {/* 本轮提示词面板：从 assistant.extra.round_prompt 打开 */}
      <div
        className={`absolute inset-0 z-40 transition ${
          roundPromptPanelOpen ? 'bg-black/20' : 'pointer-events-none'
        }`}
        onClick={() => setRoundPromptPanelOpen(false)}
      />
      <div
        className={`absolute right-0 top-0 h-full w-[520px] max-w-[95vw] bg-white border-l border-gray-200 shadow-xl z-50 transform transition-transform duration-200 ${
          roundPromptPanelOpen ? 'translate-x-0' : 'translate-x-full'
        }`}
      >
        <div className="flex items-center justify-between px-4 py-3 border-b border-gray-200">
          <div>
            <h3 className="text-sm font-semibold text-gray-900">本轮提示词</h3>
            <p className="text-xs text-gray-500">显示该条回复实际发送给模型的消息序列（图片已脱敏）</p>
          </div>
          <button
            onClick={() => setRoundPromptPanelOpen(false)}
            className="p-1 rounded hover:bg-gray-100 text-gray-500"
          >
            <X size={16} />
          </button>
        </div>
        <div className="h-[calc(100%-56px)] overflow-y-auto p-4">
          {selectedRoundPromptLoading ? (
            <div className="text-sm text-gray-500">正在加载本轮提示词...</div>
          ) : !selectedRoundPrompt || roundPromptDisplayMessages.length === 0 ? (
            <div className="text-sm text-gray-500">未找到本轮提示词数据。</div>
          ) : (
            <div className="space-y-3">
              <div className="rounded-lg border border-gray-200 bg-gray-50 px-3 py-2 text-xs text-gray-700">
                <div>消息ID: {selectedRoundPromptMessageId || '-'}</div>
                <div>模型: {selectedRoundPrompt.model || '-'}</div>
                <div>工具: {selectedRoundPrompt.tool_id || '通用聊天'}</div>
                <div>上下文轮数: {selectedRoundPrompt.context_rounds ?? '默认'}</div>
              </div>
              <div className="flex justify-end">
                <button
                  type="button"
                  onClick={handleCopyRoundPrompt}
                  className="flex items-center gap-1 px-3 py-1.5 text-xs rounded-md border border-gray-200 text-gray-600 hover:bg-gray-50"
                >
                  <Copy size={14} />
                  复制全部
                </button>
              </div>
              {roundPromptDisplayMessages.map((item, idx) => (
                <div key={`${item?.index ?? idx}-${item?.role ?? 'role'}`} className="rounded-lg border border-gray-200 bg-white">
                  <div className="border-b border-gray-200 bg-gray-50 px-3 py-2 text-xs font-medium text-gray-700">
                    {idx + 1}. {String(item?.role || '')}
                  </div>
                  <pre className="max-h-[320px] overflow-auto whitespace-pre-wrap break-words px-3 py-3 text-xs leading-6 text-gray-800">
                    {String(item?.content || '')}
                  </pre>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

export default ChatWindow
