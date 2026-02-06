import { useState, useRef, useEffect } from 'react'
import { useAppStore } from '../store/app'
import apiClient from '../api/client'
import MessageList from './MessageList'
import ChatInput from './ChatInput'
import { Plus, Download, Square } from 'lucide-react'
import { addToast } from './ui'

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

function ChatWindow() {
  const {
    currentTool,
    currentConversation,
    messages,
    setMessages,
    setCurrentConversation,
    conversations,
    setConversations,
    apiConfig,
    hasBackendApiKey,
    chatLoading,
    setChatLoading,
    versionIndices,
    setVersionIndices,
  } = useAppStore()

  const [inputValue, setInputValue] = useState('')
  const [images, setImages] = useState<ImageFile[]>([])
  const [isStreaming, setIsStreaming] = useState(false)
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const abortControllerRef = useRef<AbortController | null>(null)

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

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

  // 创建新对话
  const handleNewConversation = async () => {
    if (!currentTool) return

    try {
      const res = await apiClient.createConversation(
        currentTool.id,
        `${currentTool.name} - ${new Date().toLocaleString()}`
      )
      setCurrentConversation(res.data)
      setMessages([])
      setConversations([...conversations, res.data])
    } catch (error) {
      console.error('Failed to create conversation:', error)
    }
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
    if (abortControllerRef.current) {
      abortControllerRef.current.abort()
      setIsStreaming(false)
      setChatLoading(false)
      addToast('已停止生成', 'info')
    }
  }

  const sendMessageWithPayload = async (
    messageContent: string,
    imageDataList: string[],
    options?: { skipInputReset?: boolean; autoTitle?: boolean; retryMessageId?: string }
  ) => {
    if ((!messageContent.trim() && imageDataList.length === 0) || chatLoading || !apiConfig.api_key) return

    // 对于工具对话，需要有currentTool；对于通用对话，不需要
    if (!currentTool && !currentConversation) return

    const shouldAutoTitle = options?.autoTitle ?? false
    const retryMessageId = options?.retryMessageId

    try {
      setChatLoading(true)

      // 如果没有会话，先创建一个
      let conversationId = currentConversation?.id
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
        // 清理图片预览 URL
        images.forEach(img => URL.revokeObjectURL(img.preview))
      }

      // 调用聊天API - 使用完整的API配置
      setIsStreaming(true)
      const response = await apiClient.chat({
        conversation_id: conversationId,
        tool_id: currentTool?.id ?? null,
        message: messageContent,
        images: imageDataList,
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
      })

      // 处理流式SSE响应 - 使用缓冲区减少重新渲染
      let assistantMessageId = retryMessageId || Date.now().toString()
      let assistantCreated = !!retryMessageId // 只有重试时才认为已创建（不需要创建新消息）
      let contentBuffer = ''
      const bufferSize = 10 // 每10个token更新一次UI
      let tokenCount = 0
      let newContent = '' // 新的回复内容
      let firstTokenReceived = false // 标记是否接收到第一个token

      for await (const { event, data } of apiClient.readStream(response)) {
        if (event === 'start') {
          // 开始事件，包含message_id
          continue
        } else if (event === 'token') {
          // token 事件 - 来自后端的实际内容
          if (data && typeof data === 'object' && 'content' in data) {
            const token = (data as any).content
            contentBuffer += token
            newContent += token
            tokenCount++

            // 第一次收到内容时，创建或更新助手消息
            if (!assistantCreated) {
              const initialMessage = {
                id: assistantMessageId,
                conversation_id: conversationId,
                role: 'assistant' as const,
                content: contentBuffer,
                created_at: new Date().toISOString(),
              }
              setMessages((msgs) => [...msgs, initialMessage])
              assistantCreated = true
              firstTokenReceived = true
              contentBuffer = ''
              tokenCount = 0
            } else if (!firstTokenReceived && retryMessageId) {
              // 重试时第一次收到token，清空旧内容，只保留新内容
              firstTokenReceived = true
              setMessages((msgs) => {
                const msgIdx = msgs.findIndex(m => m.id === assistantMessageId)
                if (msgIdx >= 0) {
                  const updatedMsgs = [...msgs]
                  updatedMsgs[msgIdx] = {
                    ...updatedMsgs[msgIdx],
                    content: contentBuffer, // 替换而不是追加
                  }
                  return updatedMsgs
                }
                return msgs
              })
              contentBuffer = ''
              tokenCount = 0
            } else if (tokenCount >= bufferSize) {
              // 缓冲区满了，更新消息
              setMessages((msgs) => {
                const msgIdx = msgs.findIndex(m => m.id === assistantMessageId)
                if (msgIdx >= 0) {
                  const updatedMsgs = [...msgs]
                  updatedMsgs[msgIdx] = {
                    ...updatedMsgs[msgIdx],
                    content: updatedMsgs[msgIdx].content + contentBuffer,
                  }
                  return updatedMsgs
                }
                return msgs
              })
              contentBuffer = ''
              tokenCount = 0
            }
          }
        } else if (event === 'done') {
          // 最后的缓冲内容
          if (contentBuffer && assistantCreated) {
            setMessages((msgs) => {
              const msgIdx = msgs.findIndex(m => m.id === assistantMessageId)
              if (msgIdx >= 0) {
                const updatedMsgs = [...msgs]
                updatedMsgs[msgIdx] = {
                  ...updatedMsgs[msgIdx],
                  content: updatedMsgs[msgIdx].content + contentBuffer,
                }
                return updatedMsgs
              }
              return msgs
            })
          }
          
          // 如果后端返回了完整的消息对象（包含retry_versions），用它更新消息
          if (data && typeof data === 'object' && 'message' in data) {
            const completeMessage = (data as any).message
            setMessages((msgs) => {
              const msgIdx = msgs.findIndex(m => m.id === assistantMessageId)
              if (msgIdx >= 0) {
                const updatedMsgs = [...msgs]
                updatedMsgs[msgIdx] = completeMessage
                return updatedMsgs
              }
              return msgs
            })
            // 收到完整消息后，默认选中最新版本
            setVersionIndices({ ...versionIndices, [assistantMessageId]: 0 })
          }
          
          break
        } else if (event === 'stopped') {
          // 停止事件 - 也需要刷新缓冲区
          if (contentBuffer && assistantCreated) {
            setMessages((msgs) => {
              const msgIdx = msgs.findIndex(m => m.id === assistantMessageId)
              if (msgIdx >= 0) {
                const updatedMsgs = [...msgs]
                updatedMsgs[msgIdx] = {
                  ...updatedMsgs[msgIdx],
                  content: updatedMsgs[msgIdx].content + contentBuffer,
                }
                return updatedMsgs
              }
              return msgs
            })
          }
          break
        } else if (event === 'error') {
          // 错误事件
          if (data && typeof data === 'object' && 'error' in data) {
            throw new Error((data as any).error)
          }
          break
        }
      }

      setIsStreaming(false)

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
    } catch (error) {
      console.error('Failed to send message:', error)
      addToast('发送失败，请重试', 'error')
      setIsStreaming(false) // 确保错误时也停止流式传输状态
    } finally {
      setChatLoading(false)
    }
  }

  // 发送消息
  const handleSendMessage = async () => {
    if ((!inputValue.trim() && images.length === 0) || chatLoading || !apiConfig.api_key) return

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

  const handleRetryMessage = async (assistantMessageId: string) => {
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

    // 发送消息，但标记为重试（会替换而不是新增消息）
    await sendMessageWithPayload(userMsg.content, userMsg.images || [], {
      skipInputReset: true,
      autoTitle: false,
      retryMessageId: assistantMessageId,  // 传递要替换的消息ID
    })
  }

  return (
    <div className="flex-1 flex flex-col bg-white text-gray-900 h-full overflow-hidden">
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
              <span className="text-2xl">💬</span>
              <div>
                <h2 className="font-bold text-gray-900">通用聊天</h2>
                <p className="text-xs text-gray-600">与AI助手直接对话</p>
              </div>
            </>
          )}
        </div>
        <div className="flex items-center gap-2">
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
          {isStreaming && (
            <button
              onClick={handleStopGeneration}
              className="flex items-center gap-2 px-3 py-2 bg-red-500 text-white hover:bg-red-600 rounded-lg transition text-sm"
            >
              <Square size={16} fill="currentColor" />
              停止
            </button>
          )}
        </div>
      </div>

      {/* 主内容区域 - 根据是否有消息调整布局 */}
      {messages.length === 0 ? (
        /* 无消息时：标题和输入框垂直居中 */
        <div className="flex-1 flex flex-col items-center justify-center px-4 pb-20">
          <h1 className="text-3xl font-semibold text-gray-800 mb-8">有什么可以帮忙的？</h1>
          <div className="w-full max-w-3xl">
            <ChatInput
              value={inputValue}
              onChange={setInputValue}
              onSend={handleSendMessage}
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
          <div className="flex-1 overflow-y-auto bg-white">
            <MessageList messages={messages} ref={messagesEndRef} onRetry={handleRetryMessage} />
          </div>
          <div className="p-4 bg-white flex-shrink-0">
            <div className="max-w-3xl mx-auto">
              <ChatInput
                value={inputValue}
                onChange={setInputValue}
                onSend={handleSendMessage}
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
    </div>
  )
}

export default ChatWindow
