import { useAppStore } from '../store/app'
import { Settings, Compass, Plus, MoreHorizontal, Pencil, Trash2, Wrench } from 'lucide-react'
import apiClient from '../api/client'
import { addToast } from './ui'
import { useState } from 'react'

interface SidebarProps {
  onPageChange?: (page: 'chat' | 'settings' | 'explorer' | 'custom-tools') => void
  currentPage?: 'chat' | 'settings' | 'explorer' | 'custom-tools'
}

// 获取对话分组
function groupConversationsByDate(conversations: any[]) {
  const now = new Date()
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate())
  const yesterday = new Date(today.getTime() - 24 * 60 * 60 * 1000)
  const sevenDaysAgo = new Date(today.getTime() - 7 * 24 * 60 * 60 * 1000)
  const thirtyDaysAgo = new Date(today.getTime() - 30 * 24 * 60 * 60 * 1000)

  const groups: { label: string; conversations: any[] }[] = [
    { label: '今天', conversations: [] },
    { label: '昨天', conversations: [] },
    { label: '7天内', conversations: [] },
    { label: '30天内', conversations: [] },
    { label: '更早', conversations: [] },
  ]

  conversations.forEach((conv) => {
    const convDate = new Date(conv.updated_at)
    const convDateOnly = new Date(convDate.getFullYear(), convDate.getMonth(), convDate.getDate())

    if (convDateOnly.getTime() === today.getTime()) {
      groups[0].conversations.push(conv)
    } else if (convDateOnly.getTime() === yesterday.getTime()) {
      groups[1].conversations.push(conv)
    } else if (convDate > sevenDaysAgo) {
      groups[2].conversations.push(conv)
    } else if (convDate > thirtyDaysAgo) {
      groups[3].conversations.push(conv)
    } else {
      groups[4].conversations.push(conv)
    }
  })

  return groups.filter((g) => g.conversations.length > 0)
}

