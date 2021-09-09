# language=graphql
get_user_details = """query UserDetails {
    viewer {
        id
        name
        displayName
        email
        url
        organization {
            id
            name
            urlKey
        }
    }
}"""

# language=graphql
get_user = """query GetUser($userID: String!) {
    user(id: $userID) {
        id
        name
        displayName
        email
        url
    }
}"""

# language=graphql
get_issue = """query GetIssue($issueID: String!) {
    issue(id: $issueID) {
        id
        title
        identifier
        url
    }
}"""

# language=graphql
create_issue = """mutation CreateIssue($input: IssueCreateInput!) {
    issueCreate(input: $input) {
        success
        issue {
            id
            title
            identifier
            url
        }
    }
}"""

# language=graphql
create_comment = """mutation CreateComment($input: CommentCreateInput!) {
    commentCreate(input: $input) {
        success
        comment {
            id
        }
    }
}"""

# language=graphql
create_reaction = """mutation CreateReaction($commentID: String!, $emoji: String!, $reactionID: String!) {
    reactionCreate(input: {commentId: $commentID, emoji: $emoji, id: $reactionID}) {
        success
        reaction {
            id
        }
    }
}"""
