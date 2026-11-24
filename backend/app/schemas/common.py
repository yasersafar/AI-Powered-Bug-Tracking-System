"""Shared schema building blocks: validated text types, pagination, user summaries."""

import re
from typing import Annotated, Generic, TypeVar

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, StringConstraints

from app.models.enums import UserRole

# NFR-07: reject control characters (except tab/newline/CR). Text is stored as typed and is
# always returned as JSON; clients render it as text, never as HTML.
_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def _no_control_chars(value: str) -> str:
    if _CONTROL_CHARS.search(value):
        raise ValueError("must not contain control characters")
    return value


def _single_line(value: str) -> str:
    if "\n" in value or "\r" in value:
        raise ValueError("must be a single line")
    return value


SingleLine = Annotated[
    str,
    StringConstraints(strip_whitespace=True),
    AfterValidator(_no_control_chars),
    AfterValidator(_single_line),
]
MultiLine = Annotated[
    str, StringConstraints(strip_whitespace=True), AfterValidator(_no_control_chars)
]

T = TypeVar("T")


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int = Field(description="Total number of matching items.")
    page: int = Field(description="1-based page number.")
    page_size: int


class UserSummary(BaseModel):
    """Minimal user reference used inside other objects."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    full_name: str
    email: str
    role: UserRole


class Message(BaseModel):
    message: str
