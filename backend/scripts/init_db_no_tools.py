"""重建对话历史数据库（不动 ai_tools.db）。

Review note:
- 仅删除并重建 chat_history.db（conversations/messages）。
- ai_tools.db 保持原状，避免影响工具配置数据。
"""
import asyncio
import sys
from pathlib import Path
from urllib.parse import unquote

# 添加项目根目录到Python路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.config import settings
from app.database import init_db


def _chat_db_file_from_url(url: str) -> Path:
    """从 sqlite+aiosqlite URL 提取文件路径。"""
    prefix = "sqlite+aiosqlite:///"
    if not url.startswith(prefix):
        raise ValueError(f"仅支持 sqlite+aiosqlite 文件库，当前: {url}")
    raw_path = unquote(url[len(prefix):]).strip()
    if not raw_path:
        raise ValueError("CHAT_DATABASE_URL 为空，无法定位数据库文件。")
    return Path(raw_path)


async def rebuild_chat_db():
    """删除 chat_history.db 并按当前模型重建 conversations/messages。"""
    chat_db_file = _chat_db_file_from_url(settings.CHAT_DATABASE_URL)
    chat_db_path = (Path(__file__).resolve().parents[1] / chat_db_file).resolve()

    # 删除旧库文件（仅对话库），避免历史列残留。
    for p in (
        chat_db_path,
        chat_db_path.with_suffix(chat_db_path.suffix + "-wal"),
        chat_db_path.with_suffix(chat_db_path.suffix + "-shm"),
    ):
        if p.exists():
            p.unlink()

    chat_db_path.parent.mkdir(parents=True, exist_ok=True)

    # 重建数据库表。ai_tools.db 不删除，保持原状。
    await init_db()
    return chat_db_path


if __name__ == "__main__":
    print("=" * 60)
    print("🚀 AI工具平台 - 重建对话数据库")
    print("=" * 60)

    db_path = asyncio.run(rebuild_chat_db())

    print(f"\n✅ 已重建: {db_path}")
    print("\n✨ 初始化完成！现在可以启动服务了。")
    print("   运行命令: uvicorn app.main:app --reload --port 8000")
    print("=" * 60)
