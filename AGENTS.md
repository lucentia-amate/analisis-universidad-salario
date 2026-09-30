# AGENTS.md

## Project rules

- Use Python 3.13.
- Use Streamlit for the frontend visualizations.
- Use pytest for tests.
- Do not modify database schemas without explicit approval.

## Architecture

- `src/data/` contains source data files.
- `src/etl/` contains data transformation logic.
- `src/processeddata/` contains transformed data used in the visualizations.
- `src/notebooks/` contains jupyter notebooks.
- `src/visualizations/` contains the frontend to visualize data outside notebooks.
- `src/tests/` contains test files.

