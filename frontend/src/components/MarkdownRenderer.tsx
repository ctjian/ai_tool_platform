import React, { useCallback, useEffect, useMemo, useState } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import remarkMath from 'remark-math'
import rehypeKatex from 'rehype-katex'
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter'
import a11yOneLight from 'react-syntax-highlighter/dist/esm/styles/prism/a11y-one-light'
import { Copy } from 'lucide-react'
import { addToast } from './ui'
import 'katex/dist/katex.min.css'

type MarkdownPreset = 'chat' | 'notebook'

interface MarkdownRendererProps {
  content: string
  preset?: MarkdownPreset
  normalizeLatexDelimiters?: boolean
  enableCopyCode?: boolean
}

let mermaidInitialized = false

const MermaidBlock: React.FC<{ chart: string }> = ({ chart }) => {
  const [svg, setSvg] = useState('')
  const [renderError, setRenderError] = useState('')

  useEffect(() => {
    let cancelled = false
    const render = async () => {
      try {
        const mermaid = (await import('mermaid')).default
        if (!mermaidInitialized) {
          mermaid.initialize({
            startOnLoad: false,
            securityLevel: 'loose',
            theme: 'default',
          })
          mermaidInitialized = true
        }
        const id = `mermaid-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`
        const result = await mermaid.render(id, chart)
        if (!cancelled) {
          setSvg(result.svg)
          setRenderError('')
        }
      } catch (error: any) {
        if (!cancelled) {
          setSvg('')
          setRenderError(error?.message || 'Mermaid 渲染失败')
        }
      }
    }
    void render()
    return () => {
      cancelled = true
    }
  }, [chart])

  if (renderError) {
    return (
      <div className="my-3 overflow-hidden rounded-2xl border border-red-200 bg-red-50">
        <div className="border-b border-red-200 px-4 py-2 text-xs text-red-700">Mermaid 渲染失败，已回退源码</div>
        <pre className="whitespace-pre-wrap break-words px-4 py-3 text-xs text-red-700">{chart}</pre>
      </div>
    )
  }

  if (!svg) {
    return <div className="my-3 rounded-2xl border border-gray-200 bg-gray-50 px-4 py-3 text-sm text-gray-600">正在渲染 Mermaid 图...</div>
  }

  return (
    <div className="my-3 overflow-auto rounded-2xl border border-gray-200 bg-gray-50 px-3 py-3">
      <div className="[&>svg]:max-w-full" dangerouslySetInnerHTML={{ __html: svg }} />
    </div>
  )
}

const normalizeLatexContent = (content: string): string => {
  let next = String(content || '')
  next = next.replace(/\\\[([\s\S]*?)\\\]/g, (_match, p1) => `$$${p1}$$`)
  next = next.replace(/\\\(([\s\S]*?)\\\)/g, (_match, p1) => `$${p1}$`)
  return next
}

const articleStyles = {
  h1: 'mb-3 mt-6 text-3xl font-semibold tracking-tight text-gray-900 first:mt-0',
  h2: 'mb-2 mt-5 border-b border-gray-200 pb-1 text-2xl font-semibold text-gray-900',
  h3: 'mb-2 mt-4 text-xl font-semibold text-gray-900',
  h4: 'mb-2 mt-4 text-lg font-semibold text-gray-900',
  p: 'my-3 leading-7 text-gray-800',
  ul: 'my-3 list-disc space-y-1.5 pl-6 text-gray-800 marker:text-gray-500',
  ol: 'my-3 list-decimal space-y-1.5 pl-6 text-gray-800 marker:text-gray-500',
  li: 'leading-7',
  blockquote: 'my-4 rounded-r-lg border-l-4 border-gray-300 bg-gray-50 py-2.5 pl-3.5 text-gray-700',
  codeBlockWrap: 'my-4 overflow-hidden rounded-xl border border-gray-200 bg-gray-50 shadow-sm',
  codeHeader: 'flex items-center justify-between border-b border-gray-200 px-3 py-1.5 text-[11px] uppercase tracking-wide text-gray-500',
  codeBody: 'px-3 pb-3 pt-2',
  inlineCode: 'rounded-md border border-gray-200 bg-gray-50 px-1.5 py-0.5 text-[0.9em] text-gray-900',
  link: 'text-sky-700 underline decoration-sky-300 underline-offset-2 hover:text-sky-800',
  tableWrap: 'my-4 overflow-x-auto rounded-lg border border-gray-200',
  table: 'w-full border-collapse text-sm',
  thead: 'bg-gray-50 text-gray-700',
  th: 'border-b border-gray-200 px-3 py-2 text-left font-semibold',
  td: 'border-b border-gray-100 px-3 py-2 align-top text-gray-700',
  strong: 'font-semibold text-gray-900',
  hr: 'my-5 border-gray-200',
} as const

