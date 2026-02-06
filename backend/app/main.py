"""FastAPI应用主文件"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from contextlib import asynccontextmanager
import os

from app.config import settings
from app.database import init_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    # 启动时执行
    print("🚀 启动AI工具平台后端...")
    
    # 确保必要的目录存在
    os.makedirs("data", exist_ok=True)
    os.makedirs("logs", exist_ok=True)
    os.makedirs("uploads/icons", exist_ok=True)
    
    # 初始化数据库
    await init_db()
    
    print("✅ 数据库初始化完成")
    print(f"📡 服务器运行在: http://0.0.0.0:8000")
    print(f"📚 API文档: http://0.0.0.0:8000/docs")
    
    yield
    
    # 关闭时执行
    print("👋 关闭AI工具平台后端...")


# 创建FastAPI应用
app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description="AI工具平台后端API",
    lifespan=lifespan,
)

# 配置CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 挂载静态文件目录
if os.path.exists("uploads"):
    app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")


@app.get("/")
async def root():
    """根路径"""
    return {
        "message": "欢迎使用AI工具平台API",
        "version": settings.APP_VERSION,
        "docs": "/docs"
    }


@app.get("/health")
async def health_check():
    """健康检查"""
    return {
        "status": "healthy",
        "service": settings.APP_NAME,
        "version": settings.APP_VERSION
    }


# 导入并注册路由
from app.api.v1 import tools, chat, conversations, config
app.include_router(tools.router, prefix="/api/v1", tags=["tools"])
app.include_router(chat.router, prefix="/api/v1", tags=["chat"])
app.include_router(conversations.router, prefix="/api/v1", tags=["conversations"])
app.include_router(config.router, prefix="/api/v1", tags=["config"])


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True
    )
