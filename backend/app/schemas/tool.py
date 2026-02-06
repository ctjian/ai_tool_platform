"""工具相关的Pydantic schemas"""
from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime


class CategoryBase(BaseModel):
    """分类基础模型"""
    name: str = Field(..., min_length=1, max_length=100, description="分类名称")
    icon: str = Field(..., min_length=1, max_length=10, description="分类图标(emoji)")
    description: Optional[str] = Field(None, description="分类描述")
    order: int = Field(default=0, description="排序顺序")


class CategoryCreate(CategoryBase):
    """创建分类"""
    id: str = Field(..., min_length=1, max_length=50, description="分类ID")


class CategoryUpdate(BaseModel):
    """更新分类"""
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    icon: Optional[str] = Field(None, min_length=1, max_length=10)
    description: Optional[str] = None
    order: Optional[int] = None


class CategoryResponse(CategoryBase):
    """分类响应"""
    id: str
    created_at: datetime
    updated_at: datetime
    
    class Config:
        from_attributes = True


class ToolBase(BaseModel):
    """工具基础模型"""
    name: str = Field(..., min_length=1, max_length=100, description="工具名称")
    category_id: str = Field(..., description="所属分类ID")
    icon: str = Field(..., min_length=1, max_length=500, description="工具图标")
    icon_type: str = Field(default="emoji", description="图标类型: emoji或image")
    description: str = Field(..., min_length=1, description="工具描述")
    system_prompt: str = Field(..., min_length=1, description="系统提示词")


class ToolCreate(ToolBase):
    """创建工具"""
    id: str = Field(..., min_length=1, max_length=50, description="工具ID")


class ToolUpdate(BaseModel):
    """更新工具"""
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    category_id: Optional[str] = None
    icon: Optional[str] = Field(None, min_length=1, max_length=500)
    icon_type: Optional[str] = None
    description: Optional[str] = Field(None, min_length=1)
    system_prompt: Optional[str] = Field(None, min_length=1)


class ToolResponse(ToolBase):
    """工具响应"""
    id: str
    created_at: datetime
    updated_at: datetime
    
    class Config:
        from_attributes = True


class ToolListResponse(BaseModel):
    """工具列表响应"""
    tools: list[ToolResponse]


class CategoryListResponse(BaseModel):
    """分类列表响应"""
    categories: list[CategoryResponse]


class CategoryOrderUpdate(BaseModel):
    """更新分类顺序"""
    category_ids: list[str] = Field(..., description="分类ID列表（按新顺序）")


class UploadIconResponse(BaseModel):
    """图标上传响应"""
    url: str = Field(..., description="图标访问URL")
    filename: str = Field(..., description="文件名")
