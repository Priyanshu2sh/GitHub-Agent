"""
Bridges Gemini function-calling with our custom MCP server.

Responsibilities:
  1. Launch github_mcp_server.py as an MCP subprocess (via fastmcp.Client).
  2. Discover its tools and convert their schemas into Gemini
     FunctionDeclaration format.
  3. Run one chat turn: send user message -> if Gemini requests a tool call,
     execute it against the MCP server -> feed the result back to Gemini ->
     return the final natural-language answer.

This file has no UI code — Step 3 (Streamlit) just imports GitHubChatAgent.
"""

import os
import copy
import asyncio
from dotenv import load_dotenv

from fastmcp import Client
from google import genai
from google.genai import types

load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
if not GEMINI_API_KEY:
    raise RuntimeError("GEMINI_API_KEY not set. Add it to your .env file.")

MODEL_NAME = "gemini-3.1-flash-lite"
SERVER_SCRIPT = os.path.join(os.path.dirname(__file__), "github_mcp_server.py")

SYSTEM_INSTRUCTION = (
    "You are a helpful assistant that answers questions about a team's GitHub "
    "activity and reviews code by calling the available tools: "
    "list_repositories, list_pull_requests, list_all_pull_requests, "
    "get_pull_request_diff, and add_pr_comment. "
    "IMPORTANT SCOPE RULE: every tool here is already restricted server-side "
    "to repositories owned by the authenticated user themselves — never repos "
    "owned by other people or organizations. You don't need to filter results "
    "yourself; just pass through what the tools return. "
    "Tool selection: if the user names a specific repo (or gives enough to "
    "resolve one via list_repositories), use list_pull_requests for that repo. "
    "If the user asks broadly — 'show all open prs', 'what prs do i have', "
    "'list everything', with no specific repo named — use "
    "list_all_pull_requests instead of calling list_pull_requests repeatedly. "
    "\n\n"
    "CODE REVIEW WORKFLOW: if the user asks you to review a PR, check if the "
    "code is correct, or find issues in a PR, do NOT guess — always call "
    "get_pull_request_diff first to see the actual changes. Then reason "
    "through the diff yourself: look for logic errors, bugs, missing edge "
    "cases, obvious style/security issues, or anything inconsistent with "
    "the rest of the changed code. This analysis is entirely your own "
    "judgment — no tool does this for you. "
    "If the diff alone isn't enough to judge correctness — e.g. it calls a "
    "function not shown in the diff, extends a class defined elsewhere, or "
    "you need to see how something is used elsewhere in the codebase — use "
    "list_repository_files and get_file_content to pull in exactly the "
    "extra files you need, using the PR's head sha/ref from "
    "get_pull_request_diff. Don't fetch the whole repo indiscriminately — "
    "only pull files that are actually relevant to judging the diff's "
    "correctness, to keep things efficient. "
    "If you find nothing concerning, tell the user the diff looks correct "
    "and briefly say what you checked; do not invent problems to seem useful. "
    "If you find issues, draft a specific, constructive suggested comment "
    "(reference the file and what's wrong) and show it to the user — but do "
    "NOT call add_pr_comment yet. Wait for the user to explicitly approve, "
    "edit, or reject it in their next message before posting anything. Only "
    "call add_pr_comment after that explicit go-ahead, using the "
    "final-approved wording. "
    "\n\n"
    "Always resolve a repository name to the 'owner/repo' format before "
    "calling list_pull_requests or add_pr_comment — if unsure of the owner, "
    "call list_repositories first to find the correct full name. Before "
    "actually posting a comment with add_pr_comment, briefly confirm the PR "
    "number, repo, and comment text back to the user in your reply. Keep "
    "responses concise and use plain text, not markdown."
)


