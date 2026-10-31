from datetime import datetime

from pydantic import BaseModel, ConfigDict


class ProjectCreate(BaseModel):
    name: str
    description: str = ""


class ProjectRead(BaseModel):
    id: int
    name: str
    description: str
    is_archived: bool
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class MemberAdd(BaseModel):
    user_id: int


class MemberRead(BaseModel):
    id: int
    project_id: int
    user_id: int

    model_config = ConfigDict(from_attributes=True)
