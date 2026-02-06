"""工具和分类的CRUD操作"""
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, delete
from typing import Optional, List

from app.models.category import Category
from app.models.tool import Tool
from app.schemas.tool import CategoryCreate, CategoryUpdate, ToolCreate, ToolUpdate


class CRUDCategory:
    """分类CRUD操作"""
    
    async def get(self, db: AsyncSession, category_id: str) -> Optional[Category]:
        """获取单个分类"""
        result = await db.execute(
            select(Category).where(Category.id == category_id)
        )
        return result.scalar_one_or_none()
    
    async def get_all(self, db: AsyncSession) -> List[Category]:
        """获取所有分类（按order排序）"""
        result = await db.execute(
            select(Category).order_by(Category.order)
        )
        return list(result.scalars().all())
    
    async def create(self, db: AsyncSession, obj_in: CategoryCreate) -> Category:
        """创建分类"""
        db_obj = Category(
            id=obj_in.id,
            name=obj_in.name,
            icon=obj_in.icon,
            description=obj_in.description,
            order=obj_in.order,
        )
        db.add(db_obj)
        await db.commit()
        await db.refresh(db_obj)
        return db_obj
    
    async def update(
        self, 
        db: AsyncSession, 
        category_id: str, 
        obj_in: CategoryUpdate
    ) -> Optional[Category]:
        """更新分类"""
        db_obj = await self.get(db, category_id)
        if not db_obj:
            return None
        
        update_data = obj_in.model_dump(exclude_unset=True)
        for field, value in update_data.items():
            setattr(db_obj, field, value)
        
        await db.commit()
        await db.refresh(db_obj)
        return db_obj
    
    async def delete(self, db: AsyncSession, category_id: str) -> bool:
        """删除分类"""
        result = await db.execute(
            delete(Category).where(Category.id == category_id)
        )
        await db.commit()
        return result.rowcount > 0
    
    async def update_order(self, db: AsyncSession, category_ids: List[str]) -> bool:
        """批量更新分类顺序"""
        for index, category_id in enumerate(category_ids):
            await db.execute(
                update(Category)
                .where(Category.id == category_id)
                .values(order=index)
            )
        await db.commit()
        return True


class CRUDTool:
    """工具CRUD操作"""
    
    async def get(self, db: AsyncSession, tool_id: str) -> Optional[Tool]:
        """获取单个工具"""
        result = await db.execute(
            select(Tool).where(Tool.id == tool_id)
        )
        return result.scalar_one_or_none()
    
    async def get_all(
        self, 
        db: AsyncSession, 
        category_id: Optional[str] = None
    ) -> List[Tool]:
        """获取所有工具（可按分类筛选）"""
        query = select(Tool)
        if category_id:
            query = query.where(Tool.category_id == category_id)
        query = query.order_by(Tool.created_at.desc())
        
        result = await db.execute(query)
        return list(result.scalars().all())
    
    async def create(self, db: AsyncSession, obj_in: ToolCreate) -> Tool:
        """创建工具"""
        db_obj = Tool(
            id=obj_in.id,
            name=obj_in.name,
            category_id=obj_in.category_id,
            icon=obj_in.icon,
            icon_type=obj_in.icon_type,
            description=obj_in.description,
            system_prompt=obj_in.system_prompt,
        )
        db.add(db_obj)
        await db.commit()
        await db.refresh(db_obj)
        return db_obj
    
    async def update(
        self, 
        db: AsyncSession, 
        tool_id: str, 
        obj_in: ToolUpdate
    ) -> Optional[Tool]:
        """更新工具"""
        db_obj = await self.get(db, tool_id)
        if not db_obj:
            return None
        
        update_data = obj_in.model_dump(exclude_unset=True)
        for field, value in update_data.items():
            setattr(db_obj, field, value)
        
        await db.commit()
        await db.refresh(db_obj)
        return db_obj
    
    async def delete(self, db: AsyncSession, tool_id: str) -> bool:
        """删除工具"""
        result = await db.execute(
            delete(Tool).where(Tool.id == tool_id)
        )
        await db.commit()
        return result.rowcount > 0


# 创建实例
category_crud = CRUDCategory()
tool_crud = CRUDTool()
