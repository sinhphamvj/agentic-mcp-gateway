# Development Plan — agentic-mcp-gateway

> Branch: `dev`
> Base commit: `310de6b`
> Target: v0.2.0 → v0.4.0

This document contains executable specs for each feature. An AI agent can pick any task below and implement it independently. Each task includes **exact file paths**, **function signatures to create/modify**, and **acceptance criteria**.

---

## Table of Contents

1. [F1 — HTTP Server (`amcpg serve`)](#f1--http-server)
2. [F2 — Tool Output Synthesis (Two-Turn Agent)](#f2--tool-output-synthesis)
3. [F3 — Fix Docs & Example Paths](#f3--fix-docs--example-paths)
4. [F4 — Honor `human_in_the_loop_intents`](#f4--honor-human_in_the_loop_intents)
5. [F5 — Resume API for `interrupt()`](#f5--resume-api-for-interrupt)
6. [F6 — Persistent Checkpointer](#f6--persistent-checkpointer)
7. [F7 — End-to-End Integration Test](#f7--end-to-end-integration-test)
8. [F8 — Wire Anthropic SDK](#f8--wire-anthropic-sdk)
9. [F9 — Streaming SSE](#f9--streaming-sse)
10. [F10 — Connection Resilience](#f10--connection-resilience)

---

## F1 — HTTP Server

### Problem
`amcpg serve` (`gateway/cli.py:21-27`) is a `click.echo()` stub. The README Quick Start, `docker-compose.yml`, `Dockerfile`, `Makefile`, `examples/*/README.md`, and `scripts/record-demo.sh` all assume it starts a real HTTP server. The project has no `/v1/chat/completions` endpoint anywhere.

### Acceptance criteria
1. `amcpg serve --config workflow.yaml` starts a Uvicorn process on the configured port (default: `8001`)
2. `POST /v1/chat/completions` accepts `{"messages": [{"role": "user", "content": "..."}]}` and returns `{"choices": [{"message": {"role": "assistant", "content": "..."}}]}`
3. `GatewayOrchestrator` is instantiated from the YAML config and each request calls `run()` with the user message
4. `GET /health` returns `{"status": "ok"}`
5. Graceful shutdown (SIGTERM → cleanup MCP connections → exit)

### Implementation steps

#### Step 1 — Create `gateway/server/__init__.py`
```python
# SPDX-License-Identifier: Apache-2.0
"""HTTP server module."""
```

#### Step 2 — Create `gateway/server/app.py`

New module. Imports:
- `starlette.applications.Starlette`
- `starlette.routing.Route`
- `starlette.requests.Request`
- `starlette.responses.JSONResponse`
- `pydantic.BaseModel` for request/response schemas
- `gateway.core.orchestrator.GatewayOrchestrator`
- `gateway.core.config.load_config`

Classes/functions:

```python
class ChatCompletionRequest(BaseModel):
    messages: list[dict]

class ChatCompletionResponse(BaseModel):
    choices: list[dict]

def create_app(config_path: str) -> Starlette:
    """Build the Starlette app from a config file path."""
    config = load_config(config_path)
    orchestrator = GatewayOrchestrator(config)

    async def startup() -> None:
        await orchestrator.setup()

    async def shutdown() -> None:
        await orchestrator.teardown()

    async def health(request: Request) -> JSONResponse:
        return JSONResponse({"status": "ok"})

    async def chat_completions(request: Request) -> JSONResponse:
        body = await request.json()
        messages = body.get("messages", [])
        user_msg = next((m["content"] for m in messages if m["role"] == "user"), "")
        result = await orchestrator.run(user_msg, thread_id=body.get("thread_id", "default"))
        return JSONResponse({
            "choices": [{
                "message": {"role": "assistant", "content": result}
            }]
        })

    app = Starlette(
        routes=[
            Route("/health", endpoint=health, methods=["GET"]),
            Route("/v1/chat/completions", endpoint=chat_completions, methods=["POST"]),
        ],
        on_startup=[startup],
        on_shutdown=[shutdown],
    )
    return app
```

#### Step 3 — Update `gateway/cli.py`

In the `serve` command:
- Accept `--config` / `-c` option (type `click.Path`, default `"workflow.yaml"`)
- Keep existing `--host` and `--port` (these are now *override* values, not the only values)
- Call `create_app(config)` from the new module
- Start Uvicorn: `uvicorn.run(app, host=host, port=port, log_level="info")`

```python
@main.command()
@click.option("--config", "-c", default="workflow.yaml", type=click.Path(exists=True), show_default=True)
@click.option("--host", default="127.0.0.1", show_default=True)
@click.option("--port", default=8001, type=int, show_default=True)
def serve(config: str, host: str, port: int) -> None:
    """Start the gateway HTTP server."""
    from gateway.server.app import create_app
    import uvicorn
    app = create_app(config)
    uvicorn.run(app, host=host, port=port, log_level="info")
```

#### Step 4 — Update `gateway/core/models.py`

Remove the `gateway_port` field or make `cli.py --port` the single source of truth. If `gateway_port` stays in `WorkflowConfig`, the HTTP server should read it by default but allow CLI override.

#### Step 5 — Tests: `tests/test_server.py`

- Test `create_app` returns a `Starlette` instance
- Test `GET /health` returns 200 with `{"status": "ok"}`
- Test `POST /v1/chat/completions` with a mocked `GatewayOrchestrator` (use `unittest.mock.patch` or pass a fake)
- Test that startup calls `orchestrator.setup()` and shutdown calls `orchestrator.teardown()`

#### Step 6 — Update `Dockerfile` and `docker-compose.yml`

- `Dockerfile` already runs `amcpg serve --host 0.0.0.0 --port 8001` — this will now work
- `docker-compose.yml` may need `command:` override to pass `--config` if the container doesn't bundle `workflow.yaml`

### Dependencies
- `starlette` (already in `pyproject.toml:23`)
- `uvicorn` (already in `pyproject.toml:24`)
- `gateway.core.orchestrator` (already exists)
- `gateway.core.config` (already exists)

### Estimated LOC
~250 new code + ~100 tests

---

## F2 — Tool Output Synthesis

### Problem
`_create_agent_node` in `gateway/core/orchestrator.py:80-130` calls the LLM once, executes the tool, stores raw output in `tool_results`, and `_compile_response` (`orchestrator.py:143-157`) concatenates those strings. The LLM never sees the tool result — there's no second LLM `chat()` call.

### Acceptance criteria
1. When the LLM emits a tool call and the tool executes successfully, append a `{"role": "tool", "tool_call_id": ..., "content": ...}` message to the OpenAI message list
2. Make a second `llm_client.chat()` call with the updated messages
3. Store the assistant's final text in `GatewayState.response` (not the raw tool output)
4. If the second call also emits a tool call, repeat (up to a configurable `max_tool_rounds` defaulting to 3)
5. Tests assert: tool output is fed back to LLM, and the final response is natural text, not JSON/sql dump

### Implementation steps

#### Step 1 — Modify `_create_agent_node` in `gateway/core/orchestrator.py`

Current flow:
```
LLM call → if tool_calls → execute tool → store raw result in tool_results → end
```

New flow (pseudocode):
```python
async def _create_agent_node(state: GatewayState, config) -> dict:
    intent = state["intent"]
    intent_cfg = next(i for i in self.config.intents if i.name == intent)

    messages = state.get("messages", [])
    messages.append({"role": "user", "content": state["messages"][-1]["content"]})

    for _round in range(self.config.max_tool_rounds or 3):
        openai_tools = self._tools_for_intent(intent_cfg)
        response = await self.llm_client.chat(
            messages=messages, tools=openai_tools
        )

        if not response.tool_calls:
            # LLM produced a final answer
            return {"response": response.content, "messages": messages + [{"role": "assistant", "content": response.content}]}

        # LLM wants to call a tool
        for tc in response.tool_calls:
            tool_result = await self.mcp_manager.call_tool(
                server_name=intent_cfg.mcp_server,  # or self._resolve_server(...)
                tool_name=tc.function.name,
                arguments=json.loads(tc.function.arguments),
            )
            messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": json.dumps(tool_result) if isinstance(tool_result, dict) else str(tool_result),
            })

    # Max rounds reached; fall back to last available content
    return {"response": str(response.content)}
```

#### Step 2 — Add `max_tool_rounds` to `WorkflowConfig` in `gateway/core/models.py`

```python
class WorkflowConfig(BaseModel):
    ...
    max_tool_rounds: int = 3
```

#### Step 3 — Remove or simplify `_compile_response`

The method `_compile_response` (`orchestrator.py:143-157`) can be deprecated since the LLM now synthesizes the final answer. Either remove it, or keep it as a fallback if no LLM response is returned after tool rounds.

#### Step 4 — Update `GatewayState`

Add `tool_round: int` to track which round we're in (optional, useful for debugging).

#### Step 5 — Update tests: `tests/test_orchestrator.py`

- Add a test case where the fake LLM first emits a tool call, then on second invocation returns text
- Assert that `GatewayState.response` contains natural text, not raw tool output
- Assert that `max_tool_rounds` is respected (stop after N rounds even if LLM keeps asking for tools)
- Assert that `tool` role messages are correctly formatted

### Dependencies
- `LLMClient.chat` (already exists)
- `gateway/mcp_client/manager.py:MCPConnectionManager.call_tool` (already exists)

### Estimated LOC
~80 new/modified in `orchestrator.py` + ~60 in tests

---

## F3 — Fix Docs & Example Paths

### Problem
Multiple documentation files contain incorrect paths, schema examples, and port numbers. A new user following the README or example READMEs will hit errors.

### Issues (complete list)

| File | Line(s) | What's wrong | Fix |
|------|---------|-------------|-----|
| `README.md` | 116-131 | YAML uses `agents:`, `model:`, `api_key:`, `observability.otel_endpoint:` — none exist in `WorkflowConfig` | Replace with real schema: `llm: {provider, model_name, api_key_env}`, `mcp_servers:`, `intents:` |
| `README.md` | 107 | Port is `8081` but default is `8001` | Change to `8001` |
| `README.md` | 90 | `uv pip install agentic-mcp-gateway` — package not on PyPI | Change to `pip install -e .` or `uv sync` |
| `examples/devops-assistant/README.md` | 68 | `python -m gateway.mcp_servers.rest_api_server` — path doesn't exist | Change to `python -m servers.rest_api.server` |
| `examples/research-agent/README.md` | 50 | Same as above | Same |
| `examples/research-agent/README.md` | 60 | `python -m gateway.mcp_servers.filesystem_server` — path doesn't exist | Change to `python -m servers.filesystem.server` |
| `docs/getting-started.md` | 43-57 | Same wrong YAML schema as README | Fix schema to match `WorkflowConfig` |
| `docs/create-mcp-server.md` | 114-127 | Same wrong YAML schema | Fix schema |
| `docker-compose.yml` | all | MCP server containers bind to `127.0.0.1` but Docker networking requires `0.0.0.0` | Override host in `command:` or fix the server defaults |

### Implementation steps

#### Step 1 — Audit all docs
Search for:
- `gateway_port`
- `agents:`
- `mcp_servers` (should exist, not `agents`)
- `api_key` (should be `api_key_env`)
- `model:` (should be `model_name`)
- `observability.otel_endpoint`
- `8081`
- `gateway.mcp_servers.`
- `pip install agentic-mcp-gateway`

#### Step 2 — Fix each file
Use the edit tool for each file listed above. Each fix is a search-and-replace.

#### Step 3 — Add CI test
In `test_llm_providers.py` or a new `tests/test_example_configs.py`:

```python
EXAMPLE_DIR = Path(__file__).parent.parent / "examples"

@pytest.mark.parametrize("yaml_path", list(EXAMPLE_DIR.rglob("workflow.yaml")))
def test_example_workflow_yaml_loads(yaml_path):
    """Every example workflow.yaml must parse against WorkflowConfig."""
    config = load_config(str(yaml_path))
    assert config is not None
    assert len(config.intents) > 0
```

Also add a test that verifies `README.md` example YAML is valid:

```python
def test_readme_yaml_example_is_valid():
    """The YAML block in README.md must parse against WorkflowConfig."""
    readme = Path("README.md").read_text()
    # Extract YAML between ```yaml and ``` in the Configuration Guide section
    match = re.search(r"```yaml\n(.*?)```", readme, re.DOTALL)
    assert match, "No YAML code block found in README"
    yaml_text = match.group(1)
    config = load_config_from_string(yaml_text)  # Apply ${VAR} substitution with dummies
    assert config is not None
```

### Dependencies
- `gateway.core.config.load_config`

### Estimated LOC
~50 lines of test code + patch edits across 8 files

---

## F4 — Honor `human_in_the_loop_intents`

### Problem
`WorkflowConfig.human_in_the_loop_intents` is a declared field (`models.py:59`) and `examples/music-store/workflow.yaml` sets it for the `REFUND` intent. But `grep` for `human_in_the_loop` across `gateway/` returns zero hits — the field is parsed and ignored.

### Acceptance criteria
1. When the intent classifier selects an intent whose name is in `config.human_in_the_loop_intents`, the agent node calls `interrupt()` *before* executing the tool
2. The interrupt payload includes: `intent_name`, `tool_name`, `tool_arguments`, `user_message`
3. The workflow is paused and can be resumed via `Command(resume=...)` with approval
4. The music-store REFUND example workflow actually pauses when triggered

### Implementation steps

#### Step 1 — Modify `_create_agent_node` in `gateway/core/orchestrator.py`

After classifying the intent but before calling the tool, add:

```python
async def _create_agent_node(state: GatewayState, config) -> dict:
    intent = state["intent"]
    intent_cfg = next(i for i in self.config.intents if i.name == intent)

    # Check human-in-the-loop *before* tool execution
    if intent in self.config.human_in_the_loop_intents:
        interrupt_payload = {
            "intent": intent,
            "message": state.get("messages", [{}])[-1].get("content", ""),
        }
        # Call LLM to determine which tool it wants (without executing it)
        openai_tools = self._tools_for_intent(intent_cfg)
        response = await self.llm_client.chat(
            messages=state.get("messages", []),
            tools=openai_tools,
        )
        if response.tool_calls:
            interrupt_payload["proposed_tool"] = {
                "name": response.tool_calls[0].function.name,
                "arguments": json.loads(response.tool_calls[0].function.arguments),
            }
        # Pause and wait for human approval
        approval = interrupt(interrupt_payload)
        if not approval.get("approved", False):
            return {"response": "Operation cancelled by user."}
```

#### Step 2 — Wire `interrupt` into tool execution

When the agent node continues after `interrupt()` (via `Command(resume=...)`), execute the tool with the arguments from `interrupt_payload`.

#### Step 3 — Update `_unknown_handler` to be consistent

Currently `_unknown_handler` uses `interrupt()` on line 133. Ensure the patterns are consistent — both should use the same resume mechanism.

#### Step 4 — Tests: `tests/test_orchestrator.py`

- Create a test where intent is in `human_in_the_loop_intents`
- Mock `interrupt` to return `{"approved": True}` and assert the tool is called
- Mock `interrupt` to return `{"approved": False}` and assert the tool is NOT called
- Assert that non-HITL intents skip the interrupt and proceed normally

### Dependencies
- `langgraph.types.interrupt` (already imported)
- `WorkflowConfig.human_in_the_loop_intents` (already a field)
- External: needs F5 (Resume API) to be fully useful

### Estimated LOC
~50 new code in `orchestrator.py` + ~50 in tests

---

## F5 — Resume API for `interrupt()`

### Problem
`interrupt()` is called in `_unknown_handler` (and, after F4, in agent nodes). But there's no way to resume a paused workflow. The framework provides no `resume` endpoint or method.

### Acceptance criteria
1. `GatewayOrchestrator.resume(thread_id: str, action: dict) -> str` resumes a paused workflow with `Command(resume=action, goto=...)`
2. The resume payload is passed back to the paused node's return value
3. If the HTTP server (F1) is available, `POST /v1/threads/{thread_id}/resume` also works
4. Test: start a workflow that hits `interrupt()`, resume with `{"approved": True}`, assert the tool executes

### Implementation steps

#### Step 1 — Add `resume` method to `GatewayOrchestrator`

In `gateway/core/orchestrator.py`:

```python
async def resume(self, thread_id: str, action: dict) -> str:
    """Resume a paused workflow after an interrupt."""
    from langgraph.types import Command
    result = await self.workflow.ainvoke(
        Command(resume=action),
        config={"configurable": {"thread_id": thread_id}},
    )
    return result.get("response", "")
```

#### Step 2 — Add resume endpoint to HTTP server (if F1 is done)

In `gateway/server/app.py`:

```python
async def resume_thread(request: Request) -> JSONResponse:
    thread_id = request.path_params["thread_id"]
    body = await request.json()
    result = await orchestrator.resume(thread_id, body)
    return JSONResponse({"response": result})
```

Add route: `Route("/v1/threads/{thread_id}/resume", endpoint=resume_thread, methods=["POST"])`

#### Step 3 — Tests: `tests/test_orchestrator.py`

- Test `resume()` calls `workflow.ainvoke` with `Command(resume=action)`
- Integration test: workflow with interrupt → resume → completed

### Dependencies
- `langgraph.types.Command` (already imported in orchestrator)
- F1 (HTTP server) for the REST endpoint
- F4 (HITL) for a real interrupt to resume from

### Estimated LOC
~20 new code in `orchestrator.py` + ~30 in server.py + ~40 in tests

---

## F6 — Persistent Checkpointer

### Problem
`GatewayOrchestrator.checkpointer` is always `InMemorySaver`. Restart loses all conversation state. The `thread_id` parameter on `run()` currently has no effect because there's no persistent store.

### Acceptance criteria
1. Add optional `checkpointer` config to `workflow.yaml`: `checkpointer: {backend: sqlite, path: ./state.db}`
2. When configured, `GatewayOrchestrator.setup()` uses `SqliteSaver(path)` instead of `InMemorySaver`
3. `run(message, thread_id="xyz")` across two separate calls with the same `thread_id` accumulates messages
4. After process restart, the same `thread_id` still has its history (for SQLite)
5. When no `checkpointer` config is given, default to `InMemorySaver` (backward compatible)

### Implementation steps

#### Step 1 — Add `CheckpointerConfig` to `gateway/core/models.py`

```python
class CheckpointerConfig(BaseModel):
    backend: Literal["sqlite", "in_memory"] = "in_memory"
    path: str | None = None  # Only for sqlite

class WorkflowConfig(BaseModel):
    ...
    checkpointer: CheckpointerConfig = CheckpointerConfig()
```

#### Step 2 — Add optional dep to `pyproject.toml`

```toml
[project.optional-dependencies]
sqlite = ["langgraph-checkpoint-sqlite"]
```

#### Step 3 — Modify `GatewayOrchestrator.setup()` in `gateway/core/orchestrator.py`

```python
async def setup(self) -> None:
    ...
    # Replace the hard-coded InMemorySaver
    if self.config.checkpointer.backend == "sqlite":
        from langgraph.checkpoint.sqlite import SqliteSaver
        path = self.config.checkpointer.path or "./gateway_state.db"
        self.checkpointer = SqliteSaver.from_conn_string(f"sqlite:///{path}")
    else:
        from langgraph.checkpoint.memory import InMemorySaver
        self.checkpointer = InMemorySaver()
    ...
```

#### Step 4 — Tests: `tests/test_checkpointer.py` (new file)

- Test that `InMemorySaver` is used by default
- Test that `SqliteSaver` is used when `backend: sqlite` is configured
- Test multi-turn: `run("hi", thread_id="t1")` → `run("what did I say?", thread_id="t1")` → response contains "hi"
- Test that different thread_ids don't interfere

### Dependencies
- `langgraph.checkpoint.sqlite.SqliteSaver` (needs `pip install langgraph-checkpoint-sqlite`)
- `langgraph.checkpoint.memory.InMemorySaver` (already available)
- F2 (tool synthesis) for multi-turn to be meaningful

### Estimated LOC
~40 new code in `models.py` + `orchestrator.py` + ~80 in tests

---

## F7 — End-to-End Integration Test

### Problem
No test exercises the full pathway: "YAML config → intent classification → agent node → real MCP server tool call → response". Unit tests mock the MCP manager or the LLM. Integration tests test the MCP servers alone. The gap between them is where regressions hide.

### Acceptance criteria
1. `tests/integration/test_full_workflow.py` exists
2. Test boots one of the bundled MCP server (e.g., `servers.database.server`) as a subprocess
3. Test loads the corresponding `workflow.yaml` via `load_config`
4. Test instantiates `GatewayOrchestrator` with a fake LLM that returns a known tool call
5. Test asserts: intent is classified, tool is called on the real server, tool output is returned
6. Test is marked `@pytest.mark.integration` so it can be excluded from quick CI runs

### Implementation steps

#### Step 1 — Create `tests/integration/__init__.py`

```python
# SPDX-License-Identifier: Apache-2.0
```

#### Step 2 — Create `tests/integration/test_full_workflow.py`

Pattern from `tests/test_servers/test_database_server.py` (subprocess server) + `tests/test_orchestrator.py` (fake LLM):

```python
import subprocess
import pytest
import requests
from pathlib import Path
from gateway.core.config import load_config
from gateway.core.orchestrator import GatewayOrchestrator

# Bump the subprocess timeout
SERVER_START_TIMEOUT = 10

@pytest.fixture(scope="module")
def db_server():
    """Boot the database MCP server as a subprocess."""
    proc = subprocess.Popen(
        [sys.executable, "-m", "servers.database.server"],
        env={**os.environ},
    )
    # Wait for server to be ready (poll /mcp endpoint)
    url = "http://127.0.0.1:8002/mcp"
    for _ in range(SERVER_START_TIMEOUT * 10):
        try:
            r = requests.get(url, timeout=1)
            if r.status_code < 500:
                break
        except requests.ConnectionError:
            time.sleep(0.1)
    yield url
    proc.terminate()
    proc.wait()

@pytest.fixture
def fake_llm():
    """Fixture that patches LLMClient to return a known tool call."""
    ...

def test_db_query_end_to_end(db_server, fake_llm, tmp_path):
    """Classify → call real DB tool → return formatted response."""
    config_path = write_temp_workflow_yaml(tmp_path, db_server)
    config = load_config(str(config_path))

    orchestrator = GatewayOrchestrator(config)
    await orchestrator.setup()

    result = await orchestrator.run("Show me all tables in the database")
    assert "album" in result or "Album" in result or "track" in result or "Track" in result

    await orchestrator.teardown()
```

#### Step 3 — Update CI workflow (`.github/workflows/ci.yml`)

Add `--run-integration` marker or add a separate job:
```yaml
- name: Integration tests
  run: uv run pytest tests/integration -v
```

### Dependencies
- Existing test harness in `tests/test_servers/test_database_server.py`
- Existing `tests/test_orchestrator.py` fakes

### Estimated LOC
~120 new test code

---

## F8 — Wire Anthropic SDK

### Problem
`LLMProvider.ANTHROPIC` exists in the enum (`models.py:16`). `pyproject.toml` lists `anthropic>=0.30`. The README advertises Anthropic support. But `llm_providers.py:35` only ever instantiates `AsyncOpenAI` — including when `provider="anthropic"`. The base URL `https://api.anthropic.com/v1` is set (`llm_providers.py:22`) but the OpenAI client connecting to the native Anthropic API will produce a format mismatch error on the first request.

### Acceptance criteria
1. `LLMClient(LLMConfig(provider="anthropic", model_name="claude-sonnet-4-20250514"))` instantiates `anthropic.AsyncAnthropic`
2. `chat()` converts the OpenAI-shaped message list to Anthropic's message format (system prompt, user/assistant/tool roles, content blocks)
3. `structured_output()` converts the response back to OpenAI's response shape so the orchestrator doesn't need to know which provider is behind
4. Existing tests pass without modification

### Implementation steps

#### Step 1 — Refactor `LLMClient.__init__` in `gateway/core/llm_providers.py`

```python
class LLMClient:
    def __init__(self, config: LLMConfig) -> None:
        self.config = config
        if config.provider == LLMProvider.ANTHROPIC:
            from anthropic import AsyncAnthropic
            self._client = AsyncAnthropic(api_key=config.api_key_env)
            self._provider = "anthropic"
        elif config.provider == LLMProvider.OLLAMA:
            self._client = AsyncOpenAI(base_url=config.base_url, api_key="ollama")
            self._provider = "openai"
        else:
            self._client = AsyncOpenAI(
                base_url=_PROVIDER_BASE_URLS.get(config.provider, config.base_url),
                api_key=os.getenv(config.api_key_env) or config.api_key_env,
            )
            self._provider = "openai"
```

#### Step 2 — Add Anthropic message adapter

```python
def _to_anthropic_messages(openai_messages: list[dict]) -> tuple[list[dict], str | None]:
    """Convert OpenAI message format to Anthropic."""
    system = None
    messages = []
    for msg in openai_messages:
        if msg["role"] == "system":
            system = msg["content"]
        elif msg["role"] == "user":
            messages.append({"role": "user", "content": msg["content"]})
        elif msg["role"] == "assistant":
            content = []
            if msg.get("content"):
                content.append({"type": "text", "text": msg["content"]})
            if msg.get("tool_calls"):
                for tc in msg["tool_calls"]:
                    content.append({
                        "type": "tool_use",
                        "id": tc["id"],
                        "name": tc["function"]["name"],
                        "input": json.loads(tc["function"]["arguments"]),
                    })
            messages.append({"role": "assistant", "content": content})
        elif msg["role"] == "tool":
            messages.append({
                "role": "user",
                "content": [{
                    "type": "tool_result",
                    "tool_use_id": msg["tool_call_id"],
                    "content": msg["content"],
                }],
            })
    return messages, system

def _to_openai_tool_schema(anthropic_tools: list) -> list:
    """Anthropic uses the same JSON Schema format; mostly pass-through."""
    return anthropic_tools
```

#### Step 3 — Add Anthropic `chat()` branch

```python
async def chat(self, messages: list, tools: list | None = None, **kwargs) -> ChatResponse:
    if self._provider == "anthropic":
        anthropic_messages, system = _to_anthropic_messages(messages)
        response = await self._client.messages.create(
            model=self.config.model_name,
            system=system,
            messages=anthropic_messages,
            tools=_to_openai_tool_schema(tools) if tools else None,
            max_tokens=kwargs.get("max_tokens", 4096),
        )
        return _from_anthropic_response(response)
    else:
        # existing OpenAI code
        ...
```

#### Step 4 — Update tests: `tests/test_llm_providers.py`

- Add `test_anthropic_client_creation` that mocks `anthropic.AsyncAnthropic`
- Add `test_anthropic_message_conversion` with known input/output pairs
- Add `test_anthropic_tool_call` that verifies tool use content blocks

### Dependencies
- `anthropic` (already in `pyproject.toml:18`)
- `LLMClient` (already exists)

### Estimated LOC
~150 new code in `llm_providers.py` + ~100 in tests

---

## F9 — Streaming SSE

### Problem
`LLMClient.chat()` awaits the full response. No streaming. Once F1 is done, the `/v1/chat/completions` endpoint blocks until the LLM finishes, which can be 10-30 seconds for complex responses.

### Acceptance criteria
1. `LLMClient.stream_chat(messages, tools)` is an async generator yielding `("delta", str) | ("done", None)` events
2. The HTTP server `POST /v1/chat/completions` with `stream: true` in the request body returns a `text/event-stream` (SSE) response
3. The SSE format matches OpenAI's: `data: {"choices": [{"delta": {"content": "..."}}]}\n\n`
4. Without `stream: true`, the endpoint still returns a normal JSON response

### Implementation steps

#### Step 1 — Add `stream_chat` to `LLMClient`

In `gateway/core/llm_providers.py`:

```python
async def stream_chat(self, messages: list, tools: list | None = None, **kwargs):
    """Async generator yielding (event, data) tuples."""
    stream = await self._client.chat.completions.create(
        model=self.config.model_name,
        messages=messages,
        tools=tools,
        stream=True,
        stream_options={"include_usage": True},
        **kwargs,
    )
    async for chunk in stream:
        if chunk.choices:
            delta = chunk.choices[0].delta
            if delta.content:
                yield ("delta", delta.content)
            if delta.tool_calls:
                yield ("tool_call", delta.tool_calls)
        if chunk.usage:
            yield ("usage", chunk.usage.model_dump())
    yield ("done", None)
```

#### Step 2 — Add SSE handler to HTTP server

In `gateway/server/app.py`, modify the `chat_completions` endpoint:

```python
async def chat_completions(request: Request) -> Response:
    body = await request.json()
    stream = body.get("stream", False)
    messages = body.get("messages", [])

    if stream:
        return StreamingResponse(
            _stream_response(messages),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
        )
    else:
        # existing JSON response logic
        ...
```

#### Step 3 — Tests: `tests/test_llm_providers.py`

- Test `stream_chat` yields events in order
- Test `stream_chat` with tool calls

#### Step 4 — Tests: `tests/test_server.py`

- Test SSE endpoint returns `text/event-stream`
- Test SSE chunks parse as valid JSON

### Dependencies
- F1 (HTTP server)
- `starlette.responses.StreamingResponse`

### Estimated LOC
~80 new code + ~60 in tests

---

## F10 — Connection Resilience

### Problem
`MCPConnectionManager.call_tool()` (`gateway/mcp_client/manager.py:82-101`) issues one call and propagates any exception. `connect_all()` (`manager.py:53-72`) connects once. A single MCP server failure surfaces as a raw exception to the user. There is no retry, no backoff, no timeout, no health check.

### Acceptance criteria
1. `MCPServerConfig` gains optional fields: `timeout: int = 30`, `retry: {max_retries: 2, backoff_base: 1.0}`
2. `call_tool()` retries on `(ConnectionError, TimeoutError, httpx.RequestError)` with exponential backoff up to `max_retries`
3. `connect_all()` has a `max_retries` parameter (default 1)
4. A failed tool call returns a structured error dict instead of raising an unhandled exception
5. Tests mock a flaky server and verify retry behavior

### Implementation steps

#### Step 1 — Add retry config to `gateway/core/models.py`

```python
class RetryConfig(BaseModel):
    max_retries: int = 2
    backoff_base: float = 1.0

class ConnectionConfig(BaseModel):
    timeout: int = 30
    retry: RetryConfig = RetryConfig()

class MCPServerConfig(BaseModel):
    name: str
    url: str | None = None
    command: str | None = None
    transport: Literal["http", "stdio"] = "http"
    connection: ConnectionConfig = ConnectionConfig()
```

#### Step 2 — Add retry helper in `gateway/mcp_client/manager.py`

```python
import asyncio

async def with_retry(fn, max_retries: int, backoff_base: float, retryable_exceptions: tuple = (ConnectionError, TimeoutError, httpx.RequestError)):
    last_exc = None
    for attempt in range(max_retries + 1):
        try:
            return await fn()
        except retryable_exceptions as e:
            last_exc = e
            if attempt < max_retries:
                await asyncio.sleep(backoff_base * (2 ** attempt))
    raise last_exc  # type: ignore[misc]
```

#### Step 3 — Modify `MCPConnectionManager.call_tool()` to use retry

```python
async def call_tool(self, server_name: str, tool_name: str, arguments: dict) -> Any:
    client = self._connections.get(server_name)
    if not client:
        raise ValueError(f"Server '{server_name}' not connected")

    server_config = next(s for s in self._server_configs if s.name == server_name)
    retry_cfg = server_config.connection.retry

    return await with_retry(
        lambda: client.call_tool(tool_name, arguments),
        max_retries=retry_cfg.max_retries,
        backoff_base=retry_cfg.backoff_base,
    )
```

#### Step 4 — Add health check loop

In `GatewayOrchestrator.setup()`, optionally start a background task that periodically calls `list_tools()` on each connected server to verify liveness. If a server fails health checks, log a warning and mark it as degraded.

#### Step 5 — Tests: `tests/test_mcp_client.py`

- Test retry succeeds on third attempt
- Test retry exhausts max_retries and raises the final exception
- Test empty `max_retries` (0) means no retry

### Dependencies
- `gateway/core/models.py`
- `gateway/mcp_client/manager.py`
- `httpx` (already in deps)

### Estimated LOC
~100 new/modified code + ~80 in tests

---

## Workflow Priority

```
Sprint 1 — "Make it runnable" (1-2 weeks)
├── F3 (Fix docs)        — S, 0.5 day, unblocks all user onboarding
├── F1 (HTTP server)     — L, 5 days, the single most impactful feature
└── F7 (E2E test)        — M, 2 days, catches regression from F1+F2

Sprint 2 — "Make it smart" (1 week)
├── F2 (Tool synthesis)  — M, 3 days, turns router into actual agent
└── F6 (Persistent mem)  — M, 2 days, multi-turn conversations

Sprint 3 — "Make it safe" (1 week)
├── F4 (HITL loop)       — M, 2 days, human approval for destructive ops
└── F5 (Resume API)      — S, 1 day, complete the interrupt lifecycle

Sprint 4 — "Make it mature" (1 week each)
├── F8 (Anthropic)       — M, 3 days, deliver on advertised Claude support
├── F9 (Streaming)       — M, 2 days, real-time UX
└── F10 (Resilience)     — M, 2 days, production readiness
```

---

## Implementation Guidelines for Agents

### Code conventions
- All new files: `# SPDX-License-Identifier: Apache-2.0` header
- All modules: `from __future__ import annotations`
- All functions: proper type annotations
- All public methods: docstring (1 sentence explaining what, not how)
- Follow existing test patterns:
  - Unit tests: in `tests/`, named `test_<module>.py`
  - Integration tests: in `tests/integration/`, marked `@pytest.mark.integration`
  - Server tests: subprocess-based as in `tests/test_servers/`
  - Use `unittest.mock` for LLM/HTTP fakes where appropriate

### Before implementing
1. Read the relevant source file(s) to understand existing patterns
2. Read existing test files to match test style
3. Check `pyproject.toml` for available dependencies
4. Run `uv run ruff check . && uv run mypy gateway && uv run pytest` before submitting

### PR template
```markdown
## Summary
<what this feature does, in 1-2 sentences>

## Changes
- `<file_path>`: <what changed>
- `<file_path>`: <what changed>

## Tests
- `<test_file>`: <what was added>
- CI: <pass/fail>

## Dependencies
<none or list any new pip deps>
```
