# Melbourne Demand Agent Instructions

## Role

This repository is a standalone Melbourne travel-demand project, separate from UrbanSketch.

The project goal is to realize Melbourne demand artifacts from the upstream MATSim Melbourne demand codebase and keep the workflow local-first.

## Routing Policy

1. Default to local execution for setup, dependency restoration, tests, and demand generation.
2. Escalate to OpenRouter only when one of these is true:
   - the same local task failed twice
   - the work is churning without state change
   - the context is too large for local reasoning
   - the task needs architectural synthesis or risk review
3. When escalating, keep the packet short and bounded:
   - objective
   - files to inspect
   - files allowed to edit
   - exact failure
   - tests to run
   - forbidden changes
4. Use the shared workspace failure packet template at `/Users/fouriep/.openclaw/workspace/OPENCLAW_FAILURE_PACKET_TEMPLATE.md` when escalating.
5. If you create a new related project, initialize it from `/Users/fouriep/.openclaw/workspace/scripts/init_project_scaffold.py` so the shared defaults are inherited.

## Implementation Rules

1. Keep changes narrow and project-specific.
2. Prefer the existing upstream R pipeline rather than rewriting the demand logic.
3. Use project scripts instead of one-off shell fragments.
4. Treat generated outputs as disposable artifacts.
5. Do not conflate this repository with UrbanSketch or its facility-first product direction.
6. Keep retry loops short; after two local failures or obvious churn, escalate rather than repeat the same step.

## Suggested Local Flow

1. Run `./scripts/bootstrap_melbourne_demand.sh`.
2. Run `./scripts/realize_melbourne_demand.sh`.
3. Inspect `output/8.xml/plan.xml` or the failure log.
4. If the same task fails twice, escalate to OpenRouter reasoning for a bounded spec.
