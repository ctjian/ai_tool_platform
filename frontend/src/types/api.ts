// API 类型定义
// Review note:
// - 新增 ConversationPapersState/ConversationPaperItem，前端用于管理会话论文 registry + active 状态。
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
  extra?: any
  thinking_collapsed?: boolean
  thinking_done?: boolean
  created_at: string
}

export interface Conversation {
  id: string
  tool_id: string | null
  title: string
  extra?: any
  messages: Message[]
  created_at: string
  updated_at: string
}

export interface ConversationPaperItem {
  canonical_id: string
  paper_id: string
  filename: string
  pdf_url: string
  title?: string
  safe_id?: string
  source_type?: 'arxiv' | 'upload_pdf' | string
  origin_name?: string
  last_seen_at?: string
  is_active: boolean
}

export interface ConversationPapersState {
  active_ids: string[]
  papers: ConversationPaperItem[]
}

export interface NotebookNote {
  id: string
  title: string
  path: string
  tags: string[]
  updated_at?: string
  summary?: string
}

export interface NotebookSourceHit {
  source_id: string
  note_id: string
  title: string
  path: string
  tags: string[]
  snippet: string
  score: number
}

export interface NotebookQaRequest {
  query: string
  model?: string
  api_key?: string
  base_url?: string
}

export interface ArxivTranslateCreateRequest {
  input_text: string
  api_key?: string
  base_url?: string
  model?: string
  target_language?: string
  extra_prompt?: string
  allow_cache?: boolean
  concurrency?: number
}

export interface ArxivTranslateStep {
  step_id: string
  key: string
  status: 'running' | 'done' | 'error' | string
  message: string
  at: string
  elapsed_ms?: number
}

export interface ArxivTranslateArtifact {
  name: string
  path: string
  url: string
  size_bytes: number
}

export interface ArxivTranslateJob {
  job_id: string
  status: 'queued' | 'running' | 'succeeded' | 'failed' | 'cancelled' | string
  input_text: string
  paper_id?: string
  canonical_id?: string
  created_at: string
  updated_at: string
  error?: string
  steps: ArxivTranslateStep[]
  artifacts: ArxivTranslateArtifact[]
  meta: Record<string, any>
}

export interface ArxivTranslateHistoryItem {
  job_id: string
  status: string
  input_text?: string
  paper_id?: string
  canonical_id?: string
  created_at: string
  updated_at: string
  task_name: string
  paper_title?: string
  original_pdf_url?: string
  translated_pdf_url?: string
  artifacts: ArxivTranslateArtifact[]
}

export interface ArxivTranslateHistoryResponse {
  items: ArxivTranslateHistoryItem[]
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
