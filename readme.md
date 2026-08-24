# GitHub PR Assistant

A chat-based AI agent that lets you (and your team) ask about your GitHub repos and pull requests in plain English, get AI code review on a PR's actual diff, and post PR comments or full inline reviews — without leaving the chat window.

Built with:
- **Streamlit** — chat UI
- **Google Gemini** (`gemini-3.1-flash-lite`) — decides what the user wants, which tool to call, and does the actual code-review reasoning over a PR's diff
- **A custom MCP server** (via `fastmcp`) — the actual GitHub actions, kept separate from the LLM
- **PyGithub** — talks to the GitHub REST API

Scope: all tools are restricted to repositories you personally own (not orgs, not repos you're only a collaborator on).

## What it can do

**Browsing:**
- "what repos do i have" — lists your self-owned repos
- "show all open prs" — aggregates open PRs across every repo you own
- "list open prs on my-repo-name" — PRs on one specific repo

**Code review:**
- "review PR #12 in my-repo" / "is the code correct in https://github.com/you/my-repo/pull/12" — fetches the PR's actual diff, reasons over it for bugs/logic errors/edge cases, and pulls in extra files from the repo for context if the diff alone isn't enough to judge
- Paste a PR link directly — it's resolved into the repo + PR number automatically, no need to name them separately

**Commenting:**
- "add comment 'looks good' on PR #12 in my-repo-name" — posts a single general comment
- After a review, the assistant drafts a summary plus specific file-and-line comments (like GitHub's own "Files changed" review comments) and **waits for your explicit approval** before posting anything — nothing is posted to a PR without you confirming the wording first

## Project structure

```
github-pr-agent/
├── requirements.txt        # Python dependencies
├── .env.example             # template for your secrets — copy to .env
├── .gitignore
├── github_mcp_server.py     # MCP server: defines the GitHub tools
├── agent.py                 # bridges Gemini function-calling to the MCP server
└── app.py                   # Streamlit chat UI
```

### Available tools (defined in `github_mcp_server.py`)

| Tool | Purpose |
|---|---|
| `list_repositories` | List your self-owned repos |
| `list_all_pull_requests` | Aggregate PRs across all self-owned repos |
| `list_pull_requests` | PRs on one named repo |
| `resolve_pr_url` | Parse a pasted PR link into repo + PR number |
| `get_pull_request_diff` | Fetch a PR's diff, with new-file line numbers for each changed line |
| `list_repository_files` | Browse the file tree at a given branch/commit |
| `get_file_content` | Read one specific file's content, for extra review context |
| `add_pr_review` | Post a review: overall summary + inline comments on specific files/lines |
| `add_pr_comment` | Post a single general (non-inline) comment |

## Prerequisites

- Python 3.10 or newer
- A GitHub account
- A Google AI Studio account (for a Gemini API key)

## Setup

### 1. Clone the repo

```bash
git clone <your-repo-url>
cd GitHub-Agent
```

### 2. Create a virtual environment (recommended)

```bash
python -m venv .venv
source .venv/bin/activate      # on Windows: .venv\Scripts\activate
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Get a GitHub Personal Access Token (PAT)

1. Go to GitHub → **Settings → Developer settings → Personal access tokens → Tokens (classic)** (or fine-grained, see note below)
2. Generate a new token with the **`repo`** scope (needed to read PRs/diffs/files and to post comments and reviews)
3. Copy the token — you won't be able to see it again

> Fine-grained tokens work too — just make sure "Pull requests" is set to Read and write, and "Contents"/"Metadata" to Read, for the repos you want it to access.

### 5. Get a Gemini API key

1. Go to [Google AI Studio](https://aistudio.google.com/)
2. Create an API key
3. Copy it

### 6. Configure your environment variables

```bash
cp .env.example .env
```

Then open `.env` and fill in:

```
GITHUB_TOKEN=ghp_your_actual_token_here
GEMINI_API_KEY=your_actual_gemini_key_here
```

**Never commit your `.env` file.** It's already excluded via `.gitignore`.

## Running it

### Quick sanity check (optional, before the full UI)

Test the MCP server starts cleanly:
```bash
python github_mcp_server.py
```
It should idle silently, waiting for a client — that means it started correctly. Press `Ctrl+C` to stop.

Test the agent + tool-calling loop from the terminal:
```bash
python agent.py
```
Try typing things like:
```
> what repos do i have
> show all open prs
> review PR #3 in my-repo
> quit
```

### Run the actual app

```bash
streamlit run app.py
```

This opens the chat UI in your browser at `http://localhost:8501`. Ask it things like:
- "what repos do i have"
- "show all open prs"
- "review https://github.com/you/my-repo/pull/12, is the code correct?"
- "add comment 'thanks, merging this' on PR #4 in my-repo"

For a review, it'll show you its analysis and a draft of any suggested comments first — reply with something like "yes post it" (or ask for edits) before it actually posts anything to GitHub.

Use the **Reset conversation** button in the sidebar to reconnect and clear chat history.

## Troubleshooting

**`ModuleNotFoundError: No module named 'mcp.server.fastmcp'`**
Make sure `requirements.txt` installed the standalone `fastmcp` package (pinned `<3.0.0`), not an unbounded `mcp` package. Run `pip uninstall -y mcp fastmcp` then `pip install -r requirements.txt` again.

**Gemini model errors ("model not found")**
Double-check the exact model string available in your Google AI Studio account matches `MODEL_NAME` in `agent.py`, and update it if needed.

**Empty repo/PR lists**
Confirm your PAT has the `repo` scope and that you're the actual **owner** (not just a collaborator) of the repos you're testing with — this tool is scoped to self-owned repos only by design.

**`add_pr_review` fails with an error about an invalid line**
GitHub only accepts inline review comments on lines that are actually part of the diff. This can happen if the diff changed since it was last fetched — ask for the review again to get fresh line numbers before retrying.

## Security notes

- Your `GITHUB_TOKEN` grants real write access (comments, reviews) to your repos — keep `.env` private and never commit it.
- Consider scoping your PAT as narrowly as possible (fine-grained tokens limited to specific repos) if you plan to deploy this beyond local/personal use.
- Nothing is posted to a PR without an explicit approval step in chat first — the assistant always drafts comments/reviews and waits for your go-ahead before calling a posting tool.
- Rotate both tokens if you ever suspect either has been exposed.