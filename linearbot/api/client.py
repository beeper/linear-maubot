from typing import Any, Optional, Dict, List, TYPE_CHECKING
from uuid import UUID
import json

from yarl import URL

from .types import User, IssueMeta, IssueCreateResponse, Label
from .queries import (get_user_details, get_user, get_issue, get_labels,
                      create_issue, create_comment, create_reaction, create_label, update_label)

if TYPE_CHECKING:
    from ..bot import LinearBot


class LinearError(Exception):
    pass


class GraphQLError(LinearError):
    def __init__(self, data: Dict[str, Any]) -> None:
        try:
            message = data["extensions"]["userPresentableMessage"]
        except KeyError:
            message = data["message"]
        super().__init__(message)
        self.data = data


class SuccessFalseError(LinearError):
    pass


class LogoutError(LinearError):
    pass


class TokenAlreadyRevokedError(LogoutError):
    pass


class FailedToAuthenticate(LogoutError):
    pass


class LinearClient:
    bot: 'LinearBot'
    own_id: Optional[UUID]
    _cached_self: Optional[User]
    authorization: Optional[str]
    graphql_url = URL("https://api.linear.app/graphql")
    oauth_token_url = URL("https://api.linear.app/oauth/token")
    oauth_revoke_url = URL("https://api.linear.app/oauth/revoke")

    _user_cache: Dict[UUID, User]
    _issue_cache: Dict[UUID, IssueMeta]

    def __init__(self, bot: 'LinearBot', own_id: Optional[UUID] = None,
                 authorization: Optional[str] = None) -> None:
        self.authorization = authorization
        self.own_id = own_id
        self.bot = bot
        self._cached_self = None

        self._user_cache = {}
        self._issue_cache = {}

    async def login(self, oauth_code: str, redirect_uri: str) -> None:
        resp = await self.bot.http.post(self.oauth_token_url, data={
            "code": oauth_code,
            "redirect_uri": redirect_uri,
            "client_id": self.bot.oauth_client_id,
            "client_secret": self.bot.oauth_client_secret,
            "grant_type": "authorization_code",
        })
        resp_body = await resp.json()
        print("Login response:", resp.status, resp_body)
        self.authorization = f"{resp_body['token_type']} {resp_body['access_token']}"

    async def logout(self) -> None:
        resp = await self.bot.http.post(self.oauth_revoke_url,
                                        headers={"Authorization": self.authorization})
        print("Logout response:", resp.status, await resp.json())
        if resp.status != 200:
            try:
                data = await resp.json()
                raise {
                    400: TokenAlreadyRevokedError,
                    401: FailedToAuthenticate,
                }.get(resp.status, LogoutError)(data["error"])
            except (json.JSONDecodeError, KeyError):
                raise LogoutError(f"Unknown error while logging out (HTTP {resp.status})")

    @staticmethod
    def _is_retriable(errors: List[Dict[str, Any]]) -> bool:
        try:
            return errors[0]["extensions"]["code"] == "INTERNAL_SERVER_ERROR"
        except (KeyError, IndexError):
            return False

    async def request(self, query: str, variables: Optional[Dict[str, Any]] = None,
                      operation_name: Optional[str] = None, retry_count: int = 0) -> Any:
        data = {
            "operationName": operation_name,
            "query": query,
            "variables": variables,
        }
        data = {k: v for k, v in data.items() if v is not None}
        headers = {"Authorization": self.authorization}
        while True:
            resp = await self.bot.http.post(self.graphql_url, json=data, headers=headers)
            resp_data = await resp.json()
            print("GraphQL response:", resp.status, resp_data)
            try:
                errors = resp_data["errors"]
                if retry_count > 0 and self._is_retriable(errors):
                    continue
                elif len(errors) > 0:
                    raise GraphQLError(errors[0])
            except KeyError:
                pass
            try:
                return resp_data["data"]
            except KeyError:
                raise LinearError("Didn't get data from GraphQL request")

    async def get_self(self) -> User:
        if self._cached_self is not None:
            return self._cached_self
        resp = await self.request(get_user_details)
        user = User.deserialize(resp["viewer"])
        self._cached_self = user
        self.own_id = user.id
        return user

    async def get_user(self, user_id: UUID) -> User:
        try:
            return self._user_cache[user_id]
        except KeyError:
            resp = await self.request(get_user, variables={"userID": str(user_id)})
            user = User.deserialize(resp["user"])
            self._user_cache[user.id] = user
            return user

    async def get_issue(self, issue_id: UUID) -> IssueMeta:
        try:
            return self._issue_cache[issue_id]
        except KeyError:
            resp = await self.request(get_issue, variables={"issueID": str(issue_id)})
            issue = IssueMeta.deserialize(resp["issue"])
            self._issue_cache[issue.id] = issue
            return issue

    async def get_all_labels(self) -> Dict[UUID, Dict[str, Label]]:
        teams = {}
        has_next_page = True
        cursor = None
        while has_next_page:
            resp = await self.request(get_labels, variables={"cursor": cursor})
            for raw_label in resp["issueLabels"]["nodes"]:
                label = Label.deserialize(raw_label)
                teams.setdefault(label.team.id, {})[label.name] = label
            has_next_page = resp["issueLabels"]["pageInfo"]["hasNextPage"]
            cursor = resp["issueLabels"]["pageInfo"]["endCursor"]
        return teams

    @staticmethod
    def _filter_none_and_uuid(data: Dict[str, Any]) -> Dict[str, Any]:
        return {k: (str(v) if isinstance(v, UUID) else v)
                for k, v in data.items() if v is not None}

    async def create_label(self, team_id: UUID, name: str, description: Optional[str] = None,
                           color: Optional[str] = None, label_id: Optional[UUID] = None,
                           retry_count: int = 0) -> UUID:
        label_input = self._filter_none_and_uuid({
            "id": label_id,
            "teamId": team_id,
            "name": name,
            "description": description,
            "color": color,
        })
        resp = await self.request(create_label, {"input": label_input}, retry_count=retry_count)
        if not resp["issueLabelCreate"]["success"]:
            raise SuccessFalseError("Failed to create label")
        return UUID(resp["issueLabelCreate"]["issueLabel"]["id"])

    async def update_label(self, label_id: UUID, name: Optional[str] = None,
                           description: Optional[str] = None, color: Optional[str] = None,
                           retry_count: int = 0) -> None:
        update_input = self._filter_none_and_uuid({
            "name": name,
            "description": description,
            "color": color,
        })
        resp = await self.request(update_label, {"labelID": label_id, "input": update_input},
                                  retry_count=retry_count)
        if not resp["issueLabelUpdate"]["success"]:
            raise SuccessFalseError("Failed to update label")

    async def create_issue(self, team_id: UUID, title: str, description: str,
                           estimate: Optional[int] = None, labels: Optional[List[UUID]] = None,
                           state_id: Optional[UUID] = None, assignee_id: Optional[UUID] = None,
                           issue_id: Optional[UUID] = None, retry_count: int = 0
                           ) -> IssueCreateResponse:
        issue_input = self._filter_none_and_uuid({
            "id": issue_id,
            "teamId": team_id,
            "title": title,
            "description": description,
            "estimate": estimate,
            "stateId": state_id,
            "assigneeId": assignee_id,
            "labelIds": [str(label_id) for label_id in (labels or [])]
        })
        resp = await self.request(create_issue, {"input": issue_input}, retry_count=retry_count)
        if not resp["issueCreate"]["success"]:
            raise SuccessFalseError("Failed to create issue")
        return IssueCreateResponse.deserialize(resp["issueCreate"]["issue"])

    async def create_comment(self, issue_id: UUID, body: str, comment_id: Optional[UUID] = None,
                             retry_count: int = 0) -> UUID:
        comment_input = self._filter_none_and_uuid({
            "id": comment_id,
            "issueId": issue_id,
            "body": body,
        })
        resp = await self.request(create_comment, {"input": comment_input}, retry_count=retry_count)
        if not resp["commentCreate"]["success"]:
            raise SuccessFalseError("Failed to create comment")
        return UUID(resp["commentCreate"]["comment"]["id"])

    async def create_reaction(self, comment_id: UUID, emoji: str,
                              reaction_id: Optional[UUID] = None, retry_count: int = 0) -> UUID:
        reaction_input = self._filter_none_and_uuid({
            "commentID": comment_id,
            "emoji": emoji,
            "reactionID": reaction_id,
        })
        resp = await self.request(create_reaction, reaction_input, retry_count=retry_count)
        if not resp["reactionCreate"]["success"]:
            raise SuccessFalseError("Failed to create reaction")
        return UUID(resp["reactionCreate"]["reaction"]["id"])
