# Backend 重写方案：republic → LangChain / LangGraph

> 目标：把 backend 底层的 `republic` 运行时替换为 **LangChain + LangGraph**，**完整保留 pluggy hook 架构**与全部业务逻辑（channels、意图检测、structured output、库存查询、tape 录制）。
>
> 已确认决策：**LangGraph 驱动 agent 循环** · **保留项目自有 tape 系统** · **全功能对等** · **保留 Codex OAuth 登录**。
>
> **状态（2026-06-05）：核心迁移已完成。** backend 内对 `republic` 的依赖只剩 `agent/codex_oauth.py` 一处（Codex OAuth PKCE 流程，在项目 seam 之后）。详见 [§0 实施状态](#0-实施状态截至-2026-06-05)。下文 §1–§9 为原始设计方案，保留作为设计记录；实际实现的偏差已在 §0 标注。

---

## 0. 实施状态（截至 2026-06-05）

### 分阶段完成情况

| 阶段 | 内容 | 状态 |
|---|---|---|
| Phase 1 | 防腐层 `core/`（facade 再导出 republic）+ 全仓 import 改指向 `core/` | ✅ |
| Phase 2 | 模型工厂 + 单轮 LangGraph 图，非流式 `Agent.run()` | ✅ |
| Phase 3 | 流式引擎，`run_stream()` | ✅ |
| Phase 4 | 嵌入式 `<tool_call>` 解析迁出 republic + 删硬编码 key | ✅ |
| Phase B | Codex OAuth 接线（token 驱动 LangChain 模型调用） | ✅ |
| Phase A | `core/*` 类型 + tape 引擎彻底去 republic | ✅ |
| Phase 5 | 端到端对等验证（CLI/Telegram/Feishu 真实跑） | ⏳ 未做（见下「验证边界」） |

### 实际架构（最终落地）

```
backend/architecture/
  core/                  ← 全部项目自有，零 republic
    events.py              StreamEvent / StreamState / AsyncStreamEvents
    errors.py              ErrorKind(StrEnum) / AgentError(Exception) / RepublicError 别名
    tools.py               Tool / ToolContext / ToolAutoResult / @tool / tool_from_model（pydantic schema）
    tape_types.py          TapeEntry / TapeQuery[T](PEP695) / TapeContext / build_messages
    store.py               TapeStore/AsyncTapeStore 协议 + InMemoryQueryMixin + InMemoryTapeStore + AsyncTapeStoreAdapter
    engine.py            ← 新增：ModelEngine + Tape（tape 存储引擎，无 model 调用）
  llm/                   ← 新增整层
    client.py              build_chat_model：provider:model → ChatOpenAI/ChatAnthropic（+ Codex Responses 后端）
    messages.py            tape dicts↔BaseMessage、Tool→StructuredTool、graph 输出→tape 载荷
    graph.py               LangGraph 单轮 StateGraph(agent + ToolNode) + run_step/stream_step + StepResult
    embedded_tools.py      嵌入式 <tool_call> 解析（纯正则，替代已删除的 llm_parsing.py）
  agent/
    agent.py               外层循环不变；_run_once 内层改调 graph；_build_llm 返回 ModelEngine；删 DeepSeekKeyResolver
    codex_oauth.py       ← 新增：Codex 请求 helper（项目自有）+ re-export republic 的 PKCE 登录/resolver（seam）
    auth.py                import 改指向 codex_oauth
  memory/tape.py           TapeService 收 ModelEngine（原 LLM）
  其余（channels/schemas/context/utils/tool）  仅改 import 指向 core/
```

### 与原方案的关键偏差

1. **内层单轮没有「循环回 agent」**：图是 `START → agent → (tool_calls?) → tools → END`（tools 后直接 END），保留「每次 `_run_once` 一轮」语义，多步迭代仍由外层 `_run_tools_with_auto_handoff` 负责。
2. **流式用 `graph.astream(stream_mode=["messages","values"])`**（不是 `astream_events(v2)`）——messages 模式即使节点用 `ainvoke` 也能逐 token 流，values 模式拿终态。
3. **tape 引擎独立成 `core/engine.py`**（原方案放在 memory/tape.py）：`ModelEngine`/`Tape` 只含存储子集（read_messages/append/query/handoff/reset），不含 model 调用。Phase 2–4 期间临时桥接 republic tape，Phase A 才彻底换成项目自有。
4. **嵌入式解析独立成 `llm/embedded_tools.py`**，`llm/llm_parsing.py` 已**删除**（消除 `republic.clients.parsing` 依赖）。流式下原始 `<tool_call>` markup 仍会出现在 text deltas（仅恢复工具执行），属 embed-provider 边缘情况。
5. **Codex OAuth 未完整重写**：521 行 PKCE 流程仍由 republic 提供，藏在 `codex_oauth.py` seam 之后；项目自有的是「请求装配」部分（`resolve_codex_api_base`/`build_codex_headers`/`is_codex_token` + ported account-id 解码）。`build_chat_model` 用这些把 token 接进 Codex 的 **Responses API + ChatGPT backend**（`https://chatgpt.com/backend-api/codex` + `chatgpt-account-id`/`OpenAI-Beta`/`originator` headers）。
6. **`republic` 依赖未移除**：仍需它跑 Codex OAuth；`pyproject.toml` 注释已改为「仅 Codex OAuth 用」。`any-llm-sdk` 暂留。
7. **`ToolAutoResult` 退化为类型用途**：实际单轮结果是 `graph.StepResult`（鸭子兼容）。

### 验证

- 每个阶段都对**基线**跑 `pytest tests/`（忽略预存在的 `test_skills.py` 收集错误）并逐条 diff：**全程 IDENTICAL，零回归**。
- 当前：**17 failed / 134 passed**。那 17 个是仓库 HEAD **既有**失败（测试 monkeypatch 旧模块名 `bub` 不存在所致），与迁移无关。
- 新增测试：`tests/test_run_step.py`（9 个，离线 FakeChatModel：非流式/流式 × 文本/工具/嵌入/错误 + 端到端 run/run_stream）、`tests/test_codex.py`（4 个，离线假 JWT 验证 Codex 装配）。
- 改动文件 ruff 全清（仓库其余既有 ruff 警告未处理）。

### 验证边界（未做 / 需真实环境）

- **Codex OAuth 端到端**：离线只验证了「客户端装配正确」；真实 OAuth 握手 + ChatGPT backend 响应需一次真实 `ApexTran login openai` + 网络。
- **Phase 5 真实 channel 跑通**（CLI/Telegram/Feishu/库存意图/structured output 端到端）尚未做——需配置真实模型 key 和各 channel 凭证。
- 模型调用本身（真实 LLM）未联网验证；所有引擎测试用离线 fake model。

---

## 1. 核心策略

整个迁移的支点：**hook 契约不动，只把契约签名里的 republic 类型换成项目自有的中性类型，再把 republic 的「模型 + tape」引擎用 LangGraph 重新实现。**

- `ApexTranFramework` / `HookRuntime` / 16 个 `ApexTranHookSpecs` 的名称、数量、语义、调用顺序**全部保留**。
- channels / envelope / intent 检测 / structured output / SQL / 向量检索 **业务逻辑不动**，仅随中性类型替换 import。
- republic 仅在「类型层」与「Agent 引擎层」被依赖，替换面收敛。

---

## 2. republic 使用面盘点（17 个文件）

| republic 能力 | 文件 | 作用 |
|---|---|---|
| `LLM` + `tape.run_tools_async` / `stream_events_async` | `agent/agent.py`、`memory/tape.py` | 核心 agent 循环：模型调用 + 工具执行 + 多步 |
| `Tape` / `TapeStore` / `AsyncTapeStore` / `TapeEntry` / `TapeQuery` / `TapeContext` | `memory/store.py`、`memory/tape.py`、`context/context.py`、`tool/toolimpl.py`、`utils/utils.py`、`app/framework.py` | 对话录制、fork/merge、handoff（上下文压缩）、检索 |
| `InMemoryTapeStore` / `AsyncTapeStoreAdapter` / `InMemoryQueryMixin` / `is_async_tape_store` | `memory/store.py`、`agent/agent.py` | tape store 基础设施 |
| `Tool` / `tool` / `ToolContext` / `ToolAutoResult` | `tool/tools.py`、`tool/toolimpl.py`、`agent/agent.py` | 工具注册与执行 |
| `StreamEvent` / `AsyncStreamEvents` / `StreamState` | `agent/agent.py`、`schemas/hookspecs.py`、`schemas/hook_impl.py`、`schemas/hook_runtime.py`、`channels/{base,cli,manager}.py`、`utils/types.py` | 流式事件协议 |
| `RepublicError` / `ErrorKind` | `app/framework.py`、`agent/agent.py` | 错误模型 |
| `clients.parsing.*` | `llm/llm_parsing.py` | 解析把 `<tool_call>` 嵌在文本里的 provider |
| `auth.openai_codex.*` | `agent/auth.py`、`agent/agent.py` | Codex OAuth 登录（**保留**） |

---

## 3. 目标架构

```
backend/architecture/
  core/                 ← 新增：中性类型层（防腐层，取代 republic 公共类型）
    events.py             StreamEvent / AsyncStreamEvents / StreamState
    tape_types.py         TapeEntry / TapeQuery / TapeContext
    store.py              TapeStore / AsyncTapeStore 协议 + InMemory* + Adapter + Mixin
    tools.py              Tool / ToolContext / ToolResult + @tool 装饰器
    errors.py             AgentError / ErrorKind
  llm/
    client.py           ← 新增：LangChain ChatModel 工厂（provider:model → ChatOpenAI/ChatAnthropic）
    graph.py            ← 新增：LangGraph 单轮 StateGraph（call_model + ToolNode）
    messages.py         ← 新增：tape entries ⇄ LangChain BaseMessage 互转
    llm_parsing.py        嵌入式 <tool_call> 解析（保留逻辑，改挂在 call_model 节点后）
  agent/
    agent.py              重写：外层 policy 循环不变，内层单步改调 graph.py
    codex_oauth.py      ← 新增：移植 Codex OAuth（PKCE 登录 + token 存储 + resolver）
    auth.py               改 import → codex_oauth
    settings.py           不变
  memory/
    store.py              仅替换 republic 基类 import → core/
    tape.py               LLM → 项目自有 ModelEngine（提供 .tape(name)）
  context/context.py      仅替换 import；_select_messages 复用
  schemas/                仅替换 import；hook 名称/语义不变
  channels/ utils/ tool/  仅替换 import
```

**分层不变量**：当前是「外层 `_run_tools_with_auto_handoff` policy 循环 + 内层单轮 `tape.run_tools_async`」。
- **外层保留**：`max_steps`、`continue/text/error` 判定、`loop.step` tape 事件、**auto-handoff（上下文超长→`tapes.handoff` 压缩重试）** 全部不动。
- **内层换 LangGraph**：单轮 `StateGraph`：`call_model ──(tool_calls)──> ToolNode ──> call_model`，节点边界写 tape entries，`astream_events(v2)` 翻译成中性 `StreamEvent`。

---

## 4. republic → LangChain 映射

| republic | LangChain / LangGraph 替代 |
|---|---|
| `LLM(model, tape_store, context, ...)` | `llm/client.py` 工厂 + `llm/graph.py` 引擎；tape 由节点回调显式录制 |
| `tape.run_tools_async(...)` | 运行单轮 graph（非流式），返回 `ToolResult`（text/continue/error） |
| `tape.stream_events_async(...)` | `graph.astream_events(version="v2")` → 中性 `StreamEvent` |
| `tape.handoff_async` / anchors | 项目自有 tape（不变，仅换基类型） |
| `republic.Tool` / `@tool` | `core/tools.py` 自有 `Tool` + pydantic JSON schema；bind 到 model 用 `bind_tools` |
| `ToolAutoResult` | `core/tools.py` `ToolResult(kind, text, tool_calls, tool_results, error, usage)` |
| `StreamEvent/AsyncStreamEvents/StreamState` | `core/events.py` 自有 dataclass（接口同形） |
| `RepublicError/ErrorKind` | `core/errors.py` `AgentError/ErrorKind` |
| `_select_messages` 产出 OpenAI dict | 经 `langchain_core.messages.convert_to_messages()` → BaseMessage |
| `fallback_models` | `chat_model.with_fallbacks([...])` |
| 嵌入式 `<tool_call>` 解析 | `call_model` 节点后处理：无原生 tool_calls 时正则合成 |
| Codex OAuth | `agent/codex_oauth.py`（移植 PKCE 流程 + token store + resolver） |

模型 provider：DeepSeek / OpenRouter / SiliconFlow 均 OpenAI 兼容 → `ChatOpenAI(base_url, api_key)`；Anthropic → `ChatAnthropic`。配置格式 `"openrouter:qwen/..."` 可直接喂 `init_chat_model`。

---

## 5. 逐文件改动清单

### A. 新增文件

| 文件 | 内容 | 取代 republic 符号 |
|---|---|---|
| `core/events.py` | `StreamEvent(kind, data)`、`StreamState(error, usage)`、`AsyncStreamEvents`（包装 async gen + `.error/.usage/._state`，构造签名 `(iterator, state=...)`） | `StreamEvent/AsyncStreamEvents/StreamState` |
| `core/tape_types.py` | `TapeEntry(id, kind, payload, meta, date)` + `.event()` 工厂；`TapeQuery`（`tape/_kinds/_after_last/_after_anchor/_query/_limit` + `.all()/.kinds()/.query()/.limit()/.between_dates()`）；`TapeContext(select, state)` | `TapeEntry/TapeQuery/TapeContext` |
| `core/store.py` | `TapeStore`/`AsyncTapeStore` Protocol、`InMemoryTapeStore`、`AsyncTapeStoreAdapter`、`InMemoryQueryMixin`、`is_async_tape_store` | `republic.tape.*` |
| `core/tools.py` | `Tool(name, description, handler, context, schema)`、`@tool` 装饰器（pydantic → JSON schema）、`ToolContext(tape, run_id, state)`、`ToolResult` | `Tool/tool/ToolContext/ToolAutoResult` |
| `core/errors.py` | `AgentError(kind, message)`、`ErrorKind` 枚举 | `RepublicError/ErrorKind` |
| `llm/client.py` | `build_chat_model(settings)`：`provider:model` → ChatModel + fallbacks + timeout + client_args + Codex resolver 注入 | `LLM` 构造部分 |
| `llm/graph.py` | 单轮 `StateGraph(call_model, ToolNode)`；`run_step()`/`stream_step()` | `tape.run_tools_async/stream_events_async` |
| `llm/messages.py` | tape entries → BaseMessage（复用 `_select_messages` + `convert_to_messages`）；AIMessage.tool_calls → tape tool_call/tool_result | — |
| `agent/codex_oauth.py` | 移植 PKCE 登录、`OpenAICodexOAuthTokens`、`CodexOAuthLoginError`、token 存 `~/.codex/auth.json`、resolver callable | `republic.auth.openai_codex.*` |

### B. 机械替换（仅改 import，函数体基本不动）

| 文件 | 改动 |
|---|---|
| `utils/types.py` | `from republic import StreamEvent` → `core.events` |
| `utils/utils.py` | `TapeEntry` → `core.tape_types` |
| `channels/base.py` | `StreamEvent` → `core.events` |
| `channels/cli.py` | `StreamEvent` → `core.events` |
| `channels/manager.py` | `StreamEvent` → `core.events` |
| `context/context.py` | `TapeContext, TapeEntry` → `core.*`；`_select_messages` 逻辑保留 |
| `schemas/hookspecs.py` | `AsyncStreamEvents/AsyncTapeStore/TapeContext/TapeStore` → `core.*`（**hook 契约本身不变**） |
| `schemas/hook_runtime.py` | `AsyncStreamEvents/StreamEvent/StreamState` → `core.events` |
| `schemas/hook_impl.py` | `AsyncStreamEvents/TapeContext/TapeStore` → `core.*`（业务逻辑不动） |
| `app/framework.py` | `AsyncTapeStore/TapeContext` → `core.*`；`RepublicError/ErrorKind` → `core.errors`（`_run_model` 错误分支改用 `AgentError`） |
| `memory/store.py` | `AsyncTapeStore/TapeEntry/TapeQuery/AsyncTapeStoreAdapter/InMemoryQueryMixin/InMemoryTapeStore/TapeStore/is_async_tape_store` → `core.*`；`FileTapeStore/ForkTapeStore/TapeFile` 逻辑**完全不变** |

### C. 引擎重写

| 文件 | 改动 |
|---|---|
| `agent/agent.py` | 外层循环结构保留；`_run_once` 内层从 `tape.run_tools_async/stream_events_async` 改调 `llm/graph.py`；`_build_llm` 改用 `llm/client.py`；**删除 `DeepSeekKeyResolver` 硬编码 key**（见 §7）；`openai_codex_oauth_resolver` 改 import `agent/codex_oauth`；`_resolve_tool_auto_result`/`_resolve_final_data` 适配 `core` `ToolResult` |
| `memory/tape.py` | `LLM` → 项目自有 `ModelEngine`（封装 store + context + client，提供 `.tape(name)` 返回带 `query_async/handoff_async/append_async/reset_async` 的 Tape）；`TapeService` 其余不变 |
| `tool/tools.py` | `republic_tool` → `core.tools.tool`；`Tool` → `core.tools.Tool`；`_add_logging`/`model_tools`/`render_tools_prompt`/`REGISTRY` 不变 |
| `tool/toolimpl.py` | `AsyncTapeStore/TapeQuery/ToolContext` → `core.*`；所有 `@tool` 工具体不变（含 `tape.search` 的 `TapeQuery` 链式调用） |
| `llm/llm_parsing.py` | `parse_embedded_tool_calls`/`strip_embedded_tool_calls` 正则保留；`CompletionTransportParser` 子类 + `parsing_module` 钩子改为 `call_model` 节点后处理函数（无原生 tool_calls 且文本含 `<tool_call>` → 合成 tool_calls） |

### D. Codex OAuth（保留）

| 文件 | 改动 |
|---|---|
| `agent/auth.py` | `from republic.auth.openai_codex import ...` → `from backend.architecture.agent.codex_oauth import ...`；typer 命令体不变 |
| `agent/codex_oauth.py`（新） | 实现 PKCE 授权码流程、本地回调 server / 手动粘贴、token 读写 `~/.codex/auth.json`、`resolver(provider)->key`。LangChain 侧：`ChatOpenAI` 构造前取/刷新 token 注入 `api_key`，或包一层在调用前刷新 |

### E. 测试套件（`tests/`，19 个文件，11 个直接引用 republic）

`tests/` 是本次迁移的**回归基线**，必须随防腐层同步更新（把 republic 类型构造换成 `core/`）。直接 import republic 的：
`test_fork_store_merge_back.py`、`test_subagent_tool.py`、`test_file_tape_store_entry_ids.py`、`test_channels.py`、`test_framework.py`、`test_hook_runtime.py`、`test_builtin_tools.py`、`test_builtin_agent.py`、`test_builtin_hook_impl.py`、`test_tape_search_output.py`、`demo.py`。

- **Phase 1 完成判据**：这 11 个测试的 `from republic import ...` 改成 `core/` 后**全绿**，即证明类型层脱钩无回归。
- 引擎相关测试（`test_builtin_agent.py`、`test_subagent_tool.py`、`test_fork_store_merge_back.py`、`test_tape_search_output.py`）是 Phase 2–4 的核心验证靶子，可能需把"调 republic LLM"的桩换成 LangGraph 桩。

---

## 6. 依赖调整（pyproject.toml）

> **实际：** 已新增 `langchain-core` / `langchain-openai` / `langchain-anthropic` / `langgraph`。`republic` **未移除**——仍用于 Codex OAuth（注释已改为「仅 Codex OAuth 用」）。`any-llm-sdk[anthropic]` 暂留。`uv.lock` 已同步。

- **新增（已做）**：`langchain-core`、`langchain-openai`、`langchain-anthropic`、`langgraph`（`langchain-community` 已在）
- **保留**：`republic`（仅 Codex OAuth）；`any-llm-sdk[anthropic]`（待评估移除）

---

## 7. ⚠️ 安全修复（重写时必须做）

`agent/agent.py` 的 `DeepSeekKeyResolver` **硬编码了一条 DeepSeek API key**（`sk-qtrdoed...`）。

> **实际：** ✅ 已删除 `DeepSeekKeyResolver` 类及硬编码 key，`_build_llm` 改走 `settings.api_key`。⚠️ 该 key 已进入 git 历史，**仍需轮换**。

---

## 8. 分阶段实施

> 实际完成情况见 [§0](#0-实施状态截至-2026-06-05) 的状态表。下列为原始计划顺序。

1. **Phase 1 — 防腐层** ✅：建 `core/`，全仓 17 处 `from republic import` 改指向 `core/`（先 facade 桥接）。
2. **Phase 2 — 模型工厂 + 单轮图** ✅：`llm/client.py` + `llm/messages.py` + `llm/graph.py`，非流式 `Agent.run()`。
3. **Phase 3 — 流式 + 外层循环** ✅：`run_stream()`（实际用 `astream(stream_mode=[...])`）。
4. **Phase 4 — 收尾** ✅（部分）：嵌入式 tool-call 解析迁出、删硬编码 key、Codex 接线（= 原方案的 D）。**republic 依赖未删**（Codex 仍用）。
5. **Phase A（追加）** ✅：`core/*` 类型 + tape 引擎（`core/engine.py` 的 `ModelEngine`/`Tape`）彻底去 republic。
6. **Phase 5 — 对等验证** ⏳：`tests/` 全套已作回归基线（每阶段 diff IDENTICAL）；CLI + Telegram/Feishu + 库存意图 + structured output 的**真实端到端**验证未做（需真实凭证）。

> 范围说明：本方案只动 `backend/`。仓库内 `frontend/` 不在改动范围。

---

## 9. 风险点

| 风险 | 说明 | 缓解 |
|---|---|---|
| tape ⇄ BaseMessage 互转 | 多模态（image_url）、tool_call_id 对齐、anchor 注入需精确 | 复用 `_select_messages`，逐 kind 单测 |
| auto-handoff 上下文压缩 | LangGraph 无原生等价，靠 tape anchor 截断 | 保留现有 `ForkTapeStore.fetch_all` anchor 逻辑，单测覆盖 |
| 嵌入式 tool-call provider | SiliconFlow Qwen 等非原生 function calling | 节点后处理合成 tool_calls，保留原正则 |
| Codex OAuth token 刷新注入 ChatOpenAI | LangChain `api_key` 为静态 SecretStr | 调用前刷新 + 重建 client 或自定义 httpx client |
| fork/merge 并发语义 | `contextvars` 跨 LangGraph 异步节点传递 | 保持在 `Agent.run` 层 fork，graph 内只读写当前 store |
