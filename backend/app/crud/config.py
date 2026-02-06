"""配置的CRUD操作"""
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import Optional
import json

from app.models.config import Config


class CRUDConfig:
    """配置CRUD操作"""
    
    async def get(self, db: AsyncSession, key: str) -> Optional[dict]:
        """获取配置"""
        result = await db.execute(
            select(Config).where(Config.key == key)
        )
        config = result.scalar_one_or_none()
        if config:
            return json.loads(config.value)
        return None
    
    async def set(self, db: AsyncSession, key: str, value: dict) -> Config:
        """设置配置"""
        # 先查找是否存在
        result = await db.execute(
            select(Config).where(Config.key == key)
        )
        config = result.scalar_one_or_none()
        
        value_json = json.dumps(value, ensure_ascii=False)
        
        if config:
            # 更新
            config.value = value_json
        else:
            # 创建
            config = Config(key=key, value=value_json)
            db.add(config)
        
        await db.commit()
        await db.refresh(config)
        return config
    
    async def delete(self, db: AsyncSession, key: str) -> bool:
        """删除配置"""
        result = await db.execute(
            select(Config).where(Config.key == key)
        )
        config = result.scalar_one_or_none()
        if config:
            await db.delete(config)
            await db.commit()
            return True
        return False


# 创建实例
config_crud = CRUDConfig()
