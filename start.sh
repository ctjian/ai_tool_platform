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

PYTHON_BIN=""
if command -v python3 >/dev/null 2>&1; then
    PYTHON_BIN="$(command -v python3)"
elif command -v python >/dev/null 2>&1; then
    PYTHON_BIN="$(command -v python)"
else
    echo -e "${RED}未找到 Python，请先安装 Python 3。${NC}"
    exit 1
fi

# 检查虚拟环境
if [ ! -d "venv" ]; then
    echo "创建虚拟环境..."
    "$PYTHON_BIN" -m venv venv
fi

if [ -x "venv/bin/python" ]; then
    VENV_PYTHON="venv/bin/python"
elif [ -x "venv/Scripts/python.exe" ]; then
    VENV_PYTHON="venv/Scripts/python.exe"
else
    echo -e "${RED}虚拟环境创建失败，未找到可用的 Python 可执行文件。${NC}"
    exit 1
fi

# 临时禁用代理
unset http_proxy
unset https_proxy

# 安装依赖
echo "检查依赖..."
if ! "$VENV_PYTHON" -m pip --version >/dev/null 2>&1; then
    echo "虚拟环境缺少 pip，正在补装..."
    "$VENV_PYTHON" -m ensurepip --upgrade
fi
"$VENV_PYTHON" -m pip install -q -r requirements.txt

# 初始化数据库
# echo "初始化数据库..."
# python scripts/init_db_no_tools.py

# 启动后端
echo -e "${GREEN}✓ 后端启动完成${NC}"
echo "后端运行在: http://localhost:8000"
echo "API文档: http://localhost:8000/docs"
echo ""

# 在后台启动后端
mkdir -p logs
nohup "$VENV_PYTHON" -m uvicorn app.main:app --reload --host :: --port 8000 > logs/backend.log 2>&1 &
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
echo "前端运行在: http://localhost:2102"
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

# 显示启动信息
echo "========================================="
echo -e "${GREEN}✓ 所有服务已启动${NC}"
echo "========================================="
echo ""
echo "📚 后端服务"
echo "   地址: http://localhost:8000"
echo "   API文档: http://localhost:8000/docs"
echo ""
echo "🎨 前端服务"
echo "   地址: http://localhost:2102"
echo ""
echo "📝 日志文件"
echo "   后端: logs/backend.log"
echo "   前端: 在终端显示"
echo ""
echo "⏹️  停止服务: 按 Ctrl+C"
echo "========================================="
echo ""

# 等待进程
wait
