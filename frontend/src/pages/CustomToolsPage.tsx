// Review note:
// - 新增“Arxiv论文精细翻译”自定义工具页逻辑（提交任务、轮询状态、下载产物）。
import { useEffect, useMemo, useRef, useState } from 'react'
import { Card, CardContent, CardHeader, CardTitle, Input, Button, Loading, addToast } from '../components/ui'
import apiClient from '../api/client'
import { useAppStore } from '../store/app'
import { ArxivTranslateHistoryItem, ArxivTranslateJob } from '../types/api'

interface CustomTool {
  id: string
  name: string
  description: string
  icon: string
}

interface DemoResponse {
  result: number
}

const ARXIV_DEFAULT_EXTRA_PROMPT = [
  'If the term "agent" appears, translate it as "智能体"; "policy" as "策略"; "reward model" as "奖励模型"; "alignment" as "对齐".',
  "Keep abbreviations unchanged at first mention, and append Chinese in parentheses (e.g., Distributionally Robust Optimization (DRO，分布鲁棒优化)).",
  "Keep model names and benchmark names in English (e.g., GPT, Llama, MMLU, HellaSwag).",
  "Do not modify LaTeX commands, equations, citation keys, labels, refs, or environment names.",
  "Keep all numbers, percentages, units, and variable symbols unchanged.",
  "Use formal and concise academic Chinese; avoid colloquial wording.",
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

let pdfJsLibPromise: Promise<any> | null = null

const loadPdfJsLib = async () => {
  if ((window as any).pdfjsLib) {
    return (window as any).pdfjsLib
  }
  if (pdfJsLibPromise) {
    return pdfJsLibPromise
  }
  pdfJsLibPromise = new Promise((resolve, reject) => {
    const script = document.createElement('script')
    script.src = 'https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.min.js'
    script.async = true
    script.onload = () => {
      const lib = (window as any).pdfjsLib
      if (!lib) {
        reject(new Error('pdf.js 加载失败'))
        return
      }
      lib.GlobalWorkerOptions.workerSrc =
        'https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.worker.min.js'
      resolve(lib)
    }
    script.onerror = () => reject(new Error('pdf.js 脚本加载失败'))
    document.body.appendChild(script)
  })
  return pdfJsLibPromise
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
        id: 'demo-text-pipeline',
        name: '测试自定义工具',
        description: '输入一个值，后端返回该值 + 1',
        icon: '🧪',
      },
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
  const [inputValue, setInputValue] = useState('1')
  const [bibTitle, setBibTitle] = useState('')
  const [bibShorten, setBibShorten] = useState(false)
  const [bibRemoveFields, setBibRemoveFields] = useState('url,biburl,address,publisher')
  const [loading, setLoading] = useState(false)
  const [output, setOutput] = useState<DemoResponse | null>(null)
  const [bibOutput, setBibOutput] = useState<string | null>(null)
  const [bibCandidates, setBibCandidates] = useState<{ title: string; bibtex: string }[]>([])
  const [copiedBibKey, setCopiedBibKey] = useState<string | null>(null)
  const [arxivInput, setArxivInput] = useState('')
  const [arxivTargetLang, setArxivTargetLang] = useState('中文')
  const [arxivExtraPrompt, setArxivExtraPrompt] = useState(ARXIV_DEFAULT_EXTRA_PROMPT)
  const [arxivAllowCache, setArxivAllowCache] = useState(true)
  const [arxivConcurrency, setArxivConcurrency] = useState('16')
  const [arxivModelGroup, setArxivModelGroup] = useState('')
  const [arxivModel, setArxivModel] = useState('')
  const [arxivJob, setArxivJob] = useState<ArxivTranslateJob | null>(null)
  const [arxivHistory, setArxivHistory] = useState<ArxivTranslateHistoryItem[]>([])
  const [expandedHistoryJobId, setExpandedHistoryJobId] = useState<string | null>(null)
  const [compareOpen, setCompareOpen] = useState(false)
  const [compareLeftUrl, setCompareLeftUrl] = useState('')
  const [compareRightUrl, setCompareRightUrl] = useState('')
  const [compareTitle, setCompareTitle] = useState('')
  const [compareError, setCompareError] = useState('')
  const [compareLeftLoading, setCompareLeftLoading] = useState(false)
  const [compareRightLoading, setCompareRightLoading] = useState(false)
  const leftPdfRef = useRef<HTMLDivElement | null>(null)
  const rightPdfRef = useRef<HTMLDivElement | null>(null)
  const syncLockRef = useRef(false)
  const renderTokenRef = useRef(0)

  const selectedTool = tools.find((t) => t.id === selectedToolId) || null
  const modelGroupOptions = availableModelGroups || []
  const fallbackModelOptions = availableModels || []
  const currentGroupModels = useMemo(() => {
    if (!modelGroupOptions.length) return []
    const group = modelGroupOptions.find((g) => g.name === arxivModelGroup)
    return group?.models || []
  }, [modelGroupOptions, arxivModelGroup])
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
    const preferredModel = ARXIV_DEFAULT_MODEL
    const currentModel = arxivModel || preferredModel || apiConfig.model
    if (modelGroupOptions.length > 0) {
      const matchedGroup =
        modelGroupOptions.find((g) => g.models.includes(currentModel)) ||
        modelGroupOptions.find((g) => g.models.includes(apiConfig.model))
      const nextGroup = matchedGroup?.name || modelGroupOptions[0]?.name || ''
      if (!arxivModelGroup || !modelGroupOptions.some((g) => g.name === arxivModelGroup)) {
        setArxivModelGroup(nextGroup)
        return
      }
      const groupModels = modelGroupOptions.find((g) => g.name === arxivModelGroup)?.models || []
      if (!arxivModel || !groupModels.includes(arxivModel)) {
        const nextModel = groupModels.includes(preferredModel)
          ? preferredModel
          : groupModels.includes(apiConfig.model)
            ? apiConfig.model
            : (groupModels.includes(currentModel) ? currentModel : groupModels[0])
        setArxivModel(nextModel || '')
      }
      return
    }

    if ((!arxivModel || !fallbackModelOptions.includes(arxivModel)) && fallbackModelOptions.length > 0) {
      const next = fallbackModelOptions.includes(preferredModel)
        ? preferredModel
        : fallbackModelOptions.includes(apiConfig.model)
          ? apiConfig.model
          : (fallbackModelOptions.includes(currentModel) ? currentModel : fallbackModelOptions[0])
      setArxivModel(next || '')
    }
  }, [
    apiConfig.model,
    arxivModel,
    arxivModelGroup,
    fallbackModelOptions,
    modelGroupOptions,
  ])

  const handleRun = async () => {
    if (!selectedTool) return
    try {
      setLoading(true)
      if (selectedTool.id === 'demo-text-pipeline') {
        const parsed = Number(inputValue)
        if (!Number.isFinite(parsed)) {
          return
        }
        const res = await apiClient.runCustomToolDemo(parsed)
        setOutput(res.data)
      } else if (selectedTool.id === 'bib-lookup') {
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
          model: arxivModel || ARXIV_DEFAULT_MODEL || apiConfig.model || undefined,
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
      setOutput(null)
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

  const getArtifactUrl = (url: string) => {
    if (!url) return '#'
    if (/^https?:\/\//i.test(url)) return url
    return url.startsWith('/') ? url : `/${url}`
  }

  const getArtifactByName = (item: ArxivTranslateHistoryItem, name: string) =>
    (item.artifacts || []).find((a) => a.name === name)

  const renderPdfToPane = async (url: string, container: HTMLDivElement, token: number) => {
    const lib = await loadPdfJsLib()
    if (token !== renderTokenRef.current) return

    container.innerHTML = ''
    const content = document.createElement('div')
    content.className = 'space-y-2 p-2'
    container.appendChild(content)

    const loadingTask = lib.getDocument({ url, withCredentials: false })
    const pdf = await loadingTask.promise
    if (token !== renderTokenRef.current) return

    const paneWidth = Math.max(320, container.clientWidth - 16)
    for (let pageNo = 1; pageNo <= pdf.numPages; pageNo += 1) {
      if (token !== renderTokenRef.current) return
      const page = await pdf.getPage(pageNo)
      const viewport = page.getViewport({ scale: 1 })
      const scale = paneWidth / viewport.width
      const scaled = page.getViewport({ scale })
      const dpr = Math.max(1, window.devicePixelRatio || 1)

      const canvas = document.createElement('canvas')
      canvas.width = Math.floor(scaled.width * dpr)
      canvas.height = Math.floor(scaled.height * dpr)
      canvas.style.width = `${scaled.width}px`
      canvas.style.height = `${scaled.height}px`
      canvas.className = 'mx-auto bg-white shadow-sm'
      const ctx = canvas.getContext('2d')
      if (!ctx) continue
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
      await page.render({ canvasContext: ctx, viewport: scaled }).promise
      content.appendChild(canvas)
    }
  }

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
    setCompareOpen(true)
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
    if (!compareOpen) return
    if (!leftPdfRef.current || !rightPdfRef.current) return
    if (!compareLeftUrl || !compareRightUrl) return

    const token = renderTokenRef.current + 1
    renderTokenRef.current = token
    setCompareError('')
    setCompareLeftLoading(true)
    setCompareRightLoading(true)

    renderPdfToPane(compareLeftUrl, leftPdfRef.current, token)
      .catch(() => {
        setCompareError('原文 PDF 加载失败，请稍后重试。')
      })
      .finally(() => {
        if (token === renderTokenRef.current) setCompareLeftLoading(false)
      })

    renderPdfToPane(compareRightUrl, rightPdfRef.current, token)
      .catch(() => {
        setCompareError((prev) => prev || '译文 PDF 加载失败，请稍后重试。')
      })
      .finally(() => {
        if (token === renderTokenRef.current) setCompareRightLoading(false)
      })

    return () => {
      renderTokenRef.current += 1
    }
  }, [compareOpen, compareLeftUrl, compareRightUrl])

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
        <p className="text-gray-600 mt-2">展示一个多步流程的自定义工具示例</p>
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
                  setOutput(null)
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
                setOutput(null)
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
              {selectedTool.id === 'demo-text-pipeline' && (
                <Input
                  label="输入值"
                  type="number"
                  value={inputValue}
                  onChange={(e) => setInputValue(e.target.value)}
                  placeholder="输入一个数字"
                />
              )}
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
                  {modelGroupOptions.length > 0 ? (
                    <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                      <div>
                        <label className="block text-sm font-medium text-gray-700 mb-1">模型分组</label>
                        <select
                          value={arxivModelGroup}
                          onChange={(e) => {
                            const groupName = e.target.value
                            setArxivModelGroup(groupName)
                            const models = modelGroupOptions.find((g) => g.name === groupName)?.models || []
                            setArxivModel(models[0] || '')
                          }}
                          className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm bg-white"
                        >
                          {modelGroupOptions.map((group) => (
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
                        {fallbackModelOptions.map((model) => (
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
                      未检测到 API Key；请先在设置页配置，或在后端 .env 配置 OPENAI_API_KEY。
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
              {!loading && selectedTool.id === 'demo-text-pipeline' && !output && (
                <p className="text-gray-500">暂无结果</p>
              )}
              {!loading && selectedTool.id === 'demo-text-pipeline' && output && (
                <div className="border rounded-lg p-3 bg-gray-50">
                  <div className="font-semibold text-gray-900 mb-1">最终结果</div>
                  <div className="text-gray-700 whitespace-pre-wrap">{output.result}</div>
                </div>
              )}
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
                          </div>
                          <div className="text-gray-400 text-sm shrink-0">{expanded ? '收起' : '展开'}</div>
                        </div>
                      </button>
                      {expanded && (
                        <div className="px-3 py-2 bg-white border-t border-gray-200">
                          <div className="mb-2 flex items-center justify-end">
                            <button
                              type="button"
                              className={`text-xs px-2.5 py-1 rounded border ${
                                canCompare
                                  ? 'border-gray-300 text-gray-700 hover:bg-gray-50'
                                  : 'border-gray-200 text-gray-400 cursor-not-allowed'
                              }`}
                              disabled={!canCompare}
                              onClick={() => handleOpenCompare(item)}
                            >
                              对照阅读
                            </button>
                          </div>
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
            <button
              type="button"
              className="px-3 py-1.5 rounded border border-gray-300 text-sm text-gray-700 hover:bg-gray-50"
              onClick={() => setCompareOpen(false)}
            >
              关闭
            </button>
          </div>
          <div className="flex-1 min-h-0 grid grid-cols-1 lg:grid-cols-2 gap-0 lg:gap-2 p-2">
            <div className="bg-white rounded-lg border border-gray-200 overflow-hidden flex flex-col min-h-0">
              <div className="px-3 py-2 text-xs font-medium text-gray-700 border-b border-gray-200">原文 PDF</div>
              <div
                ref={leftPdfRef}
                onScroll={() => syncPaneScroll(leftPdfRef.current, rightPdfRef.current)}
                className="flex-1 min-h-0 overflow-auto bg-gray-100"
              />
              {compareLeftLoading && <div className="px-3 py-2 text-xs text-gray-500 border-t border-gray-200">原文加载中...</div>}
            </div>
            <div className="bg-white rounded-lg border border-gray-200 overflow-hidden flex flex-col min-h-0">
              <div className="px-3 py-2 text-xs font-medium text-gray-700 border-b border-gray-200">译文 PDF</div>
              <div
                ref={rightPdfRef}
                onScroll={() => syncPaneScroll(rightPdfRef.current, leftPdfRef.current)}
                className="flex-1 min-h-0 overflow-auto bg-gray-100"
              />
              {compareRightLoading && <div className="px-3 py-2 text-xs text-gray-500 border-t border-gray-200">译文加载中...</div>}
            </div>
          </div>
          {compareError && (
            <div className="px-4 py-2 bg-white border-t border-gray-200 text-xs text-red-600">{compareError}</div>
          )}
        </div>
      )}
    </div>
  )
}
