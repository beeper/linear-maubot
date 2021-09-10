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

# language=graphql
get_labels = """query GetLabels($cursor: String) {
    issueLabels(after: $cursor, first: 50) {
        nodes {
            id
            name
            description
            color
            createdAt
            updatedAt
            team {
                id
                key
                name
            }
        }
        pageInfo {
            endCursor
            hasNextPage
        }
    }
}"""

# language=graphql
create_label = """mutation CreateLabel($input: IssueLabelCreateInput!) {
    issueLabelCreate(input: $input) {
        success
        issueLabel {
            id
        }
    }
}"""

# language=graphql
update_label = """mutation UpdateLabel($labelID: String!, $input: IssueLabelUpdateInput!) {
    issueLabelUpdate(id: $labelID, input: $input) {
        success
    }
}"""