def _clean_schema(schema: dict) -> dict:
    """Strip JSON-schema fields Gemini's function schema doesn't accept."""
    if not isinstance(schema, dict):
        return schema
    schema = copy.deepcopy(schema)
    for key in ("title", "additionalProperties", "$schema"):
        schema.pop(key, None)
    if "properties" in schema:
        for prop_name, prop_schema in schema["properties"].items():
            schema["properties"][prop_name] = _clean_schema(prop_schema)
    return schema


class GitHubChatAgent:
    """Wraps the MCP client + Gemini client and manages a chat session."""

    def __init__(self):
        self.mcp_client = Client(SERVER_SCRIPT)
        self.genai_client = genai.Client(api_key=GEMINI_API_KEY)
        self.gemini_tool = None   # built after discovering MCP tools
        self.history = []         # list[types.Content]
        self._entered = False

    async def start(self):
        """Connect to the MCP server and discover tools. Call once before chat()."""
        await self.mcp_client.__aenter__()
        self._entered = True

        mcp_tools = await self.mcp_client.list_tools()
        function_declarations = []
        for tool in mcp_tools:
            function_declarations.append(
                types.FunctionDeclaration(
                    name=tool.name,
                    description=tool.description or "",
                    parameters=_clean_schema(tool.inputSchema),
                )
            )
        self.gemini_tool = types.Tool(function_declarations=function_declarations)

    async def close(self):
        if self._entered:
            await self.mcp_client.__aexit__(None, None, None)
            self._entered = False

    async def _call_mcp_tool(self, name: str, args: dict) -> str:
        result = await self.mcp_client.call_tool(name, args)
        # fastmcp returns a list of content blocks; join their text.
        parts = []
        for block in result.content:
            text = getattr(block, "text", None)
            if text:
                parts.append(text)
        return "\n".join(parts) if parts else str(result)

    async def chat(self, user_message: str) -> str:
        """Send one user message, run any tool calls Gemini requests, return final text."""
        self.history.append(
            types.Content(role="user", parts=[types.Part(text=user_message)])
        )

        # Loop in case the model chains multiple tool calls in one turn
        # (code review can legitimately need several: diff, file tree,
        # a couple of file reads for context).
        for _ in range(8):
            response = self.genai_client.models.generate_content(
                model=MODEL_NAME,
                contents=self.history,
                config=types.GenerateContentConfig(
                    system_instruction=SYSTEM_INSTRUCTION,
                    tools=[self.gemini_tool],
                ),
            )

            candidate = response.candidates[0]
            self.history.append(candidate.content)

            function_calls = [
                part.function_call
                for part in candidate.content.parts
                if part.function_call
            ]

            if not function_calls:
                # Plain text answer — we're done.
                return response.text or ""

            # Execute each requested tool call and feed results back.
            function_response_parts = []
            for fc in function_calls:
                tool_result_text = await self._call_mcp_tool(fc.name, dict(fc.args))
                function_response_parts.append(
                    types.Part.from_function_response(
                        name=fc.name,
                        response={"result": tool_result_text},
                    )
                )

            self.history.append(
                types.Content(role="user", parts=function_response_parts)
            )

        # Loop exhausted but the last pass still returned a function_call —
        # force one final answer, tools disabled, so it must respond with
        # text using whatever's already in history rather than nothing.
        final_response = self.genai_client.models.generate_content(
            model=MODEL_NAME,
            contents=self.history,
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM_INSTRUCTION,
                # no `tools` here — Gemini can't ask for another tool call
            ),
        )
        return final_response.text or "Sorry, I couldn't complete that — please rephrase."


async def _manual_test():
    """Quick CLI smoke test: python agent.py"""
    agent = GitHubChatAgent()
    await agent.start()
    try:
        print("Connected. Type a message (or 'quit').")
        while True:
            msg = input("> ")
            if msg.strip().lower() in ("quit", "exit"):
                break
            reply = await agent.chat(msg)
            print(reply)
    finally:
        await agent.close()


if __name__ == "__main__":
    asyncio.run(_manual_test())