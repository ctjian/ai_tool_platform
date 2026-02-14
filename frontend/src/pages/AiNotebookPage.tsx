import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { BookOpen, ExternalLink, Loader2, Plus, Search, Send, X } from 'lucide-react'
import { addToast } from '../components/ui'
import apiClient from '../api/client'
import { useAppStore } from '../store/app'
import MarkdownRenderer from '../components/MarkdownRenderer'

interface NotebookMeta {
  id: string
  title: string
  path: string
  tags: string[]
  updated_at?: string
  summary?: string
}

interface SourceHit {
  source_id: string
  note_id: string
  title: string
  path: string
  tags: string[]
  snippet: string
  score: number
}

const DEFAULT_TAGS = ['全部', '系统运维', '开发排错']

export const AiNotebookPage = () => {
  const { availableModels, availableModelGroups, apiConfig } = useAppStore()
  const [notes, setNotes] = useState<NotebookMeta[]>([])
  const [loading, setLoading] = useState(true)
  const [selectedTag, setSelectedTag] = useState('全部')
  const [searchKeyword, setSearchKeyword] = useState('')
  const [panelMode, setPanelMode] = useState<'list' | 'qa' | 'create'>('list')
  const [selectedNoteId, setSelectedNoteId] = useState<string | null>(null)
  const [previewOpen, setPreviewOpen] = useState(false)
  const [contentById, setContentById] = useState<Record<string, string>>({})
  const [question, setQuestion] = useState('')
  const [asking, setAsking] = useState(false)
  const [qaModel, setQaModel] = useState(apiConfig.model || 'gpt-4o-mini')
  const qaStreamAbortRef = useRef<AbortController | null>(null)
  const [answerMarkdown, setAnswerMarkdown] = useState('')
  const [sourceHits, setSourceHits] = useState<SourceHit[]>([])
  const [newTitle, setNewTitle] = useState('')
  const [newSummary, setNewSummary] = useState('')
  const [newContent, setNewContent] = useState('')
  const [newTagInput, setNewTagInput] = useState('')
  const [newTags, setNewTags] = useState<string[]>([])

  useEffect(() => {
    const loadMeta = async () => {
      try {
        setLoading(true)
        const res = await apiClient.listNotebookNotes()
        const items = Array.isArray(res.data?.notes) ? res.data.notes : []
        setNotes(items)
      } catch (error) {
        console.error('Failed to load notebook index:', error)
        addToast('AI笔记本索引加载失败', 'error')
      } finally {
        setLoading(false)
      }
    }
    loadMeta()
  }, [])

  const ensureNoteContent = useCallback(
    async (note: NotebookMeta): Promise<string> => {
      const cached = contentById[note.id]
      if (typeof cached === 'string') return cached
      const res = await fetch(note.path)
      if (!res.ok) {
        throw new Error(`load note failed: ${res.status}`)
      }
      const text = await res.text()
      setContentById((prev) => ({ ...prev, [note.id]: text }))
      return text
    },
    [contentById]
  )

  const availableTags = useMemo(() => {
    const dynamicTags = new Set<string>()
    notes.forEach((note) => (note.tags || []).forEach((tag) => dynamicTags.add(tag)))
    return [...DEFAULT_TAGS, ...Array.from(dynamicTags).filter((tag) => !DEFAULT_TAGS.includes(tag))]
  }, [notes])

  const createPresetTags = useMemo(() => availableTags.filter((tag) => tag !== '全部'), [availableTags])
  const customCreateTags = useMemo(
    () => newTags.filter((tag) => !createPresetTags.includes(tag)),
    [newTags, createPresetTags]
  )

  const groupedQaModels = useMemo(() => {
    if (availableModelGroups.length > 0) {
      return availableModelGroups
        .map((group) => ({
          name: group.name,
          models: (group.models || []).filter(Boolean),
        }))
        .filter((group) => group.models.length > 0)
    }
    const fallback = (availableModels || []).filter(Boolean)
    return [{ name: '模型', models: fallback.length > 0 ? fallback : ['gpt-4o-mini'] }]
  }, [availableModelGroups, availableModels])

  const qaModelOptions = useMemo(() => {
    const flat: string[] = []
    groupedQaModels.forEach((group) =>
      group.models.forEach((model) => {
        if (!flat.includes(model)) flat.push(model)
      })
    )
    return flat
  }, [groupedQaModels])

  useEffect(() => {
    if (!qaModelOptions.length) return
    if (!qaModelOptions.includes(qaModel)) {
      setQaModel(qaModelOptions[0])
    }
  }, [qaModelOptions, qaModel])

  const filteredNotes = useMemo(() => {
    const key = searchKeyword.trim().toLowerCase()
    return notes.filter((note) => {
      const tagOK = selectedTag === '全部' || (note.tags || []).includes(selectedTag)
      if (!tagOK) return false
      if (!key) return true
      const raw = `${note.title}\n${note.summary || ''}\n${(note.tags || []).join(' ')}`
      return raw.toLowerCase().includes(key)
    })
  }, [notes, selectedTag, searchKeyword])

  const selectedNote = useMemo(
    () => notes.find((note) => note.id === selectedNoteId) || null,
    [notes, selectedNoteId]
  )

  useEffect(() => {
    if (!selectedNote) return
    void ensureNoteContent(selectedNote)
  }, [selectedNote, ensureNoteContent])

  useEffect(() => {
    if (!previewOpen) return
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        setPreviewOpen(false)
      }
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [previewOpen])

  useEffect(() => {
    return () => {
      qaStreamAbortRef.current?.abort()
      qaStreamAbortRef.current = null
    }
  }, [])

  const selectedNoteContent = selectedNote ? contentById[selectedNote.id] || '' : ''

  const handleOpenNote = useCallback(
    async (note: NotebookMeta) => {
      setSelectedNoteId(note.id)
      try {
        await ensureNoteContent(note)
        setPreviewOpen(true)
      } catch (error) {
        console.error('Failed to open note:', error)
        addToast('笔记加载失败', 'error')
      }
    },
    [ensureNoteContent]
  )

  const handleAskQuestion = async () => {
    const query = question.trim()
    if (!query) {
      addToast('请输入问题', 'warning')
      return
    }
    if (!notes.length) {
      addToast('当前没有可检索的笔记', 'warning')
      return
    }

    try {
      setAsking(true)
      setAnswerMarkdown('')
      setSourceHits([])

      qaStreamAbortRef.current?.abort()
      const controller = new AbortController()
      qaStreamAbortRef.current = controller

      const response = await apiClient.notebookQaStream({
        query,
        model: qaModel,
        api_key: apiConfig.api_key || '',
        base_url: apiConfig.base_url || '',
      }, controller.signal)

      let streamTerminated = false
      let streamErrorShown = false

      for await (const { event, data } of apiClient.readStream(response)) {
        if (event === 'status') {
          continue
        }

        if (event === 'token') {
          if (data && typeof data === 'object' && 'content' in data) {
            const token = String((data as any).content || '')
            if (token) {
              setAnswerMarkdown((prev) => prev + token)
            }
          }
          continue
        }

        if (event === 'done') {
          const payloadData = data && typeof data === 'object' ? (data as any) : {}
          const finalAnswer = String(payloadData.answer_markdown || '')
          const finalSources = Array.isArray(payloadData.sources) ? (payloadData.sources as SourceHit[]) : []
          if (finalAnswer) {
            setAnswerMarkdown(finalAnswer)
          }
          setSourceHits(finalSources)
          streamTerminated = true
          break
        }

        if (event === 'error') {
          const errMsg =
            data && typeof data === 'object' && 'error' in data
              ? String((data as any).error || '笔记检索失败')
              : '笔记检索失败'
          addToast(errMsg, 'error')
          streamTerminated = true
          streamErrorShown = true
          break
        }
      }

      if (!streamTerminated) {
        const errMsg = '检索流已中断，请重试'
        if (!streamErrorShown) {
          addToast(errMsg, 'error')
        }
      }
    } catch (error) {
      if ((error as any)?.name === 'AbortError') {
        return
      }
      console.error('Notebook QA failed:', error)
      const detail = (error as any)?.response?.data?.detail || (error as Error)?.message
      addToast(detail || '笔记检索失败', 'error')
    } finally {
      setAsking(false)
      qaStreamAbortRef.current = null
    }
  }

  const appendCreateTag = useCallback((raw: string) => {
    const cleaned = String(raw || '').trim()
    if (!cleaned) return
    const pieces = cleaned
      .split(/[,\s，、]+/)
      .map((item) => item.trim())
      .filter(Boolean)
    if (!pieces.length) return
    setNewTags((prev) => {
      const next = [...prev]
      for (const tag of pieces) {
        if (!next.includes(tag)) next.push(tag)
      }
      return next
    })
  }, [])

  const handleCreateTagKeyDown = (event: React.KeyboardEvent<HTMLInputElement>) => {
    if (event.key !== 'Enter') return
    event.preventDefault()
    appendCreateTag(newTagInput)
    setNewTagInput('')
  }

  const handleCreateNote = async () => {
    const title = newTitle.trim()
    const content = newContent.trim()
    if (!title) {
      addToast('请输入笔记标题', 'warning')
      return
    }
    if (!content) {
      addToast('请输入笔记内容', 'warning')
      return
    }
    try {
      const tags = newTags.length > 0 ? newTags : ['未分类']
      const createRes = await apiClient.createNotebookNote({
        title,
        summary: newSummary.trim(),
        tags,
        content,
      })
      const created = createRes.data
      setNotes((prev) => [created, ...prev.filter((item) => item.id !== created.id)])
      setContentById((prev) => ({ ...prev, [created.id]: content }))
      setSelectedNoteId(null)
      setPreviewOpen(false)
      setPanelMode('list')
      setNewTitle('')
      setNewSummary('')
      setNewContent('')
      setNewTagInput('')
      setNewTags([])
      addToast('笔记已新增', 'success')
    } catch (error) {
      const detail = (error as any)?.response?.data?.detail
      addToast(detail || '新增笔记失败', 'error')
    }
  }

  if (loading) {
    return (
      <div className="flex h-[calc(100vh-120px)] items-center justify-center text-gray-500">
        <Loader2 size={18} className="mr-2 animate-spin" />
        正在加载 AI笔记本...
      </div>
    )
  }

  return (
    <div className="mx-auto max-w-6xl">
      <div className="mb-5">
        <h1 className="text-3xl font-bold text-gray-900">AI笔记本</h1>
        <p className="mt-2 text-sm text-gray-600">
          笔记来源：Markdown 文件 + JSON 元信息。当前支持标签筛选、渲染阅读、库内问答检索（原型）。
        </p>
      </div>

      <section className="flex flex-col rounded-xl border border-gray-200 bg-white">
        <div className="border-b border-gray-200 p-4">
          <h2 className="text-sm font-semibold text-gray-900">笔记工作台</h2>
          <p className="mt-1 text-xs text-gray-500">笔记列表、检索问答、新增笔记整合在一个区域，支持全宽切换。</p>
          <div className="mt-3 inline-flex rounded-lg border border-gray-200 bg-gray-50 p-1">
            <button
              type="button"
              onClick={() => setPanelMode('list')}
              className={`inline-flex items-center gap-1 rounded-md px-3 py-1.5 text-xs transition ${
                panelMode === 'list' ? 'bg-white text-gray-900 shadow-sm' : 'text-gray-600 hover:text-gray-900'
              }`}
            >
              <BookOpen size={12} />
              笔记列表
            </button>
            <button
              type="button"
              onClick={() => setPanelMode('qa')}
              className={`rounded-md px-3 py-1.5 text-xs transition ${
                panelMode === 'qa' ? 'bg-white text-gray-900 shadow-sm' : 'text-gray-600 hover:text-gray-900'
              }`}
            >
              检索问答
            </button>
            <button
              type="button"
              onClick={() => setPanelMode('create')}
              className={`rounded-md px-3 py-1.5 text-xs transition ${
                panelMode === 'create' ? 'bg-white text-gray-900 shadow-sm' : 'text-gray-600 hover:text-gray-900'
              }`}
            >
              新增笔记
            </button>
          </div>
        </div>
        <div className="flex flex-col p-4">
          {panelMode === 'list' && (
            <>
              <div className="relative">
                <Search size={14} className="pointer-events-none absolute left-3 top-1/2 z-10 -translate-y-1/2 text-gray-400" />
                <input
                  value={searchKeyword}
                  onChange={(e) => setSearchKeyword(e.target.value)}
                  placeholder="搜索标题、摘要、标签"
                  className="h-10 w-full rounded-lg border border-gray-200 bg-white pl-9 pr-3 text-sm leading-10 text-gray-800 outline-none placeholder:text-gray-400 focus:border-gray-300"
                />
              </div>
              <div className="mt-3 flex flex-wrap gap-2">
                {availableTags.map((tag) => (
                  <button
                    key={tag}
                    onClick={() => setSelectedTag(tag)}
                    className={`rounded-full border px-3 py-1 text-xs transition ${
                      selectedTag === tag
                        ? 'border-gray-900 bg-gray-900 text-white'
                        : 'border-gray-200 text-gray-600 hover:border-gray-300 hover:text-gray-900'
                    }`}
                  >
                    {tag}
                  </button>
                ))}
              </div>
              <div className="mt-3 space-y-2">
                {filteredNotes.length === 0 && (
                  <div className="rounded-lg border border-dashed border-gray-200 px-3 py-8 text-center text-sm text-gray-500">
                    当前筛选条件下没有笔记
                  </div>
                )}
                {filteredNotes.map((note) => (
                  <button
                    key={note.id}
                    onClick={() => void handleOpenNote(note)}
                    className={`w-full rounded-lg border px-3 py-3 text-left transition ${
                      selectedNoteId === note.id
                        ? 'border-gray-900 bg-gray-50'
                        : 'border-gray-200 hover:border-gray-300 hover:bg-gray-50'
                    }`}
                  >
                    <div className="line-clamp-2 text-sm font-semibold text-gray-900">{note.title}</div>
                    {note.summary && <div className="mt-1 line-clamp-2 text-xs text-gray-600">{note.summary}</div>}
                    <div className="mt-2 flex flex-wrap gap-1">
                      {(note.tags || []).map((tag) => (
                        <span key={tag} className="rounded bg-gray-100 px-2 py-0.5 text-[11px] text-gray-600">
                          {tag}
                        </span>
                      ))}
                    </div>
                  </button>
                ))}
              </div>
            </>
          )}
          {panelMode === 'qa' && (
            <>
              <div className="mb-3 flex items-center gap-2">
                <span className="text-xs text-gray-600">问答模型</span>
                <select
                  value={qaModel}
                  onChange={(e) => setQaModel(e.target.value)}
                  className="h-9 min-w-[280px] rounded-lg border border-gray-200 bg-white px-3 text-xs text-gray-800 outline-none focus:border-gray-300"
                >
                  {groupedQaModels.map((group) => (
                    <optgroup key={group.name} label={group.name}>
                      {group.models.map((model) => (
                        <option key={`${group.name}-${model}`} value={model}>
                          {model}
                        </option>
                      ))}
                    </optgroup>
                  ))}
                </select>
              </div>
              <div className="flex items-stretch gap-2">
                <textarea
                  value={question}
                  onChange={(e) => setQuestion(e.target.value)}
                  placeholder="例如：排查 Linux 内存异常时有哪些可靠步骤？"
                  className="min-h-[52px] flex-1 resize-none rounded-lg border border-gray-200 p-3 text-sm text-gray-800 outline-none focus:border-gray-300"
                />
                  <button
                    onClick={handleAskQuestion}
                    disabled={asking}
                    className="inline-flex w-[136px] shrink-0 items-center justify-center gap-2 rounded-lg bg-gray-900 px-3 py-2 text-sm text-white transition hover:bg-gray-800 disabled:opacity-60"
                  >
                  {asking ? <Loader2 size={14} className="animate-spin" /> : <Send size={14} />}
                  {asking ? '检索中...' : '检索回答'}
                </button>
              </div>

              <div className="mt-4 min-h-[220px] rounded-lg border border-gray-200 bg-gray-50 p-3">
                {answerMarkdown ? (
                  <MarkdownRenderer content={answerMarkdown} preset="notebook" normalizeLatexDelimiters />
                ) : (
                  <div className="text-sm text-gray-500">在上方输入问题后，将在这里显示检索回答。</div>
                )}
              </div>

              <div className="mt-4">
                <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-gray-500">来源文件</h3>
                <div className="space-y-2">
                  {sourceHits.length === 0 && <div className="text-xs text-gray-500">暂无来源。</div>}
                  {sourceHits.map((source) => (
                    <div key={source.source_id} className="rounded-lg border border-gray-200 bg-white p-2">
                      <div className="text-xs font-semibold text-gray-900">{source.title}</div>
                      <div className="mt-1 line-clamp-2 text-[11px] text-gray-600">{source.snippet}</div>
                      <div className="mt-2 flex items-center gap-2">
                        <button
                          onClick={() => {
                            const target = notes.find((item) => item.id === source.note_id)
                            setPanelMode('list')
                            if (target) {
                              void handleOpenNote(target)
                            } else {
                              setSelectedNoteId(source.note_id)
                            }
                          }}
                          className="rounded border border-gray-200 px-2 py-0.5 text-[11px] text-gray-600 hover:bg-gray-50"
                        >
                          定位笔记
                        </button>
                        {source.path ? (
                          <a
                            href={source.path}
                            target="_blank"
                            rel="noreferrer"
                            className="inline-flex items-center gap-1 rounded border border-gray-200 px-2 py-0.5 text-[11px] text-gray-600 hover:bg-gray-50"
                          >
                            <ExternalLink size={11} />
                            打开文件
                          </a>
                        ) : null}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            </>
          )}
          {panelMode === 'create' && (
            <div className="flex flex-col gap-3">
              <input
                value={newTitle}
                onChange={(e) => setNewTitle(e.target.value)}
                placeholder="笔记标题（必填）"
                className="h-10 w-full rounded-lg border border-gray-200 px-3 text-sm text-gray-800 outline-none focus:border-gray-300"
              />
              <input
                value={newSummary}
                onChange={(e) => setNewSummary(e.target.value)}
                placeholder="摘要（可选，不填将自动截取内容）"
                className="h-10 w-full rounded-lg border border-gray-200 px-3 text-sm text-gray-800 outline-none focus:border-gray-300"
              />
              <div className="rounded-lg border border-gray-200 p-3">
                <div className="mb-2 text-xs font-semibold text-gray-600">标签（可新增自定义标签）</div>
                <div className="mb-2 flex flex-wrap gap-2">
                  {customCreateTags.map((tag) => (
                    <span key={tag} className="inline-flex items-center gap-1 rounded-full bg-gray-900 px-2 py-1 text-xs text-white">
                      {tag}
                      <button
                        type="button"
                        onClick={() => setNewTags((prev) => prev.filter((item) => item !== tag))}
                        className="rounded-full bg-white/20 p-0.5 hover:bg-white/30"
                        title="移除标签"
                      >
                        <X size={10} />
                      </button>
                    </span>
                  ))}
                </div>
                <div className="flex items-center gap-2">
                  <input
                    value={newTagInput}
                    onChange={(e) => setNewTagInput(e.target.value)}
                    onKeyDown={handleCreateTagKeyDown}
                    placeholder="输入标签后回车，例如：网络、K8s、论文想法"
                    className="h-9 flex-1 rounded-lg border border-gray-200 px-3 text-xs text-gray-800 outline-none focus:border-gray-300"
                  />
                  <button
                    type="button"
                    onClick={() => {
                      appendCreateTag(newTagInput)
                      setNewTagInput('')
                    }}
                    className="inline-flex h-9 items-center gap-1 rounded-lg border border-gray-300 px-3 text-xs text-gray-700 hover:bg-gray-50"
                  >
                    <Plus size={12} />
                    添加
                  </button>
                </div>
                <div className="mt-2 flex flex-wrap gap-1">
                  {createPresetTags.map((tag) => {
                    const active = newTags.includes(tag)
                    return (
                      <button
                        key={tag}
                        type="button"
                        onClick={() => {
                          setNewTags((prev) => (prev.includes(tag) ? prev.filter((item) => item !== tag) : [...prev, tag]))
                        }}
                        className={`rounded-full border px-2 py-1 text-[11px] ${
                          active
                            ? 'border-gray-900 bg-gray-900 text-white'
                            : 'border-gray-200 text-gray-600 hover:border-gray-300 hover:text-gray-900'
                        }`}
                      >
                        {tag}
                      </button>
                    )
                  })}
                </div>
              </div>
              <textarea
                value={newContent}
                onChange={(e) => setNewContent(e.target.value)}
                placeholder="在这里粘贴原始笔记（支持 Markdown）..."
                className="min-h-[220px] flex-1 resize-none rounded-lg border border-gray-200 p-3 text-sm text-gray-800 outline-none focus:border-gray-300"
              />
              <div className="flex items-center justify-between">
                <span className="text-xs text-gray-500">保存后会写入后端笔记库，并建立检索索引。</span>
                <div className="flex items-center gap-2">
                  <button
                    type="button"
                    onClick={() => {
                      setNewTitle('')
                      setNewSummary('')
                      setNewContent('')
                      setNewTagInput('')
                      setNewTags([])
                    }}
                    className="rounded-md border border-gray-200 px-3 py-1.5 text-xs text-gray-600 hover:bg-gray-50"
                  >
                    清空
                  </button>
                  <button
                    type="button"
                    onClick={handleCreateNote}
                    className="rounded-md bg-gray-900 px-3 py-1.5 text-xs text-white hover:bg-gray-800"
                  >
                    保存笔记
                  </button>
                </div>
              </div>
            </div>
          )}
        </div>
      </section>

      {previewOpen && selectedNote && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4 lg:p-8"
          onClick={() => setPreviewOpen(false)}
        >
          <div
            className="flex h-[88vh] w-full max-w-5xl flex-col overflow-hidden rounded-xl border border-gray-200 bg-white shadow-2xl"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center justify-between border-b border-gray-200 px-4 py-3">
              <div className="min-w-0">
                <div className="truncate text-base font-semibold text-gray-900">{selectedNote.title}</div>
                <div className="mt-1 flex flex-wrap gap-1">
                  {(selectedNote.tags || []).map((tag) => (
                    <span key={tag} className="rounded bg-gray-100 px-2 py-0.5 text-[11px] text-gray-600">
                      {tag}
                    </span>
                  ))}
                </div>
              </div>
              <div className="ml-3 flex items-center gap-2">
                {selectedNote.path ? (
                  <a
                    href={selectedNote.path}
                    target="_blank"
                    rel="noreferrer"
                    className="inline-flex items-center gap-1 rounded-md border border-gray-200 px-2 py-1 text-xs text-gray-600 hover:bg-gray-50"
                  >
                    <ExternalLink size={12} />
                    打开源文件
                  </a>
                ) : (
                  <span className="rounded-md border border-gray-200 px-2 py-1 text-xs text-gray-500">本地草稿</span>
                )}
                <button
                  type="button"
                  onClick={() => setPreviewOpen(false)}
                  className="rounded-md border border-gray-200 p-1 text-gray-600 hover:bg-gray-50"
                  title="关闭"
                >
                  <X size={14} />
                </button>
              </div>
            </div>
            <div className="min-h-0 flex-1 overflow-y-auto px-6 py-5">
              {!selectedNoteContent && (
                <div className="flex items-center text-sm text-gray-500">
                  <Loader2 size={14} className="mr-2 animate-spin" />
                  正在加载笔记内容...
                </div>
              )}
              {selectedNoteContent && (
                <div className="max-w-none">
                  <MarkdownRenderer content={selectedNoteContent} preset="notebook" normalizeLatexDelimiters />
                </div>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
