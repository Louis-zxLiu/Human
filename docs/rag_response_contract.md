# RAG Response Contract

## Overview

The planner-first pipeline returns a stable envelope for every RAG+SQL execution.

## Fields

- `answer`: final user-facing text
- `response_kind`: execution outcome, such as `fact`, `analytics`, `recommendation`, `refused:*`
- `plan`: planner decision, selected strategy, and execution summary
- `evidence`: compact source evidence for audit, UI, and replay
- `refusal`: machine-readable refusal reason and suggested follow-up queries
- `warnings`: non-fatal quality warnings
- `observability`: latency, fallback, and trace metadata

## Strategy Semantics

- `structured_fact` should prefer structured scenic facts first.
- `semantic_sql` should answer analytics from SQL-backed evidence first.
- `hybrid_rag` should be used for unstructured scenic knowledge only.
- `route_planner` should expose route items, rationale, and supporting context.
- `refusal` must be machine-readable and should not be hidden inside free-form prose.

## Intended Usage

- `plan` is for audit, debugging, UI hints, and offline evaluation.
- `evidence` is for verification and UI, not for prompt stuffing.
- `refusal` is for safe product behavior and measurable boundary handling.
- `warnings` are for soft degradations, such as weak retrieval or fallback execution.
- `observability` is for timing, traceability, and production diagnostics.
