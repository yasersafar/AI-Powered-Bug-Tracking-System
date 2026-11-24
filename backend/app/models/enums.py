"""Domain enumerations. Stored in PostgreSQL as native ENUM types using the `.value` strings."""

from enum import StrEnum


class UserRole(StrEnum):
    """Global role (FR-03). Administrator is a system-wide super user."""

    REPORTER = "Reporter"
    DEVELOPER = "Developer"
    PROJECT_MANAGER = "ProjectManager"
    ADMINISTRATOR = "Administrator"


class ProjectRole(StrEnum):
    """Role a user holds inside one project (FR-19)."""

    REPORTER = "Reporter"
    DEVELOPER = "Developer"
    PROJECT_MANAGER = "ProjectManager"


class Severity(StrEnum):
    """Bug severity. `Unclassified` means no prediction was available (NFR-10)."""

    LOW = "Low"
    MEDIUM = "Medium"
    HIGH = "High"
    CRITICAL = "Critical"
    UNCLASSIFIED = "Unclassified"


class BugStatus(StrEnum):
    """Lifecycle state (FR-06): Open -> InProgress -> Resolved -> Verified -> Closed."""

    OPEN = "Open"
    IN_PROGRESS = "InProgress"
    RESOLVED = "Resolved"
    VERIFIED = "Verified"
    CLOSED = "Closed"


class AiStatus(StrEnum):
    """Overall result of the AI triage for a report: `ok` or `degraded` (NFR-10)."""

    OK = "ok"
    DEGRADED = "degraded"


class CloseReason(StrEnum):
    """Why a bug was closed: fixed, invalid or duplicate."""

    FIXED = "fixed"
    INVALID = "invalid"
    DUPLICATE = "duplicate"


class ExperienceLevel(StrEnum):
    """Developer experience level in the admin profile (FR-20)."""

    JUNIOR = "Junior"
    MID = "Mid"
    SENIOR = "Senior"


class Availability(StrEnum):
    """Whether a developer can take new work; Critical bugs skip `Unavailable` developers."""

    AVAILABLE = "Available"
    LIMITED = "Limited"
    UNAVAILABLE = "Unavailable"


class AssignmentEnd(StrEnum):
    REASSIGNED = "reassigned"
    CLOSED = "closed"


class NotificationKind(StrEnum):
    """Why a notification was sent: assignment, status change or critical bug."""

    ASSIGNED = "assigned"
    STATUS_CHANGED = "status_changed"
    CRITICAL_BUG = "critical_bug"


class DeliveryStatus(StrEnum):
    """Delivery state of an e-mail or push notification."""

    PENDING = "pending"
    SENT = "sent"
    FAILED = "failed"
    SKIPPED = "skipped"
