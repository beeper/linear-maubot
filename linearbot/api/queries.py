# language=graphql
get_user_details = """query UserDetails {
    viewer {
        id
        name
        displayName
        email
        organization {
            id
            name
            urlKey
        }
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
