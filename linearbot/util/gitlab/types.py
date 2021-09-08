from typing import List, NewType
from datetime import datetime

from yarl import URL
from attr import dataclass

from mautrix.types import SerializableAttrs, field, JSON, deserializer

GitLabTimestamp = NewType('GitLabTimestamp', datetime)


@deserializer(GitLabTimestamp)
def deserialize_gl_timestamp(data: str) -> GitLabTimestamp:
    return GitLabTimestamp(datetime.strptime(data, "%Y-%m-%dT%H:%M:%S%z"))


def deserialize_list_as_nodes(cls: SerializableAttrs) -> SerializableAttrs:
    @deserializer(List[cls])
    def _deserialize_list(data: JSON) -> List[cls]:
        return [cls.deserialize(item) for item in data["nodes"]]

    return cls


@deserialize_list_as_nodes
@dataclass
class User(SerializableAttrs):
    name: str
    username: str
    url: str = field(json="webUrl")


@deserialize_list_as_nodes
@dataclass
class Label(SerializableAttrs):
    title: str


@deserialize_list_as_nodes
@dataclass
class Note(SerializableAttrs):
    id: str
    body: str
    system: bool
    url: str
    author: User
    created_at: GitLabTimestamp = field(json="createdAt")


@dataclass(kw_only=True)
class Issue(SerializableAttrs):
    author: User
    id: str
    created_at: GitLabTimestamp = field(json="createdAt")
    title: str
    description: str
    weight: int
    url: str = field(json="webUrl")
    time_estimate: int = field(json="timeEstimate")
    assignees: List[User]
    labels: List[Label]
    notes: List[Note]


# language=graphql
full_issue_query = """
query FullIssueDetails($projectID: ID!, $issueID: String!) {
    project(fullPath: $projectID) {
        issue(iid: $issueID) {
            author {
                name
                username
                webUrl
            }
            id
            createdAt
            title
            description
            weight
            webUrl
            timeEstimate
            assignees {
                nodes {
                    name
                    username
                    webUrl
                }
            }
            labels {
                nodes {
                    title
                }
            }
            notes {
                nodes {
                    id
                    body
                    system
                    url
                    createdAt
                    author {
                        name
                        username
                        webUrl
                    }
                }
            }
        }
    }
}
"""

# language=graphql
comment_and_close_issue_query = """
mutation CommentAndCloseIssue($projectID: ID!, $issueID: String!, $noteableID: NoteableID!,
                              $closeText: String!) {
    createNote(input: {
        noteableId: $noteableID,
        body: $closeText,
    }) {
        errors
    }
    updateIssue(input: {
        iid: $issueID,
        projectPath: $projectID,
        stateEvent: CLOSE,
    }) {
        errors
    }
}
"""
