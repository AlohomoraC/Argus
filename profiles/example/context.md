# Project context (example)

> Replace this file with your own context. The model reads it to decide what matters and to write the
> "For <your project>" notes. Be concrete: name your components, constraints and current initiatives.
> Keep confidential details out of anything you commit — `profiles/` is git-ignored except this example.

## What we build

**Acme Agents** is an enterprise agent platform that customers deploy in their own cloud. Customers often
cannot use frontier closed models, so agents must be reliable on mid-sized open-weight models.

## Components (use these names when pointing at affected parts)

| Component | Responsibility |
|---|---|
| gateway | chat entry point, streaming, sessions |
| planner | intent detection and task planning |
| executor | multi-step execution and tool calls |
| memory | long-term memory (vector store + file-based notes) |
| knowledge | RAG: parsing, retrieval, reranking |
| tools | MCP gateway and connector catalogue |
| model-gateway | unified LLM / embedding / rerank gateway with caching and metering |
| sandbox | code execution sandbox |
| skills | skill packaging, review and publishing |
| eval | datasets, evaluators, experiments |

## Current initiatives (always call these out)

- Evaluating a small decision model for intent routing (accuracy and confidence calibration matter).
- Rolling out file-based memory next to the vector store.
- Launching a skill marketplace with an approval workflow.

## What we care about most

- Agent reliability on non-frontier models (planning, tool use, long tasks)
- Memory, retrieval and context engineering (compression, caching)
- MCP / skills / tool ecosystem and standards
- Enterprise concerns: permissions, approvals, multi-tenancy, prompt-injection safety, observability
- Cheap, reproducible agent evaluation
- Deployment cost: inference efficiency, small models, diverse hardware
- Personal / proactive agents and how they change enterprise assistants
- Competitors and ecosystem: other agent platforms and frameworks
