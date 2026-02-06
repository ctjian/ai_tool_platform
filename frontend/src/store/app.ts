import { create } from 'zustand'
import { Category, Tool, Conversation, Message } from '../types/api'

interface APIConfig {
  api_key: string
  base_url: string
  model: string
  temperature: number
  max_tokens: number
  top_p: number
  frequency_penalty: number
  presence_penalty: number
}

interface AppState {
  // 数据
  categories: Category[]
  tools: Tool[]
  currentTool: Tool | null
  conversations: Conversation[]
  currentConversation: Conversation | null
  messages: Message[]
  availableModels: string[]
  availableModelGroups: { name: string; models: string[] }[]
  
  // UI状态
  sidebarOpen: boolean
  loading: boolean
  chatLoading: boolean
  apiKey: string
  apiConfig: APIConfig
  hasBackendApiKey: boolean  // 后端是否配置了API Key
  versionIndices: Record<string, number>  // 记录每条消息选中的版本索引
  
  // 操作
  setCategories: (categories: Category[]) => void
  setTools: (tools: Tool[]) => void
  setCurrentTool: (tool: Tool | null) => void
  setConversations: (conversations: Conversation[] | ((prev: Conversation[]) => Conversation[])) => void
  setCurrentConversation: (conversation: Conversation | null) => void
  setMessages: (messages: Message[] | ((prev: Message[]) => Message[])) => void
  setAvailableModels: (models: string[]) => void
  setAvailableModelGroups: (groups: { name: string; models: string[] }[]) => void
  setSidebarOpen: (open: boolean) => void
  setLoading: (loading: boolean) => void
  setChatLoading: (loading: boolean) => void
  setApiKey: (key: string) => void
  setApiConfig: (config: Partial<APIConfig>) => void
  setHasBackendApiKey: (has: boolean) => void
  setVersionIndices: (indices: Record<string, number>) => void
  
  addMessage: (message: Message) => void
  clearMessages: () => void
}

export const useAppStore = create<AppState>((set) => ({
  categories: [],
  tools: [],
  currentTool: null,
  conversations: [],
  currentConversation: null,
  messages: [],
  availableModels: [],
  availableModelGroups: [],
  sidebarOpen: true,
  loading: false,
  chatLoading: false,
  apiKey: localStorage.getItem('apiKey') || '',
  hasBackendApiKey: false,
  apiConfig: {
    api_key: localStorage.getItem('apiKey') || '',
    base_url: localStorage.getItem('apiConfigBaseUrl') || 'https://api.yunwu.ai/v1',
    model: localStorage.getItem('apiConfigModel') || 'gpt-4o-mini',
    temperature: parseFloat(localStorage.getItem('apiConfigTemperature') || '0.7'),
    max_tokens: parseInt(localStorage.getItem('apiConfigMaxTokens') || '2000'),
    top_p: parseFloat(localStorage.getItem('apiConfigTopP') || '1.0'),
    frequency_penalty: parseFloat(localStorage.getItem('apiConfigFrequencyPenalty') || '0.0'),
    presence_penalty: parseFloat(localStorage.getItem('apiConfigPresencePenalty') || '0.0'),
  },
  versionIndices: {},
  
  setCategories: (categories) => set({ categories }),
  setTools: (tools) => set({ tools }),
  setCurrentTool: (tool) => set({ currentTool: tool }),
  setConversations: (conversations) => set((state) => ({
    conversations: typeof conversations === 'function' ? conversations(state.conversations) : conversations
  })),
  setCurrentConversation: (conversation) => set({ currentConversation: conversation }),
  setMessages: (messages) => set((state) => ({
    messages: typeof messages === 'function' ? messages(state.messages) : messages
  })),
  setAvailableModels: (models) => set({ availableModels: models }),
  setAvailableModelGroups: (groups) => set({ availableModelGroups: groups }),
  setSidebarOpen: (open) => set({ sidebarOpen: open }),
  setLoading: (loading) => set({ loading }),
  setChatLoading: (loading) => set({ chatLoading: loading }),
  setApiKey: (key) => {
    if (key) {
      localStorage.setItem('apiKey', key)
    } else {
      localStorage.removeItem('apiKey')
    }
    set({ apiKey: key })
  },
  setApiConfig: (config) => {
    set((state) => {
      const newConfig = { ...state.apiConfig, ...config }
      // 同时保存到 localStorage
      if (config.api_key !== undefined) localStorage.setItem('apiKey', config.api_key)
      if (config.base_url !== undefined) localStorage.setItem('apiConfigBaseUrl', config.base_url)
      if (config.model !== undefined) localStorage.setItem('apiConfigModel', config.model)
      if (config.temperature !== undefined) localStorage.setItem('apiConfigTemperature', String(config.temperature))
      if (config.max_tokens !== undefined) localStorage.setItem('apiConfigMaxTokens', String(config.max_tokens))
      if (config.top_p !== undefined) localStorage.setItem('apiConfigTopP', String(config.top_p))
      if (config.frequency_penalty !== undefined) localStorage.setItem('apiConfigFrequencyPenalty', String(config.frequency_penalty))
      if (config.presence_penalty !== undefined) localStorage.setItem('apiConfigPresencePenalty', String(config.presence_penalty))
      return { apiConfig: newConfig }
    })
  },
  setHasBackendApiKey: (has) => set({ hasBackendApiKey: has }),
  setVersionIndices: (indices) => set({ versionIndices: indices }),
  
  addMessage: (message) => set((state) => ({ 
    messages: [...state.messages, message] 
  })),
  clearMessages: () => set({ messages: [] }),
}))
