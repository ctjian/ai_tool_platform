"""Schemas包初始化"""
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
from app.schemas.conversation import (
    ConversationCreate,
    ConversationUpdate,
    ConversationResponse,
    ConversationDetailResponse,
    ConversationListResponse,
    MessageResponse,
    ExportConversationResponse,
)
from app.schemas.chat import (
    ChatRequest,
    StopChatRequest,
    APIConfig,
)
from app.schemas.config import (
    APIConfigResponse,
    APIConfigUpdate,
    TestConnectionRequest,
    TestConnectionResponse,
)

__all__ = [
    # Tool schemas
    "CategoryCreate",
    "CategoryUpdate",
    "CategoryResponse",
    "CategoryListResponse",
    "ToolCreate",
    "ToolUpdate",
    "ToolResponse",
    "ToolListResponse",
    "CategoryOrderUpdate",
    "UploadIconResponse",
    # Conversation schemas
    "ConversationCreate",
    "ConversationUpdate",
    "ConversationResponse",
    "ConversationDetailResponse",
    "ConversationListResponse",
    "MessageResponse",
    "ExportConversationResponse",
    # Chat schemas
    "ChatRequest",
    "StopChatRequest",
    "APIConfig",
    # Config schemas
    "APIConfigResponse",
    "APIConfigUpdate",
    "TestConnectionRequest",
    "TestConnectionResponse",
]
