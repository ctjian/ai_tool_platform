import { useEffect } from 'react'
import { Navigate, Route, Routes, useLocation, useNavigate } from 'react-router-dom'
import { useAppStore } from './store/app'
import apiClient from './api/client'
import Sidebar from './components/Sidebar'
import ChatWindow from './components/ChatWindow'
import { ToastContainer } from './components/ui'
import { SettingsPage } from './pages/SettingsPage'
import { ToolsExplorer } from './pages/ToolsExplorer'
import { CustomToolsPage } from './pages/CustomToolsPage'
import { AiNotebookPage } from './pages/AiNotebookPage'

type PageKey = 'chat' | 'settings' | 'explorer' | 'custom-tools' | 'notebook'

const PAGE_PATHS: Record<PageKey, string> = {
  chat: '/',
  settings: '/settings',
  explorer: '/explorer',
  'custom-tools': '/custom-tools',
  notebook: '/notebook',
}

const normalizePathname = (pathname: string) => {
  if (pathname.length > 1 && pathname.endsWith('/')) {
    return pathname.slice(0, -1)
  }
  return pathname
}

const getPageFromPath = (pathname: string): PageKey => {
  const normalized = normalizePathname(pathname)
  if (normalized === '/' || normalized === '/chat') return 'chat'
  if (normalized.startsWith(PAGE_PATHS.settings)) return 'settings'
  if (normalized.startsWith(PAGE_PATHS.explorer)) return 'explorer'
  if (normalized.startsWith(PAGE_PATHS['custom-tools'])) return 'custom-tools'
  if (normalized.startsWith(PAGE_PATHS.notebook)) return 'notebook'
  return 'chat'
}

function App() {
  const { 
    setCategories, 
    setTools,
    setLoading,
    setCurrentTool,
    setConversations,
    setCurrentConversation,
    apiConfig,
    setApiConfig,
    setHasBackendApiKey,
    setAvailableModels,
    setAvailableModelGroups,
  } = useAppStore()

  const location = useLocation()
  const navigate = useNavigate()
  const currentPage = getPageFromPath(location.pathname)

  useEffect(() => {
    const loadInitialData = async () => {
      try {
        setLoading(true)
        
        // 加载后端默认配置
        try {
          const defaultConfigRes = await apiClient.getDefaultConfig()
          const { has_api_key, base_url, models, model_groups } = defaultConfigRes.data
          
          // 记录后端是否有 API key
          setHasBackendApiKey(has_api_key)

          if (Array.isArray(model_groups) && model_groups.length > 0) {
            setAvailableModelGroups(model_groups)
            const flat = model_groups.flatMap((g: any) => g.models || [])
            if (flat.length > 0) {
              setAvailableModels(flat)
            }
          } else {
            setAvailableModelGroups([])
            if (Array.isArray(models) && models.length > 0) {
              setAvailableModels(models)
            } else if (apiConfig.model) {
              setAvailableModels([apiConfig.model])
            }
          }
          
          // 如果前端localStorage没有配置，使用后端默认值
          if (!apiConfig.api_key && has_api_key) {
            // 不需要真的设置 api_key，只需要标记后端有配置
            // 后端会自动使用 .env 中的配置
          }
          if (!localStorage.getItem('apiConfigBaseUrl')) {
            setApiConfig({ base_url })
          }
        } catch (error) {
          console.error('Failed to load default config:', error)
        }
        
        // 加载分类
        const catRes = await apiClient.getCategories()
        setCategories(catRes.data.categories)
        
        // 加载工具
        const toolRes = await apiClient.getTools()
        setTools(toolRes.data.tools)
        
        // 加载所有对话历史
        const convRes = await apiClient.getConversations()
        const conversations = convRes.data.conversations || []
        setConversations(conversations)
        
        // 主页默认打开最近的一个对话
        if (conversations.length > 0) {
          setCurrentConversation(conversations[0])
          setCurrentTool(null)
        }
        
      } catch (error) {
        console.error('Failed to load initial data:', error)
      } finally {
        setLoading(false)
      }
    }
    
    loadInitialData()
  }, [setCategories, setTools, setConversations, setLoading, setCurrentConversation, setCurrentTool])

  const handlePageChange = (page: PageKey) => {
    const nextPath = PAGE_PATHS[page]
    if (location.pathname !== nextPath) {
      navigate(nextPath)
    }
    // 切换到设置、提示词广场或自定义工具时，清除当前工具和对话以显示对应页面
    if (page === 'settings' || page === 'explorer' || page === 'custom-tools' || page === 'notebook') {
      setCurrentTool(null)
      setCurrentConversation(null)
    }
  }

  return (
    <div className="h-screen w-screen flex bg-white">
      <ToastContainer position="top-right" />
      
      {/* 左侧固定边栏 */}
      <Sidebar 
        onPageChange={handlePageChange}
        currentPage={currentPage}
      />
      
      {/* 右侧内容区 */}
      <div className="flex-1 flex flex-col overflow-hidden min-h-0">
        <Routes>
          <Route path="/" element={<ChatWindow />} />
          <Route path="/chat" element={<Navigate to="/" replace />} />
          <Route
            path="/settings"
            element={
              <div className="flex-1 overflow-y-auto bg-white p-6">
                <SettingsPage />
              </div>
            }
          />
          <Route
            path="/explorer"
            element={
              <div className="flex-1 overflow-y-auto bg-white p-6">
                <ToolsExplorer />
              </div>
            }
          />
          <Route
            path="/custom-tools"
            element={
              <div className="flex-1 overflow-y-auto bg-white p-6">
                <CustomToolsPage />
              </div>
            }
          />
          <Route
            path="/notebook"
            element={
              <div className="flex-1 overflow-y-auto bg-white p-6">
                <AiNotebookPage />
              </div>
            }
          />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </div>
    </div>
  )
}

export default App
