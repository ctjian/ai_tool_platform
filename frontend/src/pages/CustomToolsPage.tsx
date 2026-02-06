import { useMemo, useState } from 'react'
import { Card, CardContent, CardHeader, CardTitle, Input, Button, Loading } from '../components/ui'
import apiClient from '../api/client'

interface CustomTool {
  id: string
  name: string
  description: string
  icon: string
}

interface DemoResponse {
  result: number
}

export const CustomToolsPage = () => {
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

  const selectedTool = tools.find((t) => t.id === selectedToolId) || null

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
      }
    } catch (error) {
      console.error('Failed to run custom tool:', error)
      setOutput(null)
      setBibOutput(null)
      setBibCandidates([])
    } finally {
      setLoading(false)
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
              <div>
                <Button
                  variant="primary"
                  onClick={handleRun}
                  disabled={loading || (selectedTool.id === 'bib-lookup' && !bibTitle.trim())}
                >
                  运行工具
                </Button>
              </div>
            </CardContent>
          </Card>

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
              {!loading && selectedTool.id === 'bib-lookup' && bibOutput && (
                <div className="border rounded-lg p-3 bg-gray-50">
                  <div className="font-semibold text-gray-900 mb-1">BibTeX</div>
                  <pre className="text-gray-700 whitespace-pre-wrap bg-gray-100 border border-gray-200 rounded-lg p-3">
                    {bibOutput}
                  </pre>
                </div>
              )}
              {!loading && selectedTool.id === 'bib-lookup' && bibCandidates.length > 0 && (
                <div className="space-y-3">
                  <div className="text-gray-700">未找到精确匹配，以下是候选结果：</div>
                  {bibCandidates.map((cand, idx) => (
                    <div key={`${cand.title}-${idx}`} className="border rounded-lg p-3">
                      <div className="font-semibold text-gray-900 mb-1">{cand.title}</div>
                      <pre className="text-gray-700 whitespace-pre-wrap bg-gray-100 border border-gray-200 rounded-lg p-3">
                        {cand.bibtex}
                      </pre>
                    </div>
                  ))}
                </div>
              )}
            </CardContent>
          </Card>
        </div>
      )}
    </div>
  )
}
