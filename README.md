# AI工具平台 - 安装指南

## 📦 预安装要求

### 系统要求
- **操作系统**: Linux / macOS / Windows
- **Node.js**: 18.x 或更高版本
- **Python**: 3.11 或更高版本
- **包管理器**: npm 或 pnpm（前端）、pip（后端）

---

## 🚀 快速开始

### 1️⃣ 克隆项目
```bash
git clone <repository-url>
cd ai_tool_platform
```

### 2️⃣ 前端安装

```bash
cd frontend

# 安装依赖
npm install
# 或使用 pnpm（推荐，更快）
pnpm install

# 复制环境变量文件
cp .env.example .env

# 编辑 .env 文件（如果需要修改API地址）
# VITE_API_BASE_URL=http://localhost:8000/api/v1
```

**主要依赖说明**：
- `react` - React 18框架
- `vite` - 现代化构建工具
- `tailwindcss` - CSS框架
- `zustand` - 轻量状态管理
- `react-router-dom` - 路由管理
- `axios` - HTTP客户端
- `react-markdown` - Markdown渲染
- `katex` - LaTeX数学公式渲染
- `lucide-react` - 图标库
- `emoji-picker-react` - Emoji选择器

### 3️⃣ 后端安装

```bash
cd backend

# 创建虚拟环境（推荐）
python -m venv venv

# 激活虚拟环境
# Linux/Mac:
source venv/bin/activate
# Windows:
venv\Scripts\activate

# 安装依赖
pip install -r requirements.txt

# 复制环境变量文件
cp .env.example .env

# 编辑 .env 文件，配置必要参数
```

**主要依赖说明**：
- `fastapi` - 现代Web框架
- `uvicorn` - ASGI服务器
- `sqlalchemy` - ORM框架
- `aiosqlite` - SQLite异步驱动
- `alembic` - 数据库迁移工具
- `openai` - OpenAI官方SDK
- `pydantic` - 数据验证
- `cryptography` - 加密库

### 3.1️⃣ （可选）ArXiv 论文精细翻译的 LaTeX 依赖

如果你要使用“Arxiv论文精细翻译”（翻译后编译 PDF），后端机器还需要安装 LaTeX 工具链：

```bash
sudo apt update
sudo apt install -y texlive-full latexdiff
```

安装后建议执行版本检查：

```bash
pdflatex --version
xelatex --version
bibtex --version
latexdiff --version
```

### 4️⃣ 初始化数据库

```bash
# 确保在 backend 目录下，虚拟环境已激活

# 创建必要的目录
mkdir -p data logs uploads/icons

# 初始化数据库（运行迁移）
alembic upgrade head

# 或者使用初始化脚本（如果提供）
python scripts/init_db.py
```

---

## 🏃 运行项目

### 开发模式

#### 终端1 - 启动后端
```bash
cd backend
source venv/bin/activate  # 激活虚拟环境

# 启动FastAPI开发服务器
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# 或使用脚本
python -m uvicorn app.main:app --reload --port 8000
```

后端服务将在 http://localhost:8000 启动

#### 终端2 - 启动前端
```bash
cd frontend

# 启动Vite开发服务器
npm run dev
# 或
pnpm dev
```

前端服务将在 http://localhost:2102 启动

### 访问应用
打开浏览器访问：http://localhost:2102

---

## 🔧 常见问题

### 1. Python版本问题
```bash
# 检查Python版本
python --version  # 应该是 3.11+

# 如果系统有多个Python版本
python3.11 -m venv venv
```

### 2. Node.js版本问题
```bash
# 检查Node版本
node --version  # 应该是 18+

# 使用nvm切换版本（如果安装了nvm）
nvm use 18
```

### 3. 依赖安装失败
```bash
# 前端：清除缓存重新安装
rm -rf node_modules package-lock.json
npm install

# 后端：升级pip后重试
pip install --upgrade pip
pip install -r requirements.txt
```

### 4. 数据库初始化失败
```bash
# 删除旧数据库重新初始化
rm -rf data/ai_tools.db
alembic upgrade head
```

### 5. CORS错误
确保后端 `.env` 文件中的 `CORS_ORIGINS` 包含前端地址：
```
CORS_ORIGINS=http://localhost:2102,http://localhost:3000
```
