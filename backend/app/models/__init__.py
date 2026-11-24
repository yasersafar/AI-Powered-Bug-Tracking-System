"""Import every model so `Base.metadata` is complete (Alembic autogenerate, tests)."""

from app.models.attachment import Attachment
from app.models.audit import AuditLog
from app.models.bug import Bug, BugEmbedding
from app.models.comment import Comment
from app.models.developer import (
    BugAssignment,
    DeveloperProfile,
    ProfileComponent,
    ProfileSkill,
    ResolutionHistory,
)
from app.models.enums import (
    AiStatus,
    AssignmentEnd,
    Availability,
    BugStatus,
    CloseReason,
    DeliveryStatus,
    ExperienceLevel,
    NotificationKind,
    ProjectRole,
    Severity,
    UserRole,
)
from app.models.project import Project, ProjectMember
from app.models.system import ModelState, Notification, SystemSetting
from app.models.user import User

__all__ = [
    "AiStatus",
    "AssignmentEnd",
    "Attachment",
    "AuditLog",
    "Availability",
    "Bug",
    "BugAssignment",
    "BugEmbedding",
    "BugStatus",
    "CloseReason",
    "Comment",
    "DeliveryStatus",
    "DeveloperProfile",
    "ExperienceLevel",
    "ModelState",
    "Notification",
    "NotificationKind",
    "ProfileComponent",
    "ProfileSkill",
    "Project",
    "ProjectMember",
    "ProjectRole",
    "ResolutionHistory",
    "Severity",
    "SystemSetting",
    "User",
    "UserRole",
]
