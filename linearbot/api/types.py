from typing import NewType, List, Optional, Union, Dict, Any, TYPE_CHECKING
from datetime import datetime, date
from uuid import UUID

from attr import dataclass

from mautrix.types import (SerializableAttrs, SerializableEnum, JSON, Obj,
                           serializer, deserializer, field)

if TYPE_CHECKING:
    from .client import LinearClient

LinearDateTime = NewType("LinearDateTime", datetime)
LinearDate = NewType("LinearDate", date)
ISO_FORMAT = "%Y-%m-%dT%H:%M:%S.%f%z"


@serializer(LinearDateTime)
def datetime_serializer(dt: LinearDateTime) -> JSON:
    return dt.strftime(ISO_FORMAT)


@deserializer(LinearDateTime)
def datetime_deserializer(data: JSON) -> LinearDateTime:
    return LinearDateTime(datetime.strptime(data, ISO_FORMAT))


@serializer(LinearDate)
def date_serializer(dt: LinearDate) -> JSON:
    return dt.isoformat()


@deserializer(LinearDate)
def date_deserializer(data: JSON) -> LinearDate:
    return LinearDate(date.fromisoformat(data))


class EventAction(SerializableEnum):
    CREATE = "create"
    UPDATE = "update"
    REMOVE = "remove"
    RESTORE = "restore"


class LinearEventType(SerializableEnum):
    ISSUE = "Issue"
    REACTION = "Reaction"
    COMMENT = "Comment"
    PROJECT = "Project"
    ISSUE_LABEL = "IssueLabel"
    ATTACHMENT = "Attachment"


@dataclass
class MinimalIssue(SerializableAttrs):
    id: UUID
    title: str


@dataclass
class IssueCreateResponse(MinimalIssue, SerializableAttrs):
    identifier: str
    url: str


@dataclass
class MinimalUser(SerializableAttrs):
    id: UUID
    name: str


@dataclass
class MinimalProject(SerializableAttrs):
    id: UUID
    name: str


@dataclass
class Organization(SerializableAttrs):
    id: UUID
    name: str
    url_key: str = field(json="urlKey")


@dataclass(kw_only=True)
class User(MinimalUser, SerializableAttrs):
    display_name: str = field(json="displayName")
    email: str
    url: str
    organization: Optional[Organization] = None


@dataclass(kw_only=True)
class MinimalComment(SerializableAttrs):
    id: UUID
    body: str
    user_id: UUID = field(json="userId")


@dataclass(kw_only=True)
class MinimalTeam(SerializableAttrs):
    id: UUID
    key: str
    name: str


class IssueStateType(SerializableEnum):
    TRIAGE = "triage"
    BACKLOG = "backlog"
    UNSTARTED = "unstarted"
    STARTED = "started"
    COMPLETED = "completed"
    CANCELED = "canceled"


@dataclass
class IssueState(SerializableAttrs):
    id: UUID
    type: IssueStateType
    name: str
    color: str


@dataclass
class MinimalLabel(SerializableAttrs):
    id: UUID
    name: str
    color: str


class LinearEventData:
    async def get_meta(self, client: 'LinearClient') -> Dict[str, Any]:
        return {}


@dataclass
class LabelEvent(MinimalLabel, SerializableAttrs, LinearEventData):
    created_at: LinearDateTime = field(json="createdAt")
    updated_at: LinearDateTime = field(json="updatedAt")
    team_id: UUID = field(json="teamId")
    creator_id: UUID = field(json="creatorId")


@dataclass
class Label(MinimalLabel, SerializableAttrs):
    description: str
    team: MinimalTeam
    created_at: LinearDateTime = field(json="createdAt")
    updated_at: LinearDateTime = field(json="updatedAt")

    def meta_equals(self, other: 'Label') -> bool:
        return (self.name == other.name
                and self.color == other.color
                and self.description == other.description)


@dataclass
class Cycle(SerializableAttrs):
    id: UUID
    number: int
    starts_at: LinearDateTime = field(json="startsAt")
    ends_at: LinearDateTime = field(json="endsAt")


@dataclass
class IssueMeta(MinimalIssue):
    identifier: str
    url: str


@dataclass
class IssueSummary(IssueMeta):
    assignee: Optional[User] = None
    cycle: Optional[Cycle] = None
    description: Optional[str] = None
    estimate: Optional[int] = None
    priority_label: Optional[str] = field(json="priorityLabel", default=None)
    project: Optional[MinimalProject] = None
    state: Optional[IssueState] = None

@dataclass
class IssueLabels(MinimalIssue):
    label_ids: Optional[List[UUID]] = field(json="labelIds", default=None)

