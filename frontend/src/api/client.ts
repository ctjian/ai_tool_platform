import axios from 'axios'
import { Category, Tool, Conversation, Message, ChatRequest } from '../types/api'

const API_BASE = '/api/v1'

const api = axios.create({
  baseURL: API_BASE,
  timeout: 30000,
})

export const apiClient = {
  // 分类相关
  getCategories: () => api.get<{ categories: Category[] }>('/categories'),
  
  // 工具相关
  getTools: (categoryId?: string) => 
    api.get<{ tools: Tool[] }>('/tools', { params: { category_id: categoryId } }),
  getTool: (toolId: string) => api.get<Tool>(`/tools/${toolId}`),
  
  // 会话相关
  createConversation: (toolId: string | null, title: string) =>
    api.post<Conversation>('/conversations', { tool_id: toolId, title }),
  getConversations: (toolId?: string) => {
    const params: { tool_id?: string } = {}
    if (toolId) {
      params.tool_id = toolId
    }
    return api.get<{ conversations: Conversation[] }>(`/conversations`, { params })
  },
  getConversation: (conversationId: string) =>
    api.get<Conversation>(`/conversations/${conversationId}`),
  updateConversation: (conversationId: string, data: { title: string }) =>
    api.put(`/conversations/${conversationId}`, data),
  deleteConversation: (conversationId: string) =>
    api.delete(`/conversations/${conversationId}`),
  exportConversation: (conversationId: string) =>
    api.get<{ markdown: string }>(`/conversations/${conversationId}/export`),
  generateConversationTitle: (conversationId: string, apiConfig?: any) =>
    api.post<{ success: boolean; title: string; conversation_id: string }>(
      `/conversations/${conversationId}/generate-title`,
      apiConfig ? { api_config: apiConfig } : {}
    ),
  
  // 聊天相关 - 使用fetch处理SSE流式响应
  chat: async (data: ChatRequest) => {
    const response = await fetch(`${API_BASE}/chat/stream`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(data),
    })
    
    if (!response.ok) {
      throw new Error(`HTTP error! status: ${response.status}`)
    }
    
    return response
  },
  
  // 处理SSE流式响应
  async *readStream(response: Response) {
    const reader = response.body?.getReader()
    if (!reader) return
    
    const decoder = new TextDecoder()
    let buffer = ''
    
    try {
      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        
        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split('\n')
        
        // 处理除最后一行外的所有完整行
        for (let i = 0; i < lines.length - 1; i++) {
          const line = lines[i]
          
          if (line.startsWith('event: ')) {
            const event = line.substring(7)
            const dataLine = lines[++i]
            
            if (dataLine?.startsWith('data: ')) {
              const jsonStr = dataLine.substring(6)
              try {
                const data = JSON.parse(jsonStr)
                yield { event, data }
              } catch (e) {
                // 非JSON数据，直接返回
                yield { event, data: jsonStr }
              }
            }
          }
        }
        
        // 保留未完成的行
        buffer = lines[lines.length - 1]
      }
      
      // 处理最后一行
      if (buffer.trim()) {
        if (buffer.startsWith('event: ')) {
          const event = buffer.substring(7)
          yield { event }
        }
      }
    } finally {
      reader.releaseLock()
    }
  },
  
  stopChat: (conversationId: string) =>
    api.post(`/chat/stop`, { conversation_id: conversationId }),
  
  // 配置相关
  getDefaultConfig: () =>
    api.get<{
      has_api_key: boolean
      base_url: string
      models: string[]
      model_groups: { name: string; models: string[] }[]
    }>('/config/default'),
  getConfig: () => api.get<Record<string, any>>('/config'),
  updateConfig: (config: Record<string, any>) =>
    api.put('/config', config),
  testOpenAIConnection: (data: { api_key: string; base_url: string; model: string }) =>
    api.post('/config/test', data),

  // 自定义工具示例
  runCustomToolDemo: (value: number) =>
    api.post('/custom-tools/demo', { value }),

  runBibLookup: (payload: {
    title: string
    shorten: boolean
    remove_fields: string[]
    max_candidates: number
  }) =>
    api.post('/custom-tools/bib-lookup', payload),
}

export default apiClient