const presetStyles: Record<MarkdownPreset, typeof articleStyles> = {
  notebook: articleStyles,
  chat: articleStyles,
}

export const MarkdownRenderer: React.FC<MarkdownRendererProps> = ({
  content,
  preset = 'notebook',
  normalizeLatexDelimiters = false,
  enableCopyCode = true,
}) => {
  const styles = presetStyles[preset]
  const text = useMemo(
    () => (normalizeLatexDelimiters ? normalizeLatexContent(content) : String(content || '')),
    [content, normalizeLatexDelimiters]
  )
  const handleCopyCode = useCallback(async (code: string) => {
    try {
      if (navigator.clipboard && window.isSecureContext) {
        await navigator.clipboard.writeText(code)
      } else {
        const textarea = document.createElement('textarea')
        textarea.value = code
        textarea.setAttribute('readonly', '')
        textarea.style.position = 'fixed'
        textarea.style.top = '-9999px'
        document.body.appendChild(textarea)
        textarea.select()
        document.execCommand('copy')
        document.body.removeChild(textarea)
      }
      addToast('代码已复制到剪贴板', 'success')
    } catch {
      addToast('复制代码失败，请手动复制', 'error')
    }
  }, [])

  const markdownComponents = useMemo(
    () => ({
      h1: ({ children }: any) => <h1 className={styles.h1}>{children}</h1>,
      h2: ({ children }: any) => <h2 className={styles.h2}>{children}</h2>,
      h3: ({ children }: any) => <h3 className={styles.h3}>{children}</h3>,
      h4: ({ children }: any) => <h4 className={styles.h4}>{children}</h4>,
      p: ({ children }: any) => <p className={styles.p}>{children}</p>,
      ul: ({ children }: any) => <ul className={styles.ul}>{children}</ul>,
      ol: ({ children }: any) => <ol className={styles.ol}>{children}</ol>,
      li: ({ children }: any) => <li className={styles.li}>{children}</li>,
      blockquote: ({ children }: any) => <blockquote className={styles.blockquote}>{children}</blockquote>,
      code: ({ inline, className, children, ...props }: any) => {
        const match = /language-([\w-]+)/.exec(className || '')
        const language = (match?.[1] || '').toLowerCase()
        const displayLanguage = language || 'code'
        const code = String(children || '').replace(/\n$/, '')

        if (!inline && language === 'mermaid') {
          return <MermaidBlock chart={code} />
        }

        if (!inline) {
          return (
            <div className={styles.codeBlockWrap}>
              <div className={styles.codeHeader}>
                <span>{displayLanguage}</span>
                {enableCopyCode ? (
                  <button
                    type="button"
                    onClick={() => void handleCopyCode(code)}
                    className="inline-flex items-center gap-1 text-gray-500 hover:text-gray-700"
                    title="复制代码"
                  >
                    <Copy size={14} />
                    复制代码
                  </button>
                ) : null}
              </div>
              <div className={styles.codeBody}>
                <SyntaxHighlighter
                  style={a11yOneLight as any}
                  language={language || undefined}
                  PreTag="div"
                  wrapLongLines
                  codeTagProps={{
                    style: {
                      background: 'transparent',
                      whiteSpace: 'pre-wrap',
                      wordBreak: 'break-word',
                    },
                  }}
                  customStyle={{
                    background: 'transparent',
                    margin: 0,
                    padding: 0,
                    whiteSpace: 'pre-wrap',
                    wordBreak: 'break-word',
                    overflowX: 'visible',
                    fontSize: '13px',
                    lineHeight: '1.6',
                  }}
                  {...props}
                >
                  {code}
                </SyntaxHighlighter>
              </div>
            </div>
          )
        }

        return (
          <code className={styles.inlineCode} {...props}>
            {children}
          </code>
        )
      },
      a: ({ href, children }: any) => (
        <a href={href} target="_blank" rel="noreferrer" className={styles.link}>
          {children}
        </a>
      ),
      table: ({ children }: any) => (
        <div className={styles.tableWrap}>
          <table className={styles.table}>{children}</table>
        </div>
      ),
      thead: ({ children }: any) => <thead className={styles.thead}>{children}</thead>,
      th: ({ children }: any) => <th className={styles.th}>{children}</th>,
      td: ({ children }: any) => <td className={styles.td}>{children}</td>,
      strong: ({ children }: any) => <strong className={styles.strong}>{children}</strong>,
      hr: () => <hr className={styles.hr} />,
    }),
    [enableCopyCode, handleCopyCode, styles]
  )

  return (
    <ReactMarkdown remarkPlugins={[remarkGfm, remarkMath]} rehypePlugins={[rehypeKatex]} components={markdownComponents}>
      {text}
    </ReactMarkdown>
  )
}

export default MarkdownRenderer
