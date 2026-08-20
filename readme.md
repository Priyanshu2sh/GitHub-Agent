# GitHub PR Assistant

A chat-based AI agent that lets you (and your team) ask about your GitHub repos and pull requests in plain English — and post PR comments — without leaving the chat window.

Built with:
- **Streamlit** — chat UI
- **Google Gemini** (`gemini-3.1-flash-lite`) — decides what the user wants and which tool to call
- **A custom MCP server** (via `fastmcp`) — the actual GitHub actions, kept separate from the LLM
- **PyGithub** — talks to the GitHub REST API

Scope: all tools are restricted to repositories you personally own (not orgs, not repos you're only a collaborator on).

## What it can do

- "what repos do i have" — lists your self-owned repos
- "show all open prs" — aggregates open PRs across every repo you own
- "list open prs on my-repo-name" — PRs on one specific repo
- "add comment 'looks good' on PR #12 in my-repo-name" — posts a comment

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
2. Generate a new token with the **`repo`** scope (needed to read PRs and post comments)
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
> quit
```

### Run the actual app

```bash
streamlit run app.py
```

This opens the chat UI in your browser at `http://localhost:8501`. Ask it things like:
- "what repos do i have"
- "show all open prs"
- "add comment 'thanks, merging this' on PR #4 in my-repo"

Use the **Reset conversation** button in the sidebar to reconnect and clear chat history.

## Security notes

- Your `GITHUB_TOKEN` grants real write access (comments) to your repos — keep `.env` private and never commit it.
- Consider scoping your PAT as narrowly as possible (fine-grained tokens limited to specific repos) if you plan to deploy this beyond local/personal use.
- Rotate both tokens if you ever suspect either has been exposed.