from typing import Literal

from pydantic import BaseModel, Field


class NotionSearchRequest(BaseModel):
    query: str = Field("", description="Notion page or data source title query.")
    object_type: Literal["page", "data_source"] | None = Field(
        None,
        description="Limit search to pages or data sources.",
    )
    page_size: int = Field(10, ge=1, le=100)


class NotionSearchResult(BaseModel):
    id: str
    object: str
    title: str
    url: str | None = None
    last_edited_time: str | None = None


class NotionSearchResponse(BaseModel):
    results: list[NotionSearchResult]
    has_more: bool
    next_cursor: str | None = None


class NotionParentPageOption(BaseModel):
    id: str
    title: str
    url: str | None = None
    last_edited_time: str | None = None


class NotionParentPageOptionsResponse(BaseModel):
    results: list[NotionParentPageOption]
    has_more: bool
    next_cursor: str | None = None


class NotionPageCreateRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)
    summary: str = Field(..., min_length=1)
    source_url: str | None = None


class NotionPageCreateResponse(BaseModel):
    id: str
    url: str | None = None


class NotionOAuthStartResponse(BaseModel):
    authorization_url: str


class NotionUserConnectionResponse(BaseModel):
    connected: bool
    ready: bool = False
    workspace_id: str | None = None
    workspace_name: str | None = None
    workspace_icon: str | None = None
    bot_id: str | None = None
    parent_page_id: str | None = None
    duplicated_template_id: str | None = None


class NotionOAuthCallbackResponse(NotionUserConnectionResponse):
    message: str


class NotionParentPageRequest(BaseModel):
    parent_page_id: str = Field(..., min_length=1)
