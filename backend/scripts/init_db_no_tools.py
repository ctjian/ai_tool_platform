"""初始化数据库并添加示例数据"""
import asyncio
import sys
from pathlib import Path

# 添加项目根目录到Python路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.database import init_db, tools_session_maker, chat_session_maker
from app.models import Category, Tool
from datetime import datetime


async def init_sample_data():
    """初始化示例数据"""
    
    # 先初始化两个数据库的表
    await init_db()
    
    from sqlalchemy import text
    
    # 清理对话历史数据库（messages/conversations）
    async with chat_session_maker() as chat_session:
        await chat_session.execute(text("DELETE FROM messages"))
        await chat_session.execute(text("DELETE FROM conversations"))
        await chat_session.commit()
        

if __name__ == "__main__":
    print("=" * 60)
    print("🚀 AI工具平台 - 数据库初始化")
    print("=" * 60)
    
    asyncio.run(init_sample_data())
    
    print("\n✨ 初始化完成！现在可以启动服务了。")
    print("   运行命令: uvicorn app.main:app --reload --port 8000")
    print("=" * 60)
