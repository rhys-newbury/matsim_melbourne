# Melbourne Demand Project

## Purpose

This project realizes a Melbourne travel demand sample from the upstream MATSim Melbourne demand repository.

It is separate from UrbanSketch and focuses only on generating Melbourne population and trip demand artifacts.

## Source Repository

- Upstream: `https://github.com/matsim-melbourne/demand.git`

## Default Workflow

Use the wrapper script:

```bash
./scripts/realize_melbourne_demand.sh
```

The script runs the upstream R pipeline with explicit defaults:

- `MELBOURNE_SAMPLE_PERCENT=0.1`
- `MELBOURNE_NUM_PLANS=5000`
- `MELBOURNE_OUTPUT_DIR=output`

## Autonomy Policy

This project is intended to run locally by default.

1. Prefer local execution for routine bootstrap, restore, test, and demand-generation steps.
2. If a task fails twice in a row, is churning, or requires broad architectural synthesis, escalate to an OpenRouter reasoning model for a short, bounded specification.
3. Keep the OpenRouter context compact:
   - objective
   - files
   - exact failure
   - expected output
4. Use the local project scripts for implementation and rerun the wrapper after any dependency or code change.
5. Do not treat OpenRouter as the normal execution layer for this project.
6. When escalating, use the shared workspace failure packet template.

## Inputs

The upstream project expects Melbourne census and VISTA data under `./data`.
See `data/README.md` for the required downloads.

## Outputs

The generated MATSim population is written under the chosen output directory.
The upstream pipeline writes the final XML population to:

- `output/8.xml/plan.xml`

## Notes

- This repository uses the upstream demand-generation code unchanged.
- The wrapper exists to make the project easier to run and to keep the entrypoint explicit.
