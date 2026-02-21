// Review note:
// - 新增“Arxiv论文精细翻译”自定义工具页逻辑（提交任务、轮询状态、下载产物）。
import { useEffect, useMemo, useRef, useState } from 'react'
import { Card, CardContent, CardHeader, CardTitle, Input, Button, Loading, addToast } from '../components/ui'
import { Document, Page, pdfjs } from 'react-pdf'
import apiClient from '../api/client'
import { useAppStore } from '../store/app'
import { ArxivTranslateHistoryItem, ArxivTranslateJob } from '../types/api'
import 'react-pdf/dist/Page/AnnotationLayer.css'
import 'react-pdf/dist/Page/TextLayer.css'

interface CustomTool {
  id: string
  name: string
  description: string
  icon: string
}

interface CitationHoverState {
  key: string
  text: string
  x: number
  y: number
}

interface PdfLinkCitationMeta {
  key: string
  text: string
}

const ARXIV_DEFAULT_EXTRA_PROMPT = [
  'If the term "agent" appears, translate it as "智能体"; "policy" as "策略"; "reward model" as "奖励模型"; "alignment" as "对齐".',
  "Keep abbreviations unchanged at first mention, and append Chinese in parentheses (e.g., Distributionally Robust Optimization (DRO，分布鲁棒优化)).",
].join('\n')
const ARXIV_DEFAULT_MODEL = 'gpt-4o-mini'
const BIB_PRIORITY_FIELDS = [
  'author',
  'title',
  'journal', // 期刊， 一般用于期刊论文
  'booktitle', // 会议录，一般用于会议论文
  'publisher', // 出版社，一般用于书籍
  'volume',
  'number',
  'pages',
  'year',
  'doi'
]
const BIB_IGNORED_FIELDS = new Set(['bibsource', 'timestamp'])
const DEBUG_CITATION_HOVER = false
const COMPARE_ZOOM_MIN = 0.6
const COMPARE_ZOOM_MAX = 2.4
const COMPARE_ZOOM_STEP = 0.1

pdfjs.GlobalWorkerOptions.workerSrc = new URL(
  'pdfjs-dist/build/pdf.worker.min.mjs',
  import.meta.url,
).toString()

interface BibField {
  name: string
  value: string
  lowerName: string
}

const unwrapBibValue = (value: string) => {
  const text = value.trim()
  if (text.startsWith('{') && text.endsWith('}')) {
    return { inner: text.slice(1, -1), wrapper: 'brace' as const }
  }
  if (text.startsWith('"') && text.endsWith('"')) {
    return { inner: text.slice(1, -1), wrapper: 'quote' as const }
  }
  return { inner: text, wrapper: 'raw' as const }
}

const wrapBibValue = (inner: string, wrapper: 'brace' | 'quote' | 'raw') => {
  if (wrapper === 'brace') return `{${inner}}`
  if (wrapper === 'quote') return `"${inner}"`
  return inner
}

const normalizeAuthorValue = (value: string) => {
  const { inner, wrapper } = unwrapBibValue(value)
  const normalizedInner = inner
    .replace(/\s+/g, ' ')
    .replace(/\s+and\s+/gi, ' and ')
    .trim()
  if (!normalizedInner) return value

  const authors = normalizedInner.split(/\s+and\s+/i).map((a) => a.trim()).filter(Boolean)
  if (authors.length === 0) return value

  const converted = authors.map((author) => {
    if (author.includes(',')) return author
    const tokens = author.split(/\s+/).filter(Boolean)
    if (tokens.length < 2) return author
    const last = tokens[tokens.length - 1]
    const first = tokens.slice(0, -1).join(' ')
    return `${last}, ${first}`
  })
  return wrapBibValue(converted.join(' and '), wrapper)
}

const readBalancedBraces = (text: string, start: number) => {
  let i = start
  let depth = 0
  while (i < text.length) {
    const ch = text[i]
    if (ch === '{') depth += 1
    if (ch === '}') {
      depth -= 1
      if (depth === 0) return i + 1
    }
    i += 1
  }
  return text.length
}

const readQuotedValue = (text: string, start: number) => {
  let i = start + 1
  while (i < text.length) {
    const ch = text[i]
    if (ch === '\\') {
      i += 2
      continue
    }
    if (ch === '"') return i + 1
    i += 1
  }
  return text.length
}

const parseBibFields = (body: string): BibField[] => {
  const fields: BibField[] = []
  let i = 0
  while (i < body.length) {
    while (i < body.length && /[\s,]/.test(body[i])) i += 1
    if (i >= body.length) break

    const nameStart = i
    while (i < body.length && /[A-Za-z0-9_:-]/.test(body[i])) i += 1
    const name = body.slice(nameStart, i).trim()
    if (!name) break

    while (i < body.length && /\s/.test(body[i])) i += 1
    if (body[i] !== '=') {
      while (i < body.length && body[i] !== ',') i += 1
      continue
    }
    i += 1
    while (i < body.length && /\s/.test(body[i])) i += 1
    if (i >= body.length) break

    const valueStart = i
    if (body[i] === '{') {
      i = readBalancedBraces(body, i)
    } else if (body[i] === '"') {
      i = readQuotedValue(body, i)
    } else {
      while (i < body.length && body[i] !== ',') i += 1
    }
    const value = body.slice(valueStart, i).trim()
    fields.push({
      name,
      value,
      lowerName: name.toLowerCase(),
    })
    while (i < body.length && /\s/.test(body[i])) i += 1
    if (body[i] === ',') i += 1
  }
  return fields
}

