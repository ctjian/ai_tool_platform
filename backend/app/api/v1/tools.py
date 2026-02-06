"""工具和分类管理API"""
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional
import os
import uuid
from pathlib import Path

from app.database import get_session
from app.crud.tool import category_crud, tool_crud
from app.schemas.tool import (
    CategoryCreate,
    CategoryUpdate,
    CategoryResponse,
    CategoryListResponse,
    ToolCreate,
    ToolUpdate,
    ToolResponse,
    ToolListResponse,
    CategoryOrderUpdate,
    UploadIconResponse,
)
from app.config import settings

router = APIRouter()


# ========== 分类相关API ==========

@router.get("/categories", response_model=CategoryListResponse)
async def get_categories(db: AsyncSession = Depends(get_session)):
    """获取所有分类"""
    categories = await category_crud.get_all(db)
    return {"categories": categories}


@router.get("/categories/{category_id}", response_model=CategoryResponse)
async def get_category(
    category_id: str,
    db: AsyncSession = Depends(get_session)
):
    """获取单个分类"""
    category = await category_crud.get(db, category_id)
    if not category:
        raise HTTPException(status_code=404, detail="分类不存在")
    return category


@router.post("/categories", response_model=CategoryResponse, status_code=201)
async def create_category(
    category_in: CategoryCreate,
    db: AsyncSession = Depends(get_session)
):
    """创建分类"""
    # 检查ID是否已存在
    existing = await category_crud.get(db, category_in.id)
    if existing:
        raise HTTPException(status_code=400, detail="分类ID已存在")
    
    category = await category_crud.create(db, category_in)
    return category


@router.put("/categories/{category_id}", response_model=CategoryResponse)
async def update_category(
    category_id: str,
    category_in: CategoryUpdate,
    db: AsyncSession = Depends(get_session)
):
    """更新分类"""
    category = await category_crud.update(db, category_id, category_in)
    if not category:
        raise HTTPException(status_code=404, detail="分类不存在")
    return category


@router.delete("/categories/{category_id}")
async def delete_category(
    category_id: str,
    db: AsyncSession = Depends(get_session)
):
    """删除分类"""
    success = await category_crud.delete(db, category_id)
    if not success:
        raise HTTPException(status_code=404, detail="分类不存在")
    return {"success": True, "message": "分类已删除"}


@router.put("/categories/order")
async def update_category_order(
    order_in: CategoryOrderUpdate,
    db: AsyncSession = Depends(get_session)
):
    """更新分类顺序"""
    await category_crud.update_order(db, order_in.category_ids)
    return {"success": True, "message": "顺序已更新"}


# ========== 工具相关API ==========

@router.get("/tools", response_model=ToolListResponse)
async def get_tools(
    category_id: Optional[str] = None,
    db: AsyncSession = Depends(get_session)
):
    """获取所有工具（可按分类筛选）"""
    tools = await tool_crud.get_all(db, category_id)
    return {"tools": tools}


@router.get("/tools/{tool_id}", response_model=ToolResponse)
async def get_tool(
    tool_id: str,
    db: AsyncSession = Depends(get_session)
):
    """获取单个工具"""
    tool = await tool_crud.get(db, tool_id)
    if not tool:
        raise HTTPException(status_code=404, detail="工具不存在")
    return tool


@router.post("/tools", response_model=ToolResponse, status_code=201)
async def create_tool(
    tool_in: ToolCreate,
    db: AsyncSession = Depends(get_session)
):
    """创建工具"""
    # 检查ID是否已存在
    existing = await tool_crud.get(db, tool_in.id)
    if existing:
        raise HTTPException(status_code=400, detail="工具ID已存在")
    
    # 检查分类是否存在
    category = await category_crud.get(db, tool_in.category_id)
    if not category:
        raise HTTPException(status_code=400, detail="分类不存在")
    
    tool = await tool_crud.create(db, tool_in)
    return tool


@router.put("/tools/{tool_id}", response_model=ToolResponse)
async def update_tool(
    tool_id: str,
    tool_in: ToolUpdate,
    db: AsyncSession = Depends(get_session)
):
    """更新工具"""
    tool = await tool_crud.update(db, tool_id, tool_in)
    if not tool:
        raise HTTPException(status_code=404, detail="工具不存在")
    return tool


@router.delete("/tools/{tool_id}")
async def delete_tool(
    tool_id: str,
    db: AsyncSession = Depends(get_session)
):
    """删除工具"""
    success = await tool_crud.delete(db, tool_id)
    if not success:
        raise HTTPException(status_code=404, detail="工具不存在")
    return {"success": True, "message": "工具已删除"}


@router.post("/tools/upload-icon", response_model=UploadIconResponse)
async def upload_icon(file: UploadFile = File(...)):
    """上传工具图标"""
    # 验证文件类型
    file_ext = Path(file.filename).suffix.lower().lstrip('.')
    if file_ext not in settings.ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"不支持的文件类型。允许的类型: {', '.join(settings.ALLOWED_EXTENSIONS)}"
        )
    
    # 验证文件大小
    content = await file.read()
    if len(content) > settings.MAX_UPLOAD_SIZE:
        raise HTTPException(
            status_code=400,
            detail=f"文件过大。最大允许: {settings.MAX_UPLOAD_SIZE / 1024 / 1024}MB"
        )
    
    # 生成唯一文件名
    filename = f"{uuid.uuid4()}.{file_ext}"
    file_path = Path(settings.UPLOAD_DIR) / "icons" / filename
    
    # 确保目录存在
    file_path.parent.mkdir(parents=True, exist_ok=True)
    
    # 保存文件
    with open(file_path, "wb") as f:
        f.write(content)
    
    # 返回URL
    url = f"/uploads/icons/{filename}"
    return {
        "url": url,
        "filename": filename
    }
