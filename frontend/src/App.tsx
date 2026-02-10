import { useEffect, useState } from 'react'
import { useAppStore } from './store/app'
import apiClient from './api/client'
import Sidebar from './components/Sidebar'
import ChatWindow from './components/ChatWindow'
import { ToastContainer } from './components/ui'
import { SettingsPage } from './pages/SettingsPage'
import { ToolsExplorer } from './pages/ToolsExplorer'
import { CustomToolsPage } from './pages/CustomToolsPage'

function App() {
  const { 
    setCategories, 
    setTools,
    setLoading,
    currentTool,
    setCurrentTool,
    setConversations,
    setCurrentConversation,
    currentConversation,
    apiConfig,
    setApiConfig,
    setHasBackendApiKey,
    setAvailableModels,
    setAvailableModelGroups,
  } = useAppStore()

  const [currentPage, setCurrentPage] = useState<'chat' | 'settings' | 'explorer' | 'custom-tools'>('chat')

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

  const handlePageChange = (page: 'chat' | 'settings' | 'explorer' | 'custom-tools') => {
    setCurrentPage(page)
    // 切换到设置、提示词广场或自定义工具时，清除当前工具和对话以显示对应页面
    if (page === 'settings' || page === 'explorer' || page === 'custom-tools') {
      setCurrentTool(null)
      setCurrentConversation(null)
    }
  }

  const renderRightContent = () => {
    // chat 模式 - 最高优先级
    if (currentPage === 'chat') {
      return <ChatWindow />;
    }

    // 有工具或有对话时显示聊天窗口
    if (currentTool || currentConversation) {
      return <ChatWindow />
    }

    if (currentPage === 'settings') {
      return (
        <div className="flex-1 overflow-y-auto bg-white p-6">
          <SettingsPage />
        </div>
      )
    }
    
    if (currentPage === 'explorer') {
      return (
        <div className="flex-1 overflow-y-auto bg-white p-6">
          <ToolsExplorer />
        </div>
      )
    }
    
    if (currentPage === 'custom-tools') {
      return (
        <div className="flex-1 overflow-y-auto bg-white p-6">
          <CustomToolsPage />
        </div>
      )
    }

    // 默认：显示欢迎页面
    return (
      <div className="flex-1 flex items-center justify-center bg-white">
        <div className="text-center">
          <div className="text-6xl mb-4">�</div>
          <h2 className="text-2xl font-bold mb-2">欢迎使用AI工具</h2>
          <p className="text-gray-600">点击左侧"提示词广场"开始探索工具</p>
        </div>
      </div>
    )
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
        {renderRightContent()}
      </div>
    </div>
  )
}

export default App
