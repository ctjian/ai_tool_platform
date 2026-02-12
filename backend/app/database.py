"""数据库连接和会话管理

Review note:
- 对话库使用 conversations.extra / messages.extra 作为可扩展 JSON 容器。
- 启动时保留轻量兼容逻辑：旧库缺列时自动补齐。
"""
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.pool import StaticPool
from typing import AsyncGenerator

from app.config import settings

# 创建工具数据库异步引擎（分类、工具、配置）
tools_engine = create_async_engine(
    settings.DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
    echo=settings.DEBUG,
)

# 创建对话历史数据库异步引擎（会话、消息）
chat_engine = create_async_engine(
    settings.CHAT_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
    echo=settings.DEBUG,
)

# 创建工具数据库会话工厂
tools_session_maker = async_sessionmaker(
    tools_engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)

# 创建对话历史数据库会话工厂
chat_session_maker = async_sessionmaker(
    chat_engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)

# 为了兼容性，保留默认的 engine 和 session_maker（指向工具数据库）
engine = tools_engine
async_session_maker = tools_session_maker


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """获取工具数据库会话的依赖注入函数"""
    async with tools_session_maker() as session:
        try:
            yield session
        finally:
            await session.close()


async def get_chat_session() -> AsyncGenerator[AsyncSession, None]:
    """获取对话历史数据库会话的依赖注入函数"""
    async with chat_session_maker() as session:
        try:
            yield session
        finally:
            await session.close()


async def init_db() -> None:
    """初始化数据库表"""
    from app.models.base import Base
    from app.models.category import Category
    from app.models.tool import Tool
    from app.models.config import Config
    from app.models.conversation import Conversation
    from app.models.message import Message
    
    # 创建工具数据库表
    async with tools_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all, tables=[
            Category.__table__,
            Tool.__table__,
            Config.__table__,
        ])
        print("✅ 工具数据库表创建成功")
    
    # 创建对话历史数据库表
    async with chat_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all, tables=[
            Conversation.__table__,
            Message.__table__,
        ])
        # 兼容旧库：补充 conversations/messages 扩展列与历史列
        result = await conn.exec_driver_sql("PRAGMA table_info(conversations)")
        conversation_columns = [row[1] for row in result.fetchall()]
        if "extra" not in conversation_columns:
            await conn.exec_driver_sql("ALTER TABLE conversations ADD COLUMN extra TEXT")

        result = await conn.exec_driver_sql("PRAGMA table_info(messages)")
        message_columns = [row[1] for row in result.fetchall()]
        if "cost_meta" not in message_columns:
            await conn.exec_driver_sql("ALTER TABLE messages ADD COLUMN cost_meta TEXT")
        if "thinking" not in message_columns:
            await conn.exec_driver_sql("ALTER TABLE messages ADD COLUMN thinking TEXT")
        if "extra" not in message_columns:
            await conn.exec_driver_sql("ALTER TABLE messages ADD COLUMN extra TEXT")
        print("✅ 对话历史数据库表创建成功")