function Sidebar({ onPageChange, currentPage = 'chat' }: SidebarProps) {
  const {
    conversations,
    setCurrentTool,
    currentConversation,
    setCurrentConversation,
    setMessages,
    setConversations,
  } = useAppStore()

  const [renamingId, setRenamingId] = useState<string | null>(null)
  const [renameValue, setRenameValue] = useState('')
  const [menuModalConv, setMenuModalConv] = useState<any>(null)

  const handleNewChat = async () => {
    try {
      // 创建不关联工具的对话（通用对话模式）
      const response = await apiClient.createConversation(null, `新聊天 - ${new Date().toLocaleString()}`)
      const newConversation = response.data
      
      // 更新对话列表
      setConversations(prev => [newConversation, ...prev])
      
      // 设置当前对话
      setCurrentConversation(newConversation)
      
      // 清空消息
      setMessages([])
      
      // 清空当前工具（通用模式）
      setCurrentTool(null)
      
      addToast('新聊天已创建', 'success')
    } catch (error) {
      console.error('Failed to create new chat:', error)
      addToast('创建失败', 'error')
    }
  }

  const handleSelectConversation = async (conversation: any) => {
    try {
      setCurrentConversation(conversation)
      
      // 获取对话的详细信息（包含消息）
      const response = await apiClient.getConversation(conversation.id)
      const conversationDetail = response.data
      
      // 设置消息
      setMessages(conversationDetail.messages || [])
      
      // 设置对应的工具（如果有的话）
      if (conversation.tool_id) {
        const { tools } = useAppStore.getState()
        const foundTool = tools.find(t => t.id === conversation.tool_id)
        setCurrentTool(foundTool || null)
      } else {
        // 通用对话模式，没有工具
        setCurrentTool(null)
      }
    } catch (error) {
      console.error('Failed to load conversation:', error)
      setMessages([])
    }
  }

  const handleDeleteConversation = async (convId: string, e: React.MouseEvent) => {
    e.stopPropagation()
    
    if (!confirm('确定要删除这个对话吗？')) return

    try {
      await apiClient.deleteConversation(convId)
      setConversations(prev => prev.filter(c => c.id !== convId))
      
      // 如果删除的是当前对话，清空当前对话
      if (currentConversation?.id === convId) {
        setCurrentConversation(null)
        setMessages([])
      }
      
      addToast('对话已删除', 'success')
    } catch (error) {
      console.error('Failed to delete conversation:', error)
      addToast('删除失败', 'error')
    }
  }

  const handleStartRename = (conv: any, e: React.MouseEvent) => {
    e.stopPropagation()
    setRenamingId(conv.id)
    setRenameValue(conv.title)
  }

  const handleRename = async (convId: string) => {
    if (!renameValue.trim()) return

    try {
      await apiClient.updateConversation(convId, { title: renameValue })
      setConversations(prev => prev.map(c => 
        c.id === convId ? { ...c, title: renameValue } : c
      ))
      
      if (currentConversation?.id === convId) {
        setCurrentConversation({ ...currentConversation, title: renameValue })
      }
      
      setRenamingId(null)
      addToast('重命名成功', 'success')
    } catch (error) {
      console.error('Failed to rename conversation:', error)
      addToast('重命名失败', 'error')
    }
  }

  const handleCancelRename = () => {
    setRenamingId(null)
    setRenameValue('')
  }

  return (
    <div className="w-64 bg-white border-r border-gray-200 flex flex-col h-screen text-gray-900">
      {/* Logo/标题和新建聊天按钮 */}
      <div className="border-b border-gray-200 p-3 space-y-3">
        <div className="flex items-center gap-2">
          <span className="text-2xl">🤖</span>
          <span className="font-bold">一站式AI工具平台</span>
        </div>
        <button
          onClick={handleNewChat}
          className="w-full flex items-center justify-center gap-2 px-3 py-2 border border-gray-300 text-gray-700 hover:bg-gray-100 active:bg-gray-200 rounded-lg transition text-sm"
        >
          <Plus size={16} />
          新建聊天
        </button>
      </div>

      {/* 分类和聊天列表 */}
      <div className="flex-1 overflow-y-auto">
        {/* 聊天历史部分 */}
        {conversations && conversations.length > 0 && (
          <div className="px-3 py-4">
            {groupConversationsByDate(conversations).map((group) => (
              <div key={group.label} className="mb-4">
                <div className="text-xs font-semibold text-gray-500 uppercase mb-3">{group.label}</div>
                <div className="space-y-1">
                  {group.conversations.map((conv) => (
                    <div
                      key={conv.id}
                      className={`relative group ${menuModalConv?.id === conv.id ? 'z-50' : ''}`}
                    >
                      {renamingId === conv.id ? (
                        // 重命名输入框
                        <div className="flex items-center gap-2 px-3 py-2">
                          <input
                            type="text"
                            value={renameValue}
                            onChange={(e) => setRenameValue(e.target.value)}
                            onKeyDown={(e) => {
                              if (e.key === 'Enter') handleRename(conv.id)
                              if (e.key === 'Escape') handleCancelRename()
                            }}
                            onBlur={() => handleRename(conv.id)}
                            autoFocus
                            className="flex-1 px-2 py-1 text-xs border border-gray-300 rounded focus:outline-none focus:ring-2 focus:ring-indigo-500"
                          />
                        </div>
                      ) : (
                        // 对话项
                        <>
                          <button
                            onClick={() => handleSelectConversation(conv)}
                            className={`w-full text-left px-3 py-2 rounded text-xs transition truncate pr-8 ${
                              currentConversation?.id === conv.id
                                ? 'bg-gray-200 text-gray-900'
                                : 'text-gray-700 hover:text-gray-900 hover:bg-gray-100'
                            }`}
                            title={conv.title}
                          >
                            {conv.title}
                          </button>
                          
                          {/* 菜单按钮 */}
                          <div className={`absolute right-2 top-1/2 -translate-y-1/2 transition-opacity ${menuModalConv?.id === conv.id ? 'opacity-100' : 'opacity-0 group-hover:opacity-100'}`}>
                            <button
                              onClick={(e) => {
                                e.stopPropagation()
                                setMenuModalConv(menuModalConv?.id === conv.id ? null : conv)
                              }}
                              className="p-1 hover:bg-gray-200 rounded"
                            >
                              <MoreHorizontal size={14} className="text-gray-600" />
                            </button>
                            
                            {/* 弹出菜单 */}
                            {menuModalConv?.id === conv.id && (
                              <div className="absolute right-0 top-full mt-1 bg-white border border-gray-200 rounded-lg shadow-lg z-50 w-32">
                                <button
                                  onClick={(e) => {
                                    e.stopPropagation()
                                    handleStartRename(menuModalConv, e)
                                    setMenuModalConv(null)
                                  }}
                                  className="w-full text-left px-4 py-2.5 text-sm hover:bg-gray-100 flex items-center gap-3 text-gray-700 transition"
                                >
                                  <Pencil size={16} />
                                  重命名
                                </button>
                                <button
                                  onClick={(e) => {
                                    e.stopPropagation()
                                    handleDeleteConversation(menuModalConv.id, e)
                                    setMenuModalConv(null)
                                  }}
                                  className="w-full text-left px-4 py-2.5 text-sm hover:bg-gray-100 flex items-center gap-3 text-red-600 transition"
                                >
                                  <Trash2 size={16} />
                                  删除
                                </button>
                              </div>
                            )}
                          </div>
                        </>
                      )}
                    </div>
                  ))}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* 底部按钮 */}
      <div className="border-t border-gray-200 p-3 space-y-2">
        <button
          onClick={() => onPageChange?.('explorer')}
          className={`w-full flex items-center gap-2 px-3 py-2 rounded transition text-sm ${
            currentPage === 'explorer'
              ? 'bg-gray-200 text-gray-900'
              : 'text-gray-700 hover:bg-gray-100 active:bg-gray-200'
          }`}
        >
          <Compass size={16} />
          提示词广场
        </button>
        <button
          onClick={() => onPageChange?.('custom-tools')}
          className={`w-full flex items-center gap-2 px-3 py-2 rounded transition text-sm ${
            currentPage === 'custom-tools'
              ? 'bg-gray-200 text-gray-900'
              : 'text-gray-700 hover:bg-gray-100 active:bg-gray-200'
          }`}
        >
          <Wrench size={16} />
          自定义工具
        </button>
        <button
          onClick={() => onPageChange?.('settings')}
          className={`w-full flex items-center gap-2 px-3 py-2 rounded transition text-sm ${
            currentPage === 'settings'
              ? 'bg-gray-200 text-gray-900'
              : 'text-gray-700 hover:bg-gray-100 active:bg-gray-200'
          }`}
        >
          <Settings size={16} />
          设置
        </button>
      </div>

      {/* 全局遮罩层 - 点击关闭菜单 */}
      {menuModalConv && (
        <div
          className="fixed inset-0 z-40"
          onClick={() => setMenuModalConv(null)}
        />
      )}
    </div>
  )
}

export default Sidebar
