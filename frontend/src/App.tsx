import { useEffect, useState } from 'react'
import { useAppStore } from './store/app'
import apiClient from './api/client'
import Sidebar from './components/Sidebar'
import ChatWindow from './components/ChatWindow'
import { ToastContainer } from './components/ui'
import { SettingsPage } from './pages/SettingsPage'
import { ToolsExplorer } from './pages/ToolsExplorer'

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
  } = useAppStore()

  const [currentPage, setCurrentPage] = useState<'chat' | 'settings' | 'explorer'>('chat')

  useEffect(() => {
    const loadInitialData = async () => {
      try {
        setLoading(true)
        
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

  const handlePageChange = (page: 'chat' | 'settings' | 'explorer') => {
    setCurrentPage(page)
    // 切换到设置或工具广场时，清除当前工具和对话以显示对应页面
    if (page === 'settings' || page === 'explorer') {
      setCurrentTool(null)
      setCurrentConversation(null)
    }
  }

  const renderRightContent = () => {
    // chat 模式 - 最高优先级，有工具或有对话时显示聊天窗口
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

    // 默认：显示欢迎页面
    return (
      <div className="flex-1 flex items-center justify-center bg-white">
        <div className="text-center">
          <div className="text-6xl mb-4">�</div>
          <h2 className="text-2xl font-bold mb-2">欢迎使用AI工具</h2>
          <p className="text-gray-600">点击左侧"工具广场"开始探索工具</p>
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
      <div className="flex-1 flex flex-col overflow-hidden">
        {renderRightContent()}
      </div>
    </div>
  )
}

export default App
