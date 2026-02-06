#!/bin/bash

# 快速启动脚本
# 用法: ./dev.sh

set -e

echo "🚀 启动 AI工具平台..."
echo ""

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# 后端启动
echo -e "${YELLOW}启动后端服务 (FastAPI)...${NC}"
cd backend

# 检查虚拟环境
if [ ! -d "venv" ]; then
    echo "创建虚拟环境..."
    python3 -m venv venv
fi

# 激活虚拟环境
source venv/bin/activate || . venv/Scripts/activate

# 安装依赖
echo "检查依赖..."
pip install -q -r requirements.txt

# # 初始化数据库
# echo "初始化数据库..."
# python scripts/init_db.py

# 启动后端
echo -e "${GREEN}✓ 后端启动完成${NC}"
echo "后端运行在: http://localhost:8000"
echo "API文档: http://localhost:8000/docs"
echo ""

# 在后台启动后端
nohup uvicorn app.main:app --reload --host 0.0.0.0 --port 8000 > logs/backend.log 2>&1 &
BACKEND_PID=$!
echo "后端PID: $BACKEND_PID"

cd ..
sleep 2

# 前端启动
echo -e "${YELLOW}启动前端服务 (Vite)...${NC}"
cd frontend

# 安装依赖
if [ ! -d "node_modules" ]; then
    echo "安装npm依赖..."
    npm install -q
fi

echo -e "${GREEN}✓ 前端启动完成${NC}"
echo "前端运行在: http://localhost:20102"
echo ""

# 启动前端
npm run dev &
FRONTEND_PID=$!

cd ..

# 信号处理函数 - Ctrl+C时停止所有进程
cleanup() {
    echo ""
    echo -e "${YELLOW}正在停止所有服务...${NC}"
    if [ ! -z "$BACKEND_PID" ]; then
        kill $BACKEND_PID 2>/dev/null || true
    fi
    if [ ! -z "$FRONTEND_PID" ]; then
        kill $FRONTEND_PID 2>/dev/null || true
    fi
    echo -e "${GREEN}✓ 所有服务已停止${NC}"
    exit 0
}

# 捕获 SIGINT 信号（Ctrl+C）
trap cleanup SIGINT

