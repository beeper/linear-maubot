from typing import Any, Optional, Dict, List, TYPE_CHECKING
from uuid import UUID
import json

from yarl import URL

from .types import User, IssueCreateResponse
from .queries import get_user_details, create_issue, create_comment

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

    def __init__(self, bot: 'LinearBot', own_id: Optional[UUID] = None,
                 authorization: Optional[str] = None) -> None:
        self.authorization = authorization
        self.own_id = own_id
        self.bot = bot
        self._cached_self = None

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

    async def request(self, query: str, variables: Optional[Dict[str, Any]] = None,
                      operation_name: Optional[str] = None) -> Any:
        data = {
            "operationName": operation_name,
            "query": query,
            "variables": variables,
        }
        data = {k: v for k, v in data.items() if v is not None}
        headers = {"Authorization": self.authorization}
        resp = await self.bot.http.post(self.graphql_url, json=data, headers=headers)
        resp_data = await resp.json()
        print("GraphQL response:", resp.status, resp_data)
        try:
            errors = resp_data["errors"]
            if len(errors) > 0:
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

    async def create_issue(self, team_id: UUID, title: str, description: str,
                           estimate: Optional[int] = None, labels: Optional[List[UUID]] = None,
                           state_id: Optional[UUID] = None, assignee_id: Optional[UUID] = None,
                           issue_id: Optional[UUID] = None) -> IssueCreateResponse:
        issue_input = {
            "id": issue_id,
            "teamId": team_id,
            "title": title,
            "description": description,
            "estimate": estimate,
            "stateId": state_id,
            "assigneeId": assignee_id,
            "labelIds": [str(label_id) for label_id in (labels or [])]
        }
        issue_input = {k: (str(v) if isinstance(v, UUID) else v)
                       for k, v in issue_input.items() if v is not None}
        resp = await self.request(create_issue, {"input": issue_input})
        if not resp["issueCreate"]["success"]:
            raise SuccessFalseError("Failed to create issue")
        return IssueCreateResponse.deserialize(resp["issueCreate"]["issue"])

    async def create_comment(self, issue_id: UUID, body: str, comment_id: Optional[UUID] = None
                             ) -> UUID:
        comment_input = {
            "id": str(comment_id) if comment_id else None,
            "issueId": str(issue_id),
            "body": body,
        }
        comment_input = {k: v for k, v in comment_input.items() if v is not None}
        resp = await self.request(create_comment, {"input": comment_input})
        if not resp["commentCreate"]["success"]:
            raise SuccessFalseError("Failed to create comment")
        return UUID(resp["commentCreate"]["comment"]["id"])
