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
def get_pull_request_diff(repo_full_name: str, pr_number: int) -> str:
    """Fetch the actual code changes (diff) for a specific pull request, so
    they can be reviewed for correctness. Returns each changed file's name,
    change type, and unified diff patch. Use this before judging whether a
    PR's code looks correct or suggesting a review comment — never guess at
    code changes without fetching this first.

    Large diffs are truncated per-file and capped in total file count to
    stay a reasonable size; if a diff looks cut off, mention that in your
    analysis rather than assuming you saw everything.

    Args:
        repo_full_name: Repository in "owner/repo" format, e.g. "octocat/hello-world".
            The owner must be the authenticated user themselves.
        pr_number: The pull request number to fetch the diff for.
    """
    MAX_FILES = 25
    MAX_PATCH_CHARS = 3000

    try:
        repo = gh.get_repo(repo_full_name)
        pr = repo.get_pull(pr_number)
        files = list(pr.get_files())
    except GithubException as e:
        return f"Error fetching PR #{pr_number} in '{repo_full_name}': {e.data.get('message', str(e))}"

    if not files:
        return f"PR #{pr_number} in {repo_full_name} has no file changes."

    truncated_file_list = files[:MAX_FILES]
    sections = [
        f"PR #{pr_number}: \"{pr.title}\" by {pr.user.login}\n"
        f"{len(files)} file(s) changed, +{pr.additions}/-{pr.deletions}\n"
        f"head ref: {pr.head.ref} (sha: {pr.head.sha})\n"
        f"base ref: {pr.base.ref}\n"
        f"(use this head sha/ref with list_repository_files or get_file_content "
        f"to pull extra context — e.g. a function's full definition or a file "
        f"the diff calls into but doesn't show)\n"
    ]

    for f in truncated_file_list:
        patch = f.patch or "(no textual diff available — likely a binary file)"
        if len(patch) > MAX_PATCH_CHARS:
            patch = patch[:MAX_PATCH_CHARS] + "\n... [patch truncated for length] ..."
        sections.append(
            f"--- {f.filename} ({f.status}, +{f.additions}/-{f.deletions}) ---\n{patch}"
        )

    if len(files) > MAX_FILES:
        sections.append(
            f"\n[Only showing {MAX_FILES} of {len(files)} changed files — diff truncated.]"
        )

    return "\n\n".join(sections)


@mcp.tool()
def list_repository_files(repo_full_name: str, ref: str = "") -> str:
    """List all file paths in a repository at a given ref (branch, tag, or
    commit SHA). Use this while reviewing a PR to see what other files exist
    in the codebase, so you can decide which ones to fetch with
    get_file_content for extra context (e.g. finding the file that defines a
    function the PR's diff calls but doesn't show).

    Args:
        repo_full_name: Repository in "owner/repo" format.
        ref: Branch/tag/commit SHA to list files at. Leave empty to use the
            repo's default branch. When reviewing a specific PR, prefer the
            PR's head sha/ref (returned by get_pull_request_diff) so you see
            the codebase as it looks in that PR, not just the base branch.
    """
    MAX_FILES = 300
    try:
        repo = gh.get_repo(repo_full_name)
        ref = ref or repo.default_branch
        tree = repo.get_git_tree(ref, recursive=True)
    except GithubException as e:
        return f"Error listing files in '{repo_full_name}' at ref '{ref}': {e.data.get('message', str(e))}"

    files = [item.path for item in tree.tree if item.type == "blob"]
    if not files:
        return f"No files found in {repo_full_name}@{ref}."

    shown = files[:MAX_FILES]
    result = f"{len(files)} file(s) in {repo_full_name}@{ref}:\n" + "\n".join(shown)
    if len(files) > MAX_FILES:
        result += f"\n... [{len(files) - MAX_FILES} more not shown — narrow down by directory if needed]"
    return result


@mcp.tool()
def get_file_content(repo_full_name: str, path: str, ref: str = "") -> str:
    """Fetch the text content of one specific file, for extra context when
    reviewing a PR — e.g. seeing the full definition of a function the diff
    modifies, or a file the diff imports/calls but doesn't show.

    Args:
        repo_full_name: Repository in "owner/repo" format.
        path: File path within the repo, e.g. "src/utils/helpers.py". Get
            valid paths from list_repository_files first if unsure.
        ref: Branch/tag/commit SHA to read the file at. Leave empty to use
            the repo's default branch. When reviewing a specific PR, prefer
            the PR's head sha/ref (from get_pull_request_diff) so the file
            content matches what's actually in that PR.
    """
    MAX_CHARS = 8000
    try:
        repo = gh.get_repo(repo_full_name)
        ref = ref or repo.default_branch
        content_file = repo.get_contents(path, ref=ref)
    except GithubException as e:
        return f"Error reading '{path}' in '{repo_full_name}' at ref '{ref}': {e.data.get('message', str(e))}"

    if isinstance(content_file, list):
        return f"'{path}' is a directory, not a file. Use list_repository_files to browse it."

    try:
        text = content_file.decoded_content.decode("utf-8", errors="replace")
    except Exception as e:
        return f"Could not decode '{path}' as text (likely a binary file): {e}"

    note = ""
    if len(text) > MAX_CHARS:
        text = text[:MAX_CHARS]
        note = "\n... [file truncated for length] ..."

    return f"--- {path} (ref: {ref}) ---\n{text}{note}"


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