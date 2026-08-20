"""
Custom MCP server exposing three GitHub tools:
  1. list_repositories  - list all repos the token's user can access
  2. list_pull_requests - list PRs raised on a specific repo
  3. add_pr_comment     - add a comment to a specific PR

Uses the standalone `fastmcp` package (NOT the old `mcp.server.fastmcp`
path, which broke after mcp==2.0.0 restructured itself).

Run standalone for a quick sanity check:
    python github_mcp_server.py
(it will just idle waiting for an MCP client over stdio — Ctrl+C to exit)
"""

import os
from dotenv import load_dotenv
from github import Github, GithubException
from fastmcp import FastMCP

load_dotenv()

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
if not GITHUB_TOKEN:
    raise RuntimeError("GITHUB_TOKEN not set. Add it to your .env file.")

gh = Github(GITHUB_TOKEN)

mcp = FastMCP("github-pr-agent")


def _get_self_owned_repos():
    """Repos where the authenticated user is the actual owner —
    excludes org repos and repos where the user is only a collaborator.
    """
    return gh.get_user().get_repos(type="owner")


@mcp.tool()
def list_repositories() -> str:
    """List GitHub repositories owned by the authenticated user themselves.
    Excludes organization repos and repos where the user is only a
    collaborator/member — only repos the user personally owns.
    """
    try:
        repos = _get_self_owned_repos()
        results = []
        for repo in repos:
            visibility = "private" if repo.private else "public"
            results.append(f"{repo.full_name} [{visibility}] - {repo.html_url}")
    except GithubException as e:
        return f"Error listing repositories: {e.data.get('message', str(e))}"

    if not results:
        return "No self-owned repositories found for this account."

    return "Repositories owned by you:\n" + "\n".join(results)


@mcp.tool()
def list_all_pull_requests(state: str = "open") -> str:
    """List pull requests across ALL repositories owned by the authenticated
    user (not org repos, not repos the user only collaborates on). Use this
    whenever the user asks to see PRs across all their repos / everything /
    without naming one specific repo — e.g. "show all open prs".

    Args:
        state: One of "open", "closed", or "all". Defaults to "open".
    """
    try:
        repos = list(_get_self_owned_repos())
    except GithubException as e:
        return f"Error listing repositories: {e.data.get('message', str(e))}"

    if not repos:
        return "No self-owned repositories found for this account."

    sections = []
    total = 0
    for repo in repos:
        try:
            pulls = list(repo.get_pulls(state=state, sort="created", direction="desc"))
        except GithubException:
            continue
        if not pulls:
            continue
        total += len(pulls)
        lines = [
            f"  #{pr.number} \"{pr.title}\" by {pr.user.login} "
            f"[{pr.state}] created {pr.created_at.date()} -> {pr.html_url}"
            for pr in pulls
        ]
        sections.append(f"{repo.full_name}:\n" + "\n".join(lines))

    if total == 0:
        return f"No {state} pull requests found across any of your owned repositories."

    return f"{total} {state} pull request(s) across your repositories:\n\n" + "\n\n".join(sections)


@mcp.tool()
def list_pull_requests(repo_full_name: str, state: str = "open") -> str:
    """List pull requests raised on ONE specific GitHub repository that the
    authenticated user owns. Use this when the user names a specific repo.
    For "show all prs" across every repo, use list_all_pull_requests instead.

    Args:
        repo_full_name: Repository in "owner/repo" format, e.g. "octocat/hello-world".
            The owner must be the authenticated user themselves.
        state: One of "open", "closed", or "all". Defaults to "open".
    """
    try:
        repo = gh.get_repo(repo_full_name)
        pulls = repo.get_pulls(state=state, sort="created", direction="desc")
    except GithubException as e:
        return f"Error accessing repo '{repo_full_name}': {e.data.get('message', str(e))}"

    results = []
    for pr in pulls:
        results.append(
            f"#{pr.number} \"{pr.title}\" by {pr.user.login} "
            f"[{pr.state}] created {pr.created_at.date()} -> {pr.html_url}"
        )

    if not results:
        return f"No {state} pull requests found in {repo_full_name}."

    return f"Pull requests in {repo_full_name} ({state}):\n" + "\n".join(results)


@mcp.tool()
def add_pr_comment(repo_full_name: str, pr_number: int, comment: str) -> str:
    """Add a comment to a specific pull request.

    Args:
        repo_full_name: Repository in "owner/repo" format, e.g. "octocat/hello-world".
        pr_number: The pull request number to comment on.
        comment: The comment text to post.
    """
    try:
        repo = gh.get_repo(repo_full_name)
        issue = repo.get_issue(number=pr_number)  # PR comments use the issue-comment API
        created = issue.create_comment(comment)
    except GithubException as e:
        return f"Error commenting on PR #{pr_number} in '{repo_full_name}': {e.data.get('message', str(e))}"

    return f"Comment added to PR #{pr_number} in {repo_full_name}: {created.html_url}"


if __name__ == "__main__":
    mcp.run(transport="stdio")