from typing import Tuple, Dict, List, Union, Optional, Match, NamedTuple, Any, TYPE_CHECKING
from uuid import UUID, uuid4
import json
import re

from yarl import URL
from attr import dataclass

from mautrix.util.logging import TraceLogger
from mautrix.types import SerializableAttrs

from .types import Issue, User, full_issue_query, comment_and_close_issue_query
from ...api import LinearClient, LinearError, GraphQLError

if TYPE_CHECKING:
    from ...bot import LinearBot

issue_path_regex = re.compile(r"/?(?P<repo>.+?)/-/issues/(?P<issue>\d+)")
markdown_link_regex = re.compile(r"\[(?P<text>.+?)]\(/(?P<path>uploads/.+?)\)")


@dataclass
class LabelMapping(SerializableAttrs):
    label: Optional[UUID] = None
    state: Optional[UUID] = None
    team: Optional[UUID] = None


class MigrationResult(NamedTuple):
    gitlab_id: str
    linear_url: str
    linear_id: str


class MigrationURLParseError(ValueError):
    pass


class GitLabError(Exception):
    pass


class MigrationError(Exception):
    def __init__(self, message: str, gitlab_id: str) -> None:
        super().__init__(message)
        self.gitlab_id = gitlab_id


class GitLabMigrator:
    bot: 'LinearBot'
    log: TraceLogger
    gitlab_url: URL
    gitlab_token: str
    _label_mapping: Dict[str, LabelMapping]
    _label_name_mapping: Dict[str, str]
    _team_mapping: Dict[str, UUID]
    _user_mapping: Dict[str, Union[UUID, str, None]]

    def __init__(self, bot: 'LinearBot') -> None:
        self.bot = bot
        self.log = bot.log.getChild("migration")
        self._label_mapping = {}
        self._label_name_mapping = {}
        self._team_mapping = {}
        self._user_mapping = {}

    @property
    def label_mapping(self) -> Dict[str, LabelMapping]:
        return self._label_mapping

    @label_mapping.setter
    def label_mapping(self, mapping: Dict[Union[str, List[str]], Dict[str, str]]) -> None:
        self._label_mapping = {
            str(label_name).lower(): LabelMapping.deserialize(target)
            for label_names, target in mapping.items()
            for label_name in ([label_names] if isinstance(label_names, str) else label_names)
        }

    @property
    def label_name_mapping(self) -> Dict[str, str]:
        return self._label_name_mapping

    @label_name_mapping.setter
    def label_name_mapping(self, mapping: Dict[str, str]) -> None:
        self._label_name_mapping = {gitlab_name.lower(): linear_name
                                    for gitlab_name, linear_name in mapping.items()}

    @property
    def team_mapping(self) -> Dict[str, UUID]:
        return self._team_mapping

    @team_mapping.setter
    def team_mapping(self, mapping: Dict[str, str]) -> None:
        self._team_mapping = {repo_name: UUID(team_id)
                              for repo_name, team_id in mapping.items()}

    @property
    def user_mapping(self) -> Dict[str, Union[UUID, str, None]]:
        return self._user_mapping

    @user_mapping.setter
    def user_mapping(self, mapping: Dict[str, Optional[str]]) -> None:
        self._user_mapping = {
            username: UUID(value) if value is not None and value != "self" else value
            for username, value in mapping.items()
        }

    async def gitlab_graphql(self, payload: Dict[str, Any], action: str) -> Dict[str, Any]:
        resp = await self.bot.http.post(self.gitlab_url / "api" / "graphql", json=payload,
                                        headers={"Authorization": f"Bearer {self.gitlab_token}"})
        if resp.status != 200:
            self.log.warning(f"Got HTTP {resp.status} while {action}:\n%s", await resp.text())
            raise GitLabError(f"Got non-successful response while {action}")
        try:
            json_data = await resp.json()
        except json.JSONDecodeError as e:
            self.log.warning(f"Got non-JSON response body while {action}:\n%s",
                             await resp.text())
            raise GitLabError(f"Got invalid response while {action}") from e
        if "errors" in json_data:
            error = json_data["errors"][0]["message"]
            raise GitLabError(f"Got GraphQL error while {action}: {error}")
        return json_data

    async def get_issue_details(self, project: str, issue_id: int) -> Optional[Issue]:
        payload = {
            "operationName": "FullIssueDetails",
            "query": full_issue_query,
            "variables": {
                "projectID": project,
                "issueID": str(issue_id),
            },
        }
        json_data = await self.gitlab_graphql(payload, "getting GitLab issue details")
        try:
            issue_data = json_data["data"]["project"]["issue"]
        except KeyError as e:
            self.log.warning("Didn't find response data while getting GitLab issue details:\n%s",
                             json_data)
            raise GitLabError("Got invalid response while getting GitLab issue details") from e
        else:
            if issue_data is None:
                return None
            return Issue.deserialize(issue_data)

    async def comment_and_close_issue(self, project: str, issue_id: int, noteable_id: str,
                                      text: str) -> None:
        payload = {
            "operationName": "CommentAndCloseIssue",
            "query": comment_and_close_issue_query,
            "variables": {
                "projectID": project,
                "issueID": str(issue_id),
                "noteableID": noteable_id,
                "closeText": text,
            },
        }
        resp = await self.gitlab_graphql(payload, "closing GitLab issue")
        print("GitLab issue close response:", resp)

    def parse_issue_url(self, url: URL) -> Tuple[str, int]:
        if url.host != self.gitlab_url.host:
            raise MigrationURLParseError(f"Unsupported GitLab instance {url.host}")
        match = issue_path_regex.match(url.path)
        if not match:
            raise MigrationURLParseError(f"That doesn't look like the path to an issue")
        repo_name = match.group("repo")
        issue_id = int(match.group("issue"))
        return repo_name, issue_id

    def _get_client(self, user: User) -> Tuple['LinearClient', Optional[User]]:
        try:
            mapped_target = self.user_mapping[user.username]
        except KeyError:
            mapped_target = None
        if mapped_target == "self":
            return self.bot.linear_bot, None
        elif isinstance(mapped_target, UUID):
            client = self.bot.clients.get_by_uuid(mapped_target)
            if client:
                return client, None
        return self.bot.linear_bot, user

    def _quote(self, text: str, repo: str, quoted_user: User) -> str:
        def _replace_relative_url(match: Match) -> str:
            link_text = match.group("text")
            path = match.group("path")
            url = self.gitlab_url / repo / path
            return f"[{link_text}]({url})"

        text = markdown_link_regex.sub(_replace_relative_url, text or "")
        if quoted_user is None:
            return text
        quoted_text = "\n".join(f"> {line}" for line in text.split("\n"))
        return f"[{quoted_user.name}]({quoted_user.url}) said:\n\n{quoted_text}"

    @staticmethod
    def _time_estimate_to_weight(estimate: int) -> Optional[int]:
        if estimate == 0:
            return None
        hours = estimate / 60 / 60
        if hours <= 4:
            return 1
        elif hours < 8:
            return 2
        elif hours <= 12:
            return 3
        elif hours <= 24:
            return 5
        else:
            return 8

    async def migrate(self, client: 'LinearClient', url: str) -> MigrationResult:
        repo_name, issue_num = self.parse_issue_url(URL(url))
        gitlab_id = f"{repo_name}#{issue_num}"
        try:
            team_id = self.team_mapping[repo_name]
        except KeyError as e:
            raise MigrationError(f"GitLab Repo {repo_name} does not have"
                                 " a Linear team ID mapped.", gitlab_id) from e
        own_info = await client.get_self()
        try:
            issue = await self.get_issue_details(repo_name, issue_num)
        except GitLabError as e:
            raise MigrationError("Failed to get GitLab issue details", gitlab_id) from e
        if issue is None:
            raise MigrationError("GitLab issue not found", gitlab_id)

        author_client, quoted_user = self._get_client(issue.author)

        estimate = issue.weight or self._time_estimate_to_weight(issue.time_estimate)
        description = self._quote(issue.description, repo_name, quoted_user)
        description = (f"{description}\n\n"
                       f"Imported from GitLab by @{own_info.display_name}: {issue.url}")
        assignee_id = None
        if len(issue.assignees) > 0:
            assignee_id = self.user_mapping.get(issue.assignees[-1].username)
        labels = []
        state_id = None
        for label in issue.labels:
            try:
                mapping = self.label_mapping[label.title.lower()]
            except KeyError:
                continue
            if mapping.label:
                labels.append(mapping.label)
            if mapping.team:
                team_id = mapping.team
            if mapping.state:
                state_id = mapping.state
        for label in issue.labels:
            try:
                linear_label_name = self.label_name_mapping[label.title.lower()]
                linear_label_id = self.bot.labels.get(team_id, linear_label_name)
                if linear_label_id is None:
                    self.log.warning(f"Didn't find ID for Linear label {linear_label_name} "
                                     f"in {team_id}")
                else:
                    labels.append(linear_label_id)
            except KeyError:
                continue

        self.log.debug(f"Migrating {repo_name}#{issue_num} to {team_id}")
        new_issue_id = uuid4()
        self.bot.linear_webhook.ignore_uuids.add(new_issue_id)
        try:
            resp = await author_client.create_issue(team_id, issue.title, description=description,
                                                    estimate=estimate, labels=labels,
                                                    state_id=state_id, issue_id=new_issue_id,
                                                    assignee_id=assignee_id, retry_count=3)
        except LinearError as e:
            raise MigrationError(str(e), gitlab_id) from e
        assert resp.id == new_issue_id
        self.log.info(f"Successfully created {resp.identifier} ({resp.id}) "
                      f"out of {repo_name}#{issue_num}")

        for comment in reversed(issue.notes):
            if comment.system:
                continue
            comment_client, quoted_user = self._get_client(comment.author)
            body = self._quote(comment.body, repo_name, quoted_user)
            comment_id = uuid4()
            self.bot.linear_webhook.ignore_uuids.add(comment_id)
            try:
                resp_id = await comment_client.create_comment(resp.id, body, comment_id=comment_id,
                                                              retry_count=3)
            except LinearError as e:
                raise MigrationError(str(e), gitlab_id) from e
            assert resp_id == comment_id
            self.log.debug(f"Migrated comment {comment.id} of {repo_name}#{issue_num} "
                           f"to {resp.identifier} ({resp.id}), comment ID {comment_id}")

        close_text = f"Issue was migrated to [{resp.identifier}]({resp.url})"
        await self.comment_and_close_issue(project=repo_name, issue_id=issue_num,
                                           noteable_id=issue.id, text=close_text)

        return MigrationResult(gitlab_id=gitlab_id, linear_url=resp.url, linear_id=resp.identifier)