const reorderBibtexFields = (bibtex: string) => {
  const text = (bibtex || '').trim()
  const headerMatch = text.match(/^@([A-Za-z0-9_:+-]+)\s*\{\s*([^,]+)\s*,/s)
  if (!headerMatch) return bibtex

  const entryType = headerMatch[1]
  const citeKey = headerMatch[2].trim()
  const headerEnd = headerMatch[0].length
  const lastBraceIndex = text.lastIndexOf('}')
  if (lastBraceIndex <= headerEnd) return bibtex

  const body = text.slice(headerEnd, lastBraceIndex)
  const fields = parseBibFields(body)
  if (fields.length === 0) return bibtex
  const filteredFields = fields.filter((field) => !BIB_IGNORED_FIELDS.has(field.lowerName))
  if (filteredFields.length === 0) return bibtex

  const used = new Set<number>()
  const ordered: BibField[] = []

  for (const key of BIB_PRIORITY_FIELDS) {
    filteredFields.forEach((field, idx) => {
      if (!used.has(idx) && field.lowerName === key) {
        ordered.push(field)
        used.add(idx)
      }
    })
  }

  filteredFields.forEach((field, idx) => {
    if (!used.has(idx)) {
      ordered.push(field)
      used.add(idx)
    }
  })

  const displayFields = ordered.map((field) => {
    if (field.lowerName === 'author') {
      return { ...field, value: normalizeAuthorValue(field.value) }
    }
    return field
  })
  const maxFieldNameLength = displayFields.reduce((max, field) => Math.max(max, field.name.length), 0)
  const lines = displayFields.map(
    (field) => `  ${field.name.padEnd(maxFieldNameLength, ' ')} = ${field.value},`
  )
  return `@${entryType}{${citeKey},\n${lines.join('\n')}\n}`
}

export const CustomToolsPage = () => {
  const {
    apiConfig,
    hasBackendApiKey,
    availableModelGroups,
    availableModels,
  } = useAppStore()
  const tools = useMemo<CustomTool[]>(
    () => [
      {
        id: 'bib-lookup',
        name: 'Bib 引用查询',
        description: '输入论文标题，输出标准 BibTeX 引用',
        icon: '📚',
      },
      {
        id: 'arxiv-latex-translate',
        name: 'Arxiv论文精细翻译',
        description: '输入 arXiv 链接/ID，基于 LaTeX 源码翻译并导出 PDF',
        icon: '🧾',
      },
    ],
    []
  )

  const [selectedToolId, setSelectedToolId] = useState<string | null>(null)
  const [bibTitle, setBibTitle] = useState('')
  const [bibShorten, setBibShorten] = useState(false)
  const [bibRemoveFields, setBibRemoveFields] = useState('url,biburl,address,publisher')
  const [loading, setLoading] = useState(false)
  const [bibOutput, setBibOutput] = useState<string | null>(null)
  const [bibCandidates, setBibCandidates] = useState<{ title: string; bibtex: string }[]>([])
  const [copiedBibKey, setCopiedBibKey] = useState<string | null>(null)
  const [arxivInput, setArxivInput] = useState('')
  const [arxivTargetLang, setArxivTargetLang] = useState('中文')
  const [arxivExtraPrompt, setArxivExtraPrompt] = useState(ARXIV_DEFAULT_EXTRA_PROMPT)
  const [arxivAllowCache, setArxivAllowCache] = useState(true)
  const [arxivConcurrency, setArxivConcurrency] = useState('16')
  const [arxivModelGroup, setArxivModelGroup] = useState('')
  const [arxivModel, setArxivModel] = useState(ARXIV_DEFAULT_MODEL)
  const [arxivDefaultModel, setArxivDefaultModel] = useState(ARXIV_DEFAULT_MODEL)
  const [arxivJob, setArxivJob] = useState<ArxivTranslateJob | null>(null)
  const [arxivHistory, setArxivHistory] = useState<ArxivTranslateHistoryItem[]>([])
  const [expandedHistoryJobId, setExpandedHistoryJobId] = useState<string | null>(null)
  const [compareOpen, setCompareOpen] = useState(false)
  const [compareLeftUrl, setCompareLeftUrl] = useState('')
  const [compareRightUrl, setCompareRightUrl] = useState('')
  const [compareCitationHover, setCompareCitationHover] = useState<CitationHoverState | null>(null)
  const [compareCitationPinned, setCompareCitationPinned] = useState<{ key: string; text: string } | null>(null)
  const [compareTitle, setCompareTitle] = useState('')
  const [compareError, setCompareError] = useState('')
  const [compareLeftLoading, setCompareLeftLoading] = useState(false)
  const [compareRightLoading, setCompareRightLoading] = useState(false)
  const [compareLeftPages, setCompareLeftPages] = useState(0)
  const [compareRightPages, setCompareRightPages] = useState(0)
  const [compareLeftPageWidth, setCompareLeftPageWidth] = useState(640)
  const [compareRightPageWidth, setCompareRightPageWidth] = useState(640)
  const [compareZoom, setCompareZoom] = useState(1)
  const [compareScrollSync, setCompareScrollSync] = useState(true)
  const leftPdfRef = useRef<HTMLDivElement | null>(null)
  const rightPdfRef = useRef<HTMLDivElement | null>(null)
  const syncLockRef = useRef(false)
  const hoverHideTimerRef = useRef<number | null>(null)
  const hoverPanelRef = useRef<HTMLDivElement | null>(null)
  const compareLinkCitationsRef = useRef<{
    left: Record<string, PdfLinkCitationMeta>
    right: Record<string, PdfLinkCitationMeta>
  }>({ left: {}, right: {} })

  const selectedTool = tools.find((t) => t.id === selectedToolId) || null
  const modelGroupOptions = availableModelGroups || []
  const arxivModelGroupOptions = useMemo(
    () => modelGroupOptions.filter((g) => g.name === '云雾'),
    [modelGroupOptions]
  )
  const arxivModelSet = useMemo(() => {
    const collected = new Set<string>()
    arxivModelGroupOptions.forEach((group) => {
      ;(group.models || []).forEach((model) => collected.add(model))
    })
    return collected
  }, [arxivModelGroupOptions])
  const arxivFallbackModelOptions = useMemo(() => {
    if (arxivModelSet.size === 0) return []
    return (availableModels || []).filter((model) => arxivModelSet.has(model))
  }, [availableModels, arxivModelSet])
  const currentGroupModels = useMemo(() => {
    if (!arxivModelGroupOptions.length) return []
    const group = arxivModelGroupOptions.find((g) => g.name === arxivModelGroup)
    return group?.models || []
  }, [arxivModelGroupOptions, arxivModelGroup])
  const displayBibOutput = useMemo(() => {
    if (!bibOutput) return null
    return reorderBibtexFields(bibOutput)
  }, [bibOutput])
  const displayBibCandidates = useMemo(
    () =>
      bibCandidates.map((cand) => ({
        ...cand,
        displayBibtex: reorderBibtexFields(cand.bibtex),
      })),
    [bibCandidates]
  )
  const comparePdfOptions = useMemo(() => ({ withCredentials: false }), [])
  const compareZoomPercent = Math.round(compareZoom * 100)
  const compareLeftRenderWidth = Math.max(220, Math.floor(compareLeftPageWidth * compareZoom))
  const compareRightRenderWidth = Math.max(220, Math.floor(compareRightPageWidth * compareZoom))

  const clampCompareZoom = (value: number) => {
    const clamped = Math.min(COMPARE_ZOOM_MAX, Math.max(COMPARE_ZOOM_MIN, value))
    return Number(clamped.toFixed(2))
  }

  const adjustCompareZoom = (delta: number) => {
    setCompareZoom((prev) => clampCompareZoom(prev + delta))
  }

  const handleComparePaneWheel = (event: React.WheelEvent<HTMLDivElement>) => {
    if (!event.ctrlKey && !event.metaKey) return
    event.preventDefault()
    adjustCompareZoom(event.deltaY < 0 ? COMPARE_ZOOM_STEP : -COMPARE_ZOOM_STEP)
  }

  const refreshArxivHistory = async () => {
    try {
      const res = await apiClient.listArxivTranslateJobs(40, 'succeeded')
      setArxivHistory(res.data.items || [])
    } catch (error) {
      console.error('Failed to load arxiv history jobs:', error)
      setArxivHistory([])
    }
  }

  const restoreActiveArxivJob = async () => {
    try {
      const res = await apiClient.listArxivTranslateJobs(1, 'queued,running')
      const active = (res.data.items || [])[0]
      if (!active?.job_id) {
        return
      }
      const detail = await apiClient.getArxivTranslateJob(active.job_id)
      setArxivJob(detail.data)
      if ((detail.data.input_text || '').trim()) {
        setArxivInput(detail.data.input_text)
      }
    } catch (error) {
      console.error('Failed to restore active arxiv translation job:', error)
    }
  }

  const loadArxivDefaultModel = async () => {
    try {
      const res = await apiClient.getDefaultConfig()
      const model = (res.data.custom_tool_defaults?.arxiv_translate?.model || '').trim()
      if (model) {
        setArxivDefaultModel(model)
      }
    } catch (error) {
      console.error('Failed to load default arxiv translate model:', error)
    }
  }

  useEffect(() => {
    if (!arxivJob) return
    if (!['queued', 'running'].includes(arxivJob.status)) return

    const timer = window.setInterval(async () => {
      try {
        const res = await apiClient.getArxivTranslateJob(arxivJob.job_id)
        setArxivJob(res.data)
      } catch (error) {
        console.error('Failed to poll arxiv translation job:', error)
      }
    }, 1800)

    return () => window.clearInterval(timer)
  }, [arxivJob])

  useEffect(() => {
    if (selectedToolId !== 'arxiv-latex-translate') return
    refreshArxivHistory()
    restoreActiveArxivJob()
    loadArxivDefaultModel()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedToolId])

  useEffect(() => {
    if (selectedToolId !== 'arxiv-latex-translate') return
    if (!arxivJob) return
    if (['queued', 'running'].includes(arxivJob.status)) return
    refreshArxivHistory()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [arxivJob?.job_id, arxivJob?.status, selectedToolId])

  useEffect(() => {
    const preferredModel = arxivDefaultModel || ARXIV_DEFAULT_MODEL
    const currentModel = arxivModel || preferredModel || apiConfig.model || ARXIV_DEFAULT_MODEL
    if (arxivModelGroupOptions.length > 0) {
      const matchedGroup =
        arxivModelGroupOptions.find((g) => g.models.includes(currentModel)) ||
        arxivModelGroupOptions.find((g) => g.models.includes(preferredModel)) ||
        arxivModelGroupOptions.find((g) => g.models.includes(apiConfig.model))
      const nextGroup = matchedGroup?.name || arxivModelGroupOptions[0]?.name || ''
      if (!arxivModelGroup || !arxivModelGroupOptions.some((g) => g.name === arxivModelGroup)) {
        setArxivModelGroup(nextGroup)
        return
      }
      const groupModels = arxivModelGroupOptions.find((g) => g.name === arxivModelGroup)?.models || []
      if (!arxivModel || !groupModels.includes(arxivModel)) {
        const nextModel = (preferredModel && groupModels.includes(preferredModel))
          ? preferredModel
          : groupModels.includes(apiConfig.model)
            ? apiConfig.model
            : (groupModels.includes(currentModel) ? currentModel : groupModels[0])
        setArxivModel(nextModel || '')
      }
      return
    }

    if ((!arxivModel || !arxivFallbackModelOptions.includes(arxivModel)) && arxivFallbackModelOptions.length > 0) {
      const next = (preferredModel && arxivFallbackModelOptions.includes(preferredModel))
        ? preferredModel
        : arxivFallbackModelOptions.includes(apiConfig.model)
          ? apiConfig.model
          : (arxivFallbackModelOptions.includes(currentModel) ? currentModel : arxivFallbackModelOptions[0])
      setArxivModel(next || '')
    }
  }, [
    apiConfig.model,
    arxivDefaultModel,
    arxivModel,
    arxivModelGroup,
    arxivFallbackModelOptions,
    arxivModelGroupOptions,
  ])

  const handleRun = async () => {
    if (!selectedTool) return
    try {
      setLoading(true)
      if (selectedTool.id === 'bib-lookup') {
        const res = await apiClient.runBibLookup({
          title: bibTitle.trim(),
          shorten: bibShorten,
          remove_fields: bibRemoveFields
            .split(',')
            .map((s) => s.trim())
            .filter(Boolean),
          max_candidates: 5,
        })
        setBibOutput(res.data.bibtex || null)
        setBibCandidates(res.data.candidates || [])
      } else if (selectedTool.id === 'arxiv-latex-translate') {
        const res = await apiClient.createArxivTranslateJob({
          input_text: arxivInput.trim(),
          api_key: apiConfig.api_key || undefined,
          base_url: apiConfig.base_url || undefined,
          model: arxivModel || arxivDefaultModel || ARXIV_DEFAULT_MODEL,
          target_language: arxivTargetLang,
          extra_prompt: arxivExtraPrompt,
          allow_cache: arxivAllowCache,
          concurrency: Number(arxivConcurrency) || 2,
        })
        setArxivJob(res.data)
        if (!['queued', 'running'].includes(res.data.status)) {
          refreshArxivHistory()
        }
      }
    } catch (error) {
      console.error('Failed to run custom tool:', error)
      setBibOutput(null)
      setBibCandidates([])
      setArxivJob(null)
    } finally {
      setLoading(false)
    }
  }

  const handleCancelArxivJob = async () => {
    if (!arxivJob) return
    try {
      setLoading(true)
      const res = await apiClient.cancelArxivTranslateJob(arxivJob.job_id)
      setArxivJob(res.data)
    } catch (error) {
      console.error('Failed to cancel arxiv translation job:', error)
    } finally {
      setLoading(false)
    }
  }

  const translatedChunks = Number(arxivJob?.meta?.translated_chunks || 0)
  const totalChunks = Number(arxivJob?.meta?.total_chunks || 0)
  const progressPercent =
    totalChunks > 0 ? Math.min(100, Math.max(0, Math.round((translatedChunks / totalChunks) * 100))) : 0
  const parseCostMeta = (raw: any): any | null => {
    if (!raw) return null
    if (typeof raw === 'string') {
      try {
        return JSON.parse(raw)
      } catch {
        return null
      }
    }
    if (typeof raw === 'object') return raw
    return null
  }
  const formatCost5 = (value: number): string => {
    if (!Number.isFinite(value)) return '0.00000'
    return Number(value).toFixed(5)
  }
  const currentJobCost = parseCostMeta(arxivJob?.meta?.cost_meta)

  const getArtifactUrl = (url: string) => {
    if (!url) return '#'
    if (/^https?:\/\//i.test(url)) return url
    return url.startsWith('/') ? url : `/${url}`
  }

  const getArtifactByName = (item: ArxivTranslateHistoryItem, name: string) =>
    (item.artifacts || []).find((a) => a.name === name)

  const handleOpenCompare = (item: ArxivTranslateHistoryItem) => {
    const translatedPdf = item.translated_pdf_url || getArtifactByName(item, 'translate_zh.pdf')?.url || ''
    const originalPdf =
      item.original_pdf_url || (item.paper_id ? `https://arxiv.org/pdf/${item.paper_id}.pdf` : '')
    if (!translatedPdf || !originalPdf) {
      setCompareError('当前任务缺少对照所需 PDF。')
      return
    }
    setCompareError('')
    setCompareTitle(item.task_name || `arXiv:${item.paper_id || item.job_id}`)
    setCompareLeftUrl(getArtifactUrl(originalPdf))
    setCompareRightUrl(getArtifactUrl(translatedPdf))
    compareLinkCitationsRef.current = { left: {}, right: {} }
    setCompareCitationHover(null)
    setCompareCitationPinned(null)
    setCompareZoom(1)
    setCompareScrollSync(true)
    setCompareOpen(true)
  }

  const clearHoverHideTimer = () => {
    if (hoverHideTimerRef.current !== null) {
      window.clearTimeout(hoverHideTimerRef.current)
      hoverHideTimerRef.current = null
    }
  }

  const scheduleHoverHide = () => {
    clearHoverHideTimer()
    if (compareCitationPinned) return
    hoverHideTimerRef.current = window.setTimeout(() => {
      setCompareCitationHover(null)
    }, 400)
  }

  const calcTooltipPosition = (x: number, y: number) => {
    const margin = 12
    const estimatedWidth = 520
    const estimatedHeight = 210
    const vw = window.innerWidth || 1280
    const vh = window.innerHeight || 720
    let left = x + 12
    let top = y + 12
    if (left + estimatedWidth > vw - margin) {
      left = Math.max(margin, x - estimatedWidth - 12)
    }
    if (top + estimatedHeight > vh - margin) {
      top = Math.max(margin, vh - estimatedHeight - margin)
    }
    return { left, top }
  }

  const normalizeText = (value: string) => value.replace(/\s+/g, ' ').trim()

  const resolveDestination = async (pdfDoc: any, dest: any): Promise<{ pageNumber: number; y: number | null } | null> => {
    let target = dest
    if (!target) return null
    if (typeof target === 'string') {
      target = await pdfDoc.getDestination(target)
    }
    if (!Array.isArray(target) || target.length === 0) return null
    const pageRef = target[0]
    let pageIndex = -1
    if (typeof pageRef === 'number') {
      pageIndex = pageRef
    } else if (pageRef && typeof pageRef === 'object') {
      try {
        pageIndex = await pdfDoc.getPageIndex(pageRef)
      } catch {
        return null
      }
    }
    if (!Number.isFinite(pageIndex) || pageIndex < 0) return null
    const yRaw = target[3]
    const y = typeof yRaw === 'number' && Number.isFinite(yRaw) ? yRaw : null
    return { pageNumber: pageIndex + 1, y }
  }

  const pageTextCacheRef = useRef<{
    left: Map<number, Array<{ str: string; x: number; y: number }>>
    right: Map<number, Array<{ str: string; x: number; y: number }>>
  }>({ left: new Map(), right: new Map() })

  const readPageTextItems = async (
    side: 'left' | 'right',
    pdfDoc: any,
    pageNumber: number,
  ): Promise<Array<{ str: string; x: number; y: number }>> => {
    const cache = pageTextCacheRef.current[side]
    const cached = cache.get(pageNumber)
    if (cached) return cached
    const page = await pdfDoc.getPage(pageNumber)
    const textContent = await page.getTextContent()
    const items = (textContent?.items || [])
      .map((item: any) => {
        const str = typeof item?.str === 'string' ? normalizeText(item.str) : ''
        const tx = item?.transform
        if (!str || !Array.isArray(tx) || tx.length < 6) return null
        return { str, x: Number(tx[4]) || 0, y: Number(tx[5]) || 0 }
      })
      .filter(Boolean) as Array<{ str: string; x: number; y: number }>
    const sorted = items.sort((a, b) => {
      if (Math.abs(a.y - b.y) > 1.5) return b.y - a.y
      return a.x - b.x
    })
    cache.set(pageNumber, sorted)
    return sorted
  }

  const extractCitationSnippet = async (
    side: 'left' | 'right',
    pdfDoc: any,
    dest: { pageNumber: number; y: number | null },
  ): Promise<string> => {
    const items = await readPageTextItems(side, pdfDoc, dest.pageNumber)
    if (items.length === 0) return ''
    let pivot = Math.min(10, items.length - 1)
    if (dest.y !== null) {
      let best = 0
      let bestDelta = Number.MAX_SAFE_INTEGER
      for (let i = 0; i < items.length; i += 1) {
        const delta = Math.abs(items[i].y - dest.y)
        if (delta < bestDelta) {
          bestDelta = delta
          best = i
        }
      }
      pivot = best
    }
    const windowItems = items.slice(Math.max(0, pivot - 10), Math.min(items.length, pivot + 48))
    const lineTolerance = 2.5
    const lines: Array<{ y: number; parts: string[] }> = []
    for (const it of windowItems) {
      const last = lines[lines.length - 1]
      if (!last || Math.abs(last.y - it.y) > lineTolerance) {
        lines.push({ y: it.y, parts: [it.str] })
      } else {
        last.parts.push(it.str)
      }
    }

    const text = lines
      .map((line) => line.parts.join(' ').replace(/\s+/g, ' ').trim())
      .filter(Boolean)
      .join('\n')
      .trim()
    return text.slice(0, 900)
  }

  const buildPdfLinkCitationMap = async (
    side: 'left' | 'right',
    pdfDoc: any,
  ): Promise<Record<string, PdfLinkCitationMeta>> => {
    const map: Record<string, PdfLinkCitationMeta> = {}
    for (let pageNumber = 1; pageNumber <= pdfDoc.numPages; pageNumber += 1) {
      const page = await pdfDoc.getPage(pageNumber)
      const annotations = await page.getAnnotations()
      for (let idx = 0; idx < annotations.length; idx += 1) {
        const ann = annotations[idx]
        if (ann?.subtype !== 'Link') continue
        if (ann?.url) continue
        const resolvedDest = await resolveDestination(pdfDoc, ann?.dest)
        if (!resolvedDest) continue
        const snippet = await extractCitationSnippet(side, pdfDoc, resolvedDest)
        if (!snippet) continue
        const annId = typeof ann?.id === 'string' ? ann.id : ''
        const key = `p${resolvedDest.pageNumber}`
        const text = snippet
        map[`${pageNumber}:@${idx}`] = { key, text }
        if (annId) {
          map[`${pageNumber}:${annId}`] = { key, text }
        }
      }
    }
    return map
  }

  const resolveCitationFromEventTarget = (target: EventTarget | null): PdfLinkCitationMeta | null => {
    const el = target as HTMLElement | null
    if (!el) return null
    const section = el.closest('.react-pdf__Page__annotations section') as HTMLElement | null
    if (!section) return null
    const pageContainer = section.closest('[data-compare-page-number]') as HTMLElement | null
    const sideContainer = section.closest('[data-compare-side]') as HTMLElement | null
    const pageNumber = Number(pageContainer?.dataset.comparePageNumber || 0)
    const sideRaw = sideContainer?.dataset.compareSide
    const side = sideRaw === 'left' || sideRaw === 'right' ? sideRaw : ''
    if (!pageNumber || !side) return null

    const sideMap = compareLinkCitationsRef.current[side]
    const annId = section.getAttribute('data-annotation-id') || ''
    const annSiblings = Array.from(section.parentElement?.querySelectorAll('section') || [])
    const annIndex = annSiblings.indexOf(section)
    const byId = annId ? sideMap[`${pageNumber}:${annId}`] : null
    const byIndex = annIndex >= 0 ? sideMap[`${pageNumber}:@${annIndex}`] : null
    const resolved = byId || byIndex || null
    if (DEBUG_CITATION_HOVER && !resolved) {
      console.log('[citation-hover-unmatched-link]', { side, pageNumber, annId, annIndex })
    }
    return resolved
  }

  const handleComparePaneMouseMove = (event: React.MouseEvent<HTMLDivElement>) => {
    const resolved = resolveCitationFromEventTarget(event.target)
    if (!resolved) {
      if (!compareCitationPinned) {
        scheduleHoverHide()
      }
      return
    }
    clearHoverHideTimer()
    const pos = calcTooltipPosition(event.clientX, event.clientY)
    setCompareCitationHover({
      key: resolved.key,
      text: resolved.text,
      x: pos.left,
      y: pos.top,
    })
  }

  const handleComparePaneMouseLeave = () => {
    scheduleHoverHide()
  }

  const handleComparePaneClick = (event: React.MouseEvent<HTMLDivElement>) => {
    const resolved = resolveCitationFromEventTarget(event.target)
    if (resolved) return
    clearHoverHideTimer()
    setCompareCitationHover(null)
  }

  const syncPaneScroll = (from: HTMLDivElement | null, to: HTMLDivElement | null) => {
    if (!from || !to || syncLockRef.current) return
    const fromMax = from.scrollHeight - from.clientHeight
    const toMax = to.scrollHeight - to.clientHeight
    const ratio = fromMax > 0 ? from.scrollTop / fromMax : 0
    syncLockRef.current = true
    to.scrollTop = toMax > 0 ? ratio * toMax : 0
    window.requestAnimationFrame(() => {
      syncLockRef.current = false
    })
  }

  useEffect(() => {
    if (!compareOpen || !compareLeftUrl || !compareRightUrl) return
    setCompareError('')
    setCompareLeftLoading(true)
    setCompareRightLoading(true)
    setCompareLeftPages(0)
    setCompareRightPages(0)
    compareLinkCitationsRef.current = { left: {}, right: {} }
    pageTextCacheRef.current = { left: new Map(), right: new Map() }
    setCompareCitationHover(null)
    setCompareCitationPinned(null)
  }, [compareOpen, compareLeftUrl, compareRightUrl])

  useEffect(() => () => clearHoverHideTimer(), [])

  useEffect(() => {
    if (!compareOpen) return

    const updatePaneWidths = () => {
      const leftWidth = leftPdfRef.current
        ? Math.max(320, Math.floor(leftPdfRef.current.clientWidth - 16))
        : 0
      const rightWidth = rightPdfRef.current
        ? Math.max(320, Math.floor(rightPdfRef.current.clientWidth - 16))
        : 0
      if (leftWidth > 0) setCompareLeftPageWidth(leftWidth)
      if (rightWidth > 0) setCompareRightPageWidth(rightWidth)
    }

    updatePaneWidths()
    if (typeof ResizeObserver === 'undefined') {
      window.addEventListener('resize', updatePaneWidths)
      return () => window.removeEventListener('resize', updatePaneWidths)
    }

    const observer = new ResizeObserver(updatePaneWidths)
    if (leftPdfRef.current) observer.observe(leftPdfRef.current)
    if (rightPdfRef.current) observer.observe(rightPdfRef.current)
    return () => observer.disconnect()
  }, [compareOpen])

  const handleLeftPdfLoadSuccess = async (pdfDoc: any) => {
    setCompareLeftPages(Number(pdfDoc?.numPages || 0))
    try {
      compareLinkCitationsRef.current.left = await buildPdfLinkCitationMap('left', pdfDoc)
      if (DEBUG_CITATION_HOVER) {
        console.log('[citation-map-built]', { side: 'left', count: Object.keys(compareLinkCitationsRef.current.left).length })
      }
    } catch {
      compareLinkCitationsRef.current.left = {}
    }
    setCompareLeftLoading(false)
  }

  const handleRightPdfLoadSuccess = async (pdfDoc: any) => {
    setCompareRightPages(Number(pdfDoc?.numPages || 0))
    try {
      compareLinkCitationsRef.current.right = await buildPdfLinkCitationMap('right', pdfDoc)
      if (DEBUG_CITATION_HOVER) {
        console.log('[citation-map-built]', { side: 'right', count: Object.keys(compareLinkCitationsRef.current.right).length })
      }
    } catch {
      compareLinkCitationsRef.current.right = {}
    }
    setCompareRightLoading(false)
  }

  const handleLeftPdfLoadError = () => {
    setCompareLeftLoading(false)
    setCompareError('原文 PDF 加载失败，请稍后重试。')
  }

  const handleRightPdfLoadError = () => {
    setCompareRightLoading(false)
    setCompareError((prev) => prev || '译文 PDF 加载失败，请稍后重试。')
  }

  const getStepStatusUi = (status: string) => {
    if (status === 'done') {
      return {
        icon: '✓',
        ring: 'bg-emerald-100 text-emerald-700',
        text: 'text-gray-800',
      }
    }
    if (status === 'error') {
      return {
        icon: '✗',
        ring: 'bg-red-100 text-red-700',
        text: 'text-red-700',
      }
    }
    return {
      icon: '…',
      ring: 'bg-sky-100 text-sky-700',
      text: 'text-gray-700',
    }
  }

  const handleCopyBibText = async (value: string, key: string) => {
    try {
      if (navigator.clipboard && window.isSecureContext) {
        await navigator.clipboard.writeText(value)
      } else {
        const textarea = document.createElement('textarea')
        textarea.value = value
        textarea.setAttribute('readonly', '')
        textarea.style.position = 'fixed'
        textarea.style.top = '-9999px'
        document.body.appendChild(textarea)
        textarea.select()
        document.execCommand('copy')
        document.body.removeChild(textarea)
      }
      setCopiedBibKey(key)
      addToast('已复制到剪贴板', 'success')
      window.setTimeout(() => {
        setCopiedBibKey((prev) => (prev === key ? null : prev))
      }, 1800)
    } catch (error) {
      addToast('复制失败，请手动复制', 'error')
    }
  }

  return (
    <div className="max-w-6xl mx-auto">
      <div className="mb-8">
        <h1 className="text-3xl font-bold text-gray-900">自定义工具</h1>
        <p className="text-gray-600 mt-2">内置自定义工具合集</p>
      </div>

      {!selectedTool && (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {tools.map((tool) => (
            <div key={tool.id} className="relative group">
              <Card
                hover
                className="cursor-pointer h-full"
                onClick={() => {
                  setSelectedToolId(tool.id)
                  setBibOutput(null)
                  setBibCandidates([])
                  setArxivJob(null)
                  setArxivHistory([])
                  setExpandedHistoryJobId(null)
                }}
              >
                <CardContent className="p-4 flex flex-col h-full">
                  <div className="text-4xl mb-3">{tool.icon}</div>
                  <h3 className="font-semibold text-gray-900 mb-1">{tool.name}</h3>
                  <p className="text-gray-600 text-sm line-clamp-2 flex-grow">
                    {tool.description}
                  </p>
                </CardContent>
              </Card>
            </div>
          ))}
        </div>
      )}

      {selectedTool && (
        <div className="space-y-4">
          <div className="flex items-center gap-2 text-sm text-gray-600">
            <button
              className="hover:text-gray-900"
              onClick={() => {
                setSelectedToolId(null)
                setArxivHistory([])
                setExpandedHistoryJobId(null)
              }}
            >
              ← 返回列表
            </button>
            <span>/</span>
            <span>{selectedTool.name}</span>
          </div>

          <Card>
            <CardHeader>
              <CardTitle>{selectedTool.name}</CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              {selectedTool.id === 'bib-lookup' && (
                <div className="space-y-3">
                  <Input
                    label="论文标题"
                    value={bibTitle}
                    onChange={(e) => setBibTitle(e.target.value)}
                    placeholder="输入完整论文标题"
                  />
                  <div className="flex flex-col sm:flex-row gap-3 text-sm text-gray-700">
                    <label className="flex items-center gap-2">
                      <input
                        type="checkbox"
                        checked={bibShorten}
                        onChange={(e) => setBibShorten(e.target.checked)}
                      />
                      缩写会议/期刊名称（shorten）
                    </label>
                  </div>
                  <Input
                    label="移除字段（逗号分隔）"
                    value={bibRemoveFields}
                    onChange={(e) => setBibRemoveFields(e.target.value)}
                    placeholder="例如: url,biburl,address,publisher"
                    helper="对应 normalize.py 的 --remove 参数"
                  />
                </div>
              )}
              {selectedTool.id === 'arxiv-latex-translate' && (
                <div className="space-y-3">
                  {arxivModelGroupOptions.length > 0 ? (
                    <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                      <div>
                        <label className="block text-sm font-medium text-gray-700 mb-1">模型分组</label>
                        <select
                          value={arxivModelGroup}
                          onChange={(e) => {
                            const groupName = e.target.value
                            setArxivModelGroup(groupName)
                            const models = arxivModelGroupOptions.find((g) => g.name === groupName)?.models || []
                            setArxivModel(models[0] || '')
                          }}
                          className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm bg-white"
                        >
                          {arxivModelGroupOptions.map((group) => (
                            <option key={group.name} value={group.name}>
                              {group.name}
                            </option>
                          ))}
                        </select>
                      </div>
                      <div>
                        <label className="block text-sm font-medium text-gray-700 mb-1">翻译模型</label>
                        <select
                          value={arxivModel}
                          onChange={(e) => setArxivModel(e.target.value)}
                          className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm bg-white"
                        >
                          {currentGroupModels.map((model) => (
                            <option key={model} value={model}>
                              {model}
                            </option>
                          ))}
                        </select>
                      </div>
                    </div>
                  ) : (
                    <div>
                      <label className="block text-sm font-medium text-gray-700 mb-1">翻译模型</label>
                      <select
                        value={arxivModel}
                        onChange={(e) => setArxivModel(e.target.value)}
                        className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm bg-white"
                      >
                        {arxivFallbackModelOptions.map((model) => (
                          <option key={model} value={model}>
                            {model}
                          </option>
                        ))}
                      </select>
                    </div>
                  )}
                  <Input
                    label="arXiv 链接 / ID"
                    value={arxivInput}
                    onChange={(e) => setArxivInput(e.target.value)}
                    placeholder="例如：https://arxiv.org/abs/2402.13228"
                  />
                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                    <Input
                      label="目标语言"
                      value={arxivTargetLang}
                      onChange={(e) => setArxivTargetLang(e.target.value)}
                      placeholder="中文"
                    />
                    <Input
                      label="并发数 (1-16)"
                      type="number"
                      value={arxivConcurrency}
                      onChange={(e) => setArxivConcurrency(e.target.value)}
                      placeholder="16"
                    />
                  </div>
                  <div>
                    <label className="block text-sm font-medium text-gray-700 mb-1">
                      额外翻译要求（默认已填充）
                    </label>
                    <textarea
                      value={arxivExtraPrompt}
                      onChange={(e) => setArxivExtraPrompt(e.target.value)}
                      rows={7}
                      className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm bg-white focus:outline-none focus:ring-2 focus:ring-indigo-500"
                      placeholder='例如：术语"agent"统一翻译为"智能体"'
                    />
                  </div>
                  <label className="flex items-center gap-2 text-sm text-gray-700">
                    <input
                      type="checkbox"
                      checked={arxivAllowCache}
                      onChange={(e) => setArxivAllowCache(e.target.checked)}
                    />
                    允许缓存（命中同论文历史结果时可快速返回）
                  </label>
                  {!apiConfig.api_key && !hasBackendApiKey && (
                    <div className="text-xs text-yellow-700">
                      未检测到 API Key；请先在后端 .env 配置 OPENAI_API_KEY。
                    </div>
                  )}
                  <div className="text-xs text-gray-500 space-y-2">
                    <div>服务器需安装 LaTeX（pdflatex/xelatex/bibtex），否则仅能完成翻译文本但无法编译 PDF。</div>
                    <details className="rounded-lg border border-gray-200 bg-gray-50 p-2">
                      <summary className="cursor-pointer text-gray-700">Ubuntu 安装/验证命令</summary>
                      <pre className="mt-2 whitespace-pre-wrap break-all text-[11px] text-gray-700">
{`sudo apt update
sudo apt install -y texlive-full latexdiff

pdflatex --version
xelatex --version
bibtex --version
latexdiff --version`}
                      </pre>
                    </details>
                  </div>
                </div>
              )}
              <div className="flex items-center gap-2">
                <Button
                  variant="primary"
                  onClick={handleRun}
                  disabled={
                    loading ||
                    (selectedTool.id === 'bib-lookup' && !bibTitle.trim()) ||
                    (selectedTool.id === 'arxiv-latex-translate' && !arxivInput.trim())
                  }
                >
                  运行工具
                </Button>
                {selectedTool.id === 'arxiv-latex-translate' && arxivJob && ['queued', 'running'].includes(arxivJob.status) && (
                  <Button
                    variant="secondary"
                    onClick={handleCancelArxivJob}
                    disabled={loading}
                  >
                    取消任务
                  </Button>
                )}
              </div>
            </CardContent>
          </Card>

          {selectedTool.id === 'bib-lookup' && (
            <div className="text-xs text-gray-500">
              致谢：该工具的数据与规范化流程参考 rebiber 项目。
              源码链接：
              <span className="ml-1 font-mono">https://github.com/yuchenlin/rebiber</span>
            </div>
          )}
          {selectedTool.id === 'arxiv-latex-translate' && (
            <div className="text-xs text-gray-500">
              参考：gpt_academic 的 ArXiv 论文精细翻译思路（下载源码、分片翻译、LaTeX 编译），
              本项目已按当前后端架构重新实现。
            </div>
          )}

          <Card>
            <CardHeader>
              <CardTitle>执行结果</CardTitle>
            </CardHeader>
            <CardContent className="space-y-3 text-sm">
              {loading && <Loading />}
              {!loading && selectedTool.id === 'bib-lookup' && !bibOutput && bibCandidates.length === 0 && (
                <p className="text-gray-500">暂无结果</p>
              )}
              {!loading && selectedTool.id === 'bib-lookup' && displayBibOutput && (
                <div className="border rounded-lg p-3 bg-gray-50">
                  <div className="mb-1 font-semibold text-gray-900">BibTeX</div>
                  <div className="mb-1 flex items-center justify-between gap-2">
                    <div className="text-xs text-gray-500">bib库原始引用</div>
                    <Button
                      variant="secondary"
                      size="sm"
                      onClick={() => handleCopyBibText(bibOutput || '', 'exact-raw')}
                    >
                      {copiedBibKey === 'exact-raw' ? '已复制' : '复制'}
                    </Button>
                  </div>
                  <pre className="text-gray-700 whitespace-pre-wrap bg-gray-100 border border-gray-200 rounded-lg p-3">
                    {bibOutput}
                  </pre>
                  <div className="mt-3 mb-1 flex items-center justify-between gap-2">
                    <div className="text-xs text-gray-500">标准化展示</div>
                    <Button
                      variant="secondary"
                      size="sm"
                      onClick={() => handleCopyBibText(displayBibOutput, 'exact-normalized')}
                    >
                      {copiedBibKey === 'exact-normalized' ? '已复制' : '复制'}
                    </Button>
                  </div>
                  <pre className="text-gray-700 whitespace-pre-wrap bg-gray-100 border border-gray-200 rounded-lg p-3">
                    {displayBibOutput}
                  </pre>
                </div>
              )}
              {!loading && selectedTool.id === 'bib-lookup' && displayBibCandidates.length > 0 && (
                <div className="space-y-3">
                  <div className="text-gray-700">未找到精确匹配，以下是候选结果：</div>
                  {displayBibCandidates.map((cand, idx) => (
                    <div key={`${cand.title}-${idx}`} className="border rounded-lg p-3">
                      <div className="mb-1 font-semibold text-gray-900">{cand.title}</div>
                      <div className="mb-1 flex items-center justify-between gap-2">
                        <div className="text-xs text-gray-500">bib库原始引用</div>
                        <Button
                          variant="secondary"
                          size="sm"
                          onClick={() => handleCopyBibText(cand.bibtex, `cand-${idx}-raw`)}
                        >
                          {copiedBibKey === `cand-${idx}-raw` ? '已复制' : '复制'}
                        </Button>
                      </div>
                      <pre className="text-gray-700 whitespace-pre-wrap bg-gray-100 border border-gray-200 rounded-lg p-3">
                        {cand.bibtex}
                      </pre>
                      <div className="mt-3 mb-1 flex items-center justify-between gap-2">
                        <div className="text-xs text-gray-500">标准化展示</div>
                        <Button
                          variant="secondary"
                          size="sm"
                          onClick={() => handleCopyBibText(cand.displayBibtex, `cand-${idx}-normalized`)}
                        >
                          {copiedBibKey === `cand-${idx}-normalized` ? '已复制' : '复制'}
                        </Button>
                      </div>
                      <pre className="text-gray-700 whitespace-pre-wrap bg-gray-100 border border-gray-200 rounded-lg p-3">
                        {cand.displayBibtex}
                      </pre>
                    </div>
                  ))}
                </div>
              )}
              {!loading && selectedTool.id === 'arxiv-latex-translate' && !arxivJob && (
                <p className="text-gray-500">{arxivHistory.length > 0 ? '暂无当前任务，下面可查看历史任务。' : '暂无结果'}</p>
              )}
              {!loading && selectedTool.id === 'arxiv-latex-translate' && arxivJob && (
                <div className="space-y-3">
                  <div className="border rounded-lg p-3 bg-gray-50">
                    <div className="font-semibold text-gray-900 mb-1">任务状态</div>
                    <div className="text-gray-700">
                      {arxivJob.status}
                      {arxivJob.paper_id ? ` · arXiv:${arxivJob.paper_id}` : ''}
                    </div>
                    {arxivJob.error && (
                      <div className="mt-2 text-red-600 whitespace-pre-wrap">{arxivJob.error}</div>
                    )}
                    <div className="mt-3">
                      <div className="flex items-center justify-between text-xs text-gray-500">
                        <span>分片进度：{translatedChunks}/{totalChunks}</span>
                        <span>{progressPercent}%</span>
                      </div>
                      <div className="mt-1.5 h-2 w-full rounded-full bg-gray-200 overflow-hidden">
                        <div
                          className="h-full rounded-full bg-emerald-500 transition-all duration-300 ease-out"
                          style={{ width: `${progressPercent}%` }}
                        />
                      </div>
                    </div>
                    {currentJobCost && (
                      <div className="mt-3 text-xs text-gray-600">
                        消耗 {currentJobCost.currency === 'USD' ? '$' : ''}
                        {formatCost5(Number(currentJobCost.total_cost || 0))} (prompt {Number(currentJobCost.prompt_tokens || 0)},
                        completion {Number(currentJobCost.completion_tokens || 0)}, total {Number(currentJobCost.total_tokens || 0)})
                      </div>
                    )}
                  </div>

                  {arxivJob.steps.length > 0 && (
                    <div className="border rounded-lg p-3 bg-white">
                      <div className="font-semibold text-gray-900 mb-2">执行步骤</div>
                      <div className="space-y-2 text-xs max-h-72 overflow-y-auto pr-1">
                        {arxivJob.steps.map((step) => (
                          <div key={step.step_id} className="rounded-lg border border-gray-200 p-2.5 bg-gray-50">
                            <div className="flex items-start gap-2.5">
                              <span
                                className={`mt-0.5 inline-flex h-5 w-5 shrink-0 items-center justify-center rounded-full text-[11px] font-semibold ${
                                  getStepStatusUi(step.status).ring
                                }`}
                              >
                                {getStepStatusUi(step.status).icon}
                              </span>
                              <div className="min-w-0 flex-1">
                                <div className={`break-words ${getStepStatusUi(step.status).text}`}>
                                  {step.message}
                                </div>
                                <div className="mt-1 text-[11px] text-gray-400">
                                  {new Date(step.at).toLocaleTimeString('zh-CN', { hour12: false })}
                                  {step.elapsed_ms ? ` · ${(step.elapsed_ms / 1000).toFixed(1)}s` : ''}
                                </div>
                              </div>
                            </div>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}

                  {arxivJob.artifacts.length > 0 && (
                    <div className="border rounded-lg p-3">
                      <div className="font-semibold text-gray-900 mb-2">下载结果</div>
                      <div className="space-y-2">
                        {arxivJob.artifacts.map((art) => (
                          <a
                            key={art.url}
                            href={getArtifactUrl(art.url)}
                            target="_blank"
                            rel="noreferrer"
                            className="block text-blue-600 hover:underline break-all"
                          >
                            {art.name} ({(art.size_bytes / 1024).toFixed(1)} KB)
                          </a>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              )}
            </CardContent>
          </Card>
          {!loading && selectedTool.id === 'arxiv-latex-translate' && arxivHistory.length > 0 && (
            <Card>
              <CardHeader>
                <CardTitle>任务列表</CardTitle>
              </CardHeader>
              <CardContent className="space-y-2">
                {arxivHistory.map((item) => {
                  const expanded = expandedHistoryJobId === item.job_id
                  const itemCost = parseCostMeta(item.cost_meta)
                  const canCompare = Boolean(
                    (item.translated_pdf_url || getArtifactByName(item, 'translate_zh.pdf')?.url) &&
                      (item.original_pdf_url || item.paper_id)
                  )
                  return (
                    <div key={item.job_id} className="rounded-lg border border-gray-200 overflow-hidden">
                      <button
                        type="button"
                        className="w-full px-3 py-2 text-left bg-gray-50 hover:bg-gray-100 transition"
                        onClick={() => setExpandedHistoryJobId(expanded ? null : item.job_id)}
                      >
                        <div className="flex items-start justify-between gap-3">
                          <div className="min-w-0">
                            <div className="font-medium text-gray-900 break-words">
                              {item.task_name || `arXiv:${item.paper_id || item.canonical_id || item.job_id}`}
                            </div>
                            <div className="text-[11px] text-gray-500 mt-0.5">
                              {item.status} · {new Date(item.updated_at).toLocaleString('zh-CN', { hour12: false })}
                            </div>
                            {itemCost && (
                              <div className="text-[11px] text-gray-500 mt-0.5">
                                消耗 {itemCost.currency === 'USD' ? '$' : ''}{formatCost5(Number(itemCost.total_cost || 0))}
                                {' '}· tokens {Number(itemCost.total_tokens || 0)}
                              </div>
                            )}
                          </div>
                          <div className="text-gray-400 text-sm shrink-0">{expanded ? '收起' : '展开'}</div>
                        </div>
                      </button>
                      {expanded && (
                        <div className="px-3 py-2 bg-white border-t border-gray-200">
                          {canCompare && (
                            <div className="mb-2 flex items-center justify-start">
                              <button
                                type="button"
                                className="text-xs px-2.5 py-1 rounded border border-gray-300 text-gray-700 hover:bg-gray-50"
                                onClick={() => handleOpenCompare(item)}
                              >
                                对照阅读
                              </button>
                            </div>
                          )}
                          {item.artifacts.length === 0 ? (
                            <div className="text-xs text-gray-500">暂无可下载产物</div>
                          ) : (
                            <div className="space-y-1.5">
                              {item.artifacts.map((art) => (
                                <a
                                  key={`${item.job_id}-${art.url}`}
                                  href={getArtifactUrl(art.url)}
                                  target="_blank"
                                  rel="noreferrer"
                                  className="block text-blue-600 hover:underline break-all"
                                >
                                  {art.name} ({(art.size_bytes / 1024).toFixed(1)} KB)
                                </a>
                              ))}
                            </div>
                          )}
                        </div>
                      )}
                    </div>
                  )
                })}
              </CardContent>
            </Card>
          )}
        </div>
      )}
      {compareOpen && (
        <div className="fixed inset-0 z-50 bg-black/60 flex flex-col">
          <div className="bg-white border-b border-gray-200 px-4 py-3 flex items-center justify-between">
            <div className="min-w-0">
              <div className="font-semibold text-gray-900 truncate">对照阅读</div>
              <div className="text-xs text-gray-500 truncate">{compareTitle}</div>
            </div>
            <div className="flex items-center gap-2">
              <span className="hidden sm:inline text-xs text-gray-500">Ctrl/Cmd + 滚轮缩放</span>
              <button
                type="button"
                className={`px-2.5 py-1 rounded border text-xs ${
                  compareScrollSync
                    ? 'border-emerald-400 bg-emerald-50 text-emerald-700'
                    : 'border-gray-300 text-gray-700 hover:bg-gray-50'
                }`}
                onClick={() => setCompareScrollSync((prev) => !prev)}
                title={compareScrollSync ? '关闭联动滚动' : '开启联动滚动'}
              >
                联动滚动：{compareScrollSync ? '开' : '关'}
              </button>
              <button
                type="button"
                className="px-2 py-1 rounded border border-gray-300 text-sm text-gray-700 hover:bg-gray-50 disabled:opacity-50"
                onClick={() => adjustCompareZoom(-COMPARE_ZOOM_STEP)}
                disabled={compareZoom <= COMPARE_ZOOM_MIN}
              >
                -
              </button>
              <button
                type="button"
                className="px-2.5 py-1 rounded border border-gray-300 text-xs text-gray-700 hover:bg-gray-50"
                onClick={() => setCompareZoom(1)}
                title="重置缩放"
              >
                {compareZoomPercent}%
              </button>
              <button
                type="button"
                className="px-2 py-1 rounded border border-gray-300 text-sm text-gray-700 hover:bg-gray-50 disabled:opacity-50"
                onClick={() => adjustCompareZoom(COMPARE_ZOOM_STEP)}
                disabled={compareZoom >= COMPARE_ZOOM_MAX}
              >
                +
              </button>
              <button
                type="button"
                className="px-3 py-1.5 rounded border border-gray-300 text-sm text-gray-700 hover:bg-gray-50"
                onClick={() => setCompareOpen(false)}
              >
                关闭
              </button>
            </div>
          </div>
          <div className="flex-1 min-h-0 grid grid-cols-1 lg:grid-cols-2 gap-0 lg:gap-2 p-2">
            <div className="bg-white rounded-lg border border-gray-200 overflow-hidden flex flex-col min-h-0">
              <div className="px-3 py-2 text-xs font-medium text-gray-700 border-b border-gray-200">原文 PDF</div>
              <div
                ref={leftPdfRef}
                data-compare-side="left"
                onScroll={() => {
                  if (!compareScrollSync) return
                  syncPaneScroll(leftPdfRef.current, rightPdfRef.current)
                }}
                onMouseMove={handleComparePaneMouseMove}
                onMouseLeave={handleComparePaneMouseLeave}
                onClickCapture={handleComparePaneClick}
                onWheel={handleComparePaneWheel}
                className="flex-1 min-h-0 overflow-auto bg-gray-100"
              >
                {compareLeftUrl && (
                  <div className="space-y-3 p-2 w-max min-w-full">
                    <Document
                      file={compareLeftUrl}
                      options={comparePdfOptions}
                      onLoadSuccess={handleLeftPdfLoadSuccess}
                      onLoadError={handleLeftPdfLoadError}
                      loading={null}
                      error={null}
                      noData={null}
                    >
                      {Array.from({ length: compareLeftPages }).map((_, index) => (
                        <div
                          key={`left-page-${index + 1}`}
                          data-compare-page-number={index + 1}
                          className="w-fit mx-auto bg-white border border-gray-200 rounded-sm shadow-sm"
                        >
                          <Page
                            pageNumber={index + 1}
                            width={compareLeftRenderWidth}
                            renderTextLayer
                            renderAnnotationLayer
                            loading={null}
                          />
                        </div>
                      ))}
                    </Document>
                  </div>
                )}
              </div>
              {compareLeftLoading && <div className="px-3 py-2 text-xs text-gray-500 border-t border-gray-200">原文加载中...</div>}
            </div>
            <div className="bg-white rounded-lg border border-gray-200 overflow-hidden flex flex-col min-h-0">
              <div className="px-3 py-2 text-xs font-medium text-gray-700 border-b border-gray-200">译文 PDF</div>
              <div
                ref={rightPdfRef}
                data-compare-side="right"
                onScroll={() => {
                  if (!compareScrollSync) return
                  syncPaneScroll(rightPdfRef.current, leftPdfRef.current)
                }}
                onMouseMove={handleComparePaneMouseMove}
                onMouseLeave={handleComparePaneMouseLeave}
                onClickCapture={handleComparePaneClick}
                onWheel={handleComparePaneWheel}
                className="flex-1 min-h-0 overflow-auto bg-gray-100"
              >
                {compareRightUrl && (
                  <div className="space-y-3 p-2 w-max min-w-full">
                    <Document
                      file={compareRightUrl}
                      options={comparePdfOptions}
                      onLoadSuccess={handleRightPdfLoadSuccess}
                      onLoadError={handleRightPdfLoadError}
                      loading={null}
                      error={null}
                      noData={null}
                    >
                      {Array.from({ length: compareRightPages }).map((_, index) => (
                        <div
                          key={`right-page-${index + 1}`}
                          data-compare-page-number={index + 1}
                          className="w-fit mx-auto bg-white border border-gray-200 rounded-sm shadow-sm"
                        >
                          <Page
                            pageNumber={index + 1}
                            width={compareRightRenderWidth}
                            renderTextLayer
                            renderAnnotationLayer
                            loading={null}
                          />
                        </div>
                      ))}
                    </Document>
                  </div>
                )}
              </div>
              {compareRightLoading && <div className="px-3 py-2 text-xs text-gray-500 border-t border-gray-200">译文加载中...</div>}
            </div>
          </div>
          {compareError && (
            <div className="px-4 py-2 bg-white border-t border-gray-200 text-xs text-red-600">{compareError}</div>
          )}
          {compareCitationHover && (
            <div
              ref={hoverPanelRef}
              onMouseEnter={clearHoverHideTimer}
              onMouseLeave={scheduleHoverHide}
              className="fixed z-[70] w-[520px] max-w-[calc(100vw-24px)] rounded border border-emerald-300 bg-emerald-50 px-2.5 py-2 text-xs text-emerald-900 shadow-lg pointer-events-auto"
              style={{ left: compareCitationHover.x, top: compareCitationHover.y }}
            >
              <div className="flex items-center justify-between gap-2 mb-1">
                <div className="font-semibold">{compareCitationHover.key}</div>
                <button
                  type="button"
                  className="text-[11px] px-1.5 py-0.5 rounded border border-emerald-400 text-emerald-800 hover:bg-emerald-100"
                  onClick={() => {
                    setCompareCitationPinned({ key: compareCitationHover.key, text: compareCitationHover.text })
                    setCompareCitationHover(null)
                    clearHoverHideTimer()
                  }}
                >
                  固定
                </button>
              </div>
              <div className="max-h-72 overflow-auto whitespace-pre-wrap break-words select-text">
                {compareCitationHover.text}
              </div>
            </div>
          )}
          {compareCitationPinned && (
            <div className="fixed right-4 bottom-4 z-[71] max-w-xl rounded-lg border border-emerald-300 bg-white shadow-xl">
              <div className="flex items-center justify-between gap-2 border-b border-emerald-200 px-3 py-2">
                <div className="text-xs font-semibold text-emerald-800 break-all">{compareCitationPinned.key}</div>
                <button
                  type="button"
                  className="text-xs px-2 py-1 rounded border border-gray-300 text-gray-600 hover:bg-gray-50"
                  onClick={() => {
                    setCompareCitationPinned(null)
                    setCompareCitationHover(null)
                  }}
                >
                  关闭
                </button>
              </div>
              <div className="px-3 py-2 text-xs text-gray-700 max-h-80 overflow-auto whitespace-pre-wrap break-words select-text">
                {compareCitationPinned.text}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