@dataclass(kw_only=True)
class Issue(MinimalIssue, SerializableAttrs, LinearEventData):
    number: int
    description: Optional[str] = None
    creator_id: UUID = field(json="creatorId")
    created_at: LinearDateTime = field(json="createdAt")
    updated_at: LinearDateTime = field(json="updatedAt")
    team_id: UUID = field(json="teamId")
    team: MinimalTeam
    state_id: UUID = field(json="stateId")
    state: IssueState
    parent_id: Optional[UUID] = field(json="parentId", default=None)
    sub_issue_sort_order: Optional[float] = field(json="subIssueSortOrder", default=None)
    completed_at: Optional[LinearDateTime] = field(json="completedAt", default=None)
    canceled_at: Optional[LinearDateTime] = field(json="canceledAt", default=None)
    archived_at: Optional[LinearDateTime] = field(json="archivedAt", default=None)
    started_at: Optional[LinearDateTime] = field(json="startedAt", default=None)
    due_date: Optional[LinearDate] = field(json="dueDate", default=None)
    estimate: Optional[int] = None
    priority: Optional[int] = None
    priority_label: Optional[str] = field(json="priorityLabel", default=None)
    assignee: Optional[MinimalUser] = None
    assignee_id: Optional[UUID] = field(json="assigneeId", default=None)
    cycle: Optional[Cycle] = None
    cycle_id: Optional[UUID] = field(json="cycleId", default=None)
    label_ids: List[UUID] = field(json="labelIds", factory=lambda: [])
    labels: List[MinimalLabel] = field(factory=lambda: [])
    subscriber_ids: List[UUID] = field(json="subscriberIds", factory=lambda: [])
    sort_order: float = field(json="sortOrder", default=0)
    board_order: int = field(json="boardOrder", default=0)
    previous_identifiers: List[str] = field(json="previousIdentifiers", factory=lambda: [])
    trashed: bool = False

    async def get_meta(self, client: 'LinearClient') -> Dict[str, Any]:
        return {
            "id": str(self.id),
        }


@dataclass(kw_only=True)
class Comment(MinimalComment, SerializableAttrs, LinearEventData):
    issue: MinimalIssue
    issue_id: UUID = field(json="issueId")
    created_at: LinearDateTime = field(json="createdAt")
    updated_at: LinearDateTime = field(json="updatedAt")
    edited_at: Optional[LinearDateTime] = field(json="editedAt", default=None)
    user: MinimalUser

    async def get_meta(self, client: 'LinearClient') -> Dict[str, Any]:
        return {
            "issue_id": str(self.issue_id),
            "id": str(self.id),
        }


@dataclass(kw_only=True)
class Reaction(SerializableAttrs, LinearEventData):
    id: UUID
    emoji: str
    comment: MinimalComment
    comment_id: UUID = field(json="commentId")
    user: MinimalUser
    user_id: UUID = field(json="userId")
    created_at: LinearDateTime = field(json="createdAt")
    updated_at: LinearDateTime = field(json="updatedAt")


class AttachmentSourceType(SerializableEnum):
    API = "api"
    GITHUB = "github"


@dataclass(kw_only=True)
class AttachmentSource(SerializableAttrs):
    type: AttachmentSourceType
    image_url: Optional[str] = field(json="imageUrl", default=None)
    pull_request_id: Optional[str] = field(json="pullRequestId", default=None)


@dataclass(kw_only=True)
class Attachment(SerializableAttrs, LinearEventData):
    id: UUID
    title: str
    url: str
    source: AttachmentSource
    # metadata: ???
    issue_id: UUID = field(json="issueId")
    created_at: LinearDateTime = field(json="createdAt")
    updated_at: LinearDateTime = field(json="updatedAt")


@dataclass
class UpdatedFrom(SerializableAttrs):
    subscriber_ids: List[UUID] = field(json="subscriberIds")
    updated_at: LinearDateTime = field(json="updatedAt")


@dataclass
class LinearActor(SerializableAttrs):
    id: UUID
    type: str = "user" # or integration
    email: Optional[str] = None
    name: Optional[str] = None
    avatar_url: str = field(json="avatarUrl", default="")

LinearEventContent = Union[Issue, Comment, Reaction, LabelEvent, Attachment]
type_to_class = {
    LinearEventType.ISSUE: Issue,
    LinearEventType.COMMENT: Comment,
    LinearEventType.REACTION: Reaction,
    LinearEventType.PROJECT: Obj,
    LinearEventType.ISSUE_LABEL: LabelEvent,
    LinearEventType.ATTACHMENT: Attachment,
}


@dataclass(kw_only=True)
class LinearEvent(SerializableAttrs):
    action: EventAction
    created_at: LinearDateTime = field(json="createdAt")
    type: LinearEventType
    data: LinearEventContent
    actor: Optional[LinearActor] = None
    url: Optional[str] = None
    organization_id: Optional[UUID] = field(json="organizationId", default=None)

    @classmethod
    def deserialize(cls, data: JSON) -> 'LinearEvent':
        event_type = LinearEventType.deserialize(data["type"])
        data["data"] = type_to_class[event_type].deserialize(data["data"])
        return super().deserialize(data)


LINEAR_ENUMS = {
    "EventType": LinearEventType,
    "EventAction": EventAction,
    "IssueStateType": IssueStateType,
}
