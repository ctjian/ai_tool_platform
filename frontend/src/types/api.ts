// API 类型定义
export interface Category {
  id: string
  name: string
  icon: string
  description: string
  order: number
  created_at: string
  updated_at: string
}

export interface Tool {
  id: string
  name: string
  icon: string
  icon_type: 'emoji' | 'image'
  category_id: string
  description: string
  system_prompt: string
  created_at: string
  updated_at: string
}

export interface Message {
  id: string
  conversation_id: string
  role: 'user' | 'assistant' | 'system'
  content: string
  images?: string[]
  retry_versions?: string | string[] // 重试版本列表（之前的回复）- JSON字符串或数组
  cost_meta?: any
  thinking?: string
  thinking_collapsed?: boolean
  created_at: string
}

export interface Conversation {
  id: string
  tool_id: string | null
  title: string
  messages: Message[]
  created_at: string
  updated_at: string
}

export interface ChatRequest {
  conversation_id: string
  tool_id: string | null
  message: string
    images?: string[]
  api_config: {
    api_key: string
    base_url?: string
    model?: string
    temperature?: number
    max_tokens?: number
    top_p?: number
    frequency_penalty?: number
    presence_penalty?: number
  }
  context_rounds?: number
  retry_message_id?: string
  selected_versions?: Record<string, number>
}
