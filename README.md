# EcoMetric

AI-powered community and environmental data intelligence assistant using Gemma 4.

Team NeuroNex, IIMT Engineering College, Meerut. Hacktoberfest Hackday 2026, Problem Statement 03, Track 1: Best Use of Gemma 4.

## Overview

EcoMetric lets anyone ask questions about electricity, water, waste, air quality, mobility and campus-resource data in plain English or Hindi, and get answers they can verify.

Gemma 4 reads the question and selects one analysis tool through native function calling. It never calculates. Every number is computed by tested Python code (DuckDB), checked a second time with pandas, and shown together with the query that ran, the rows used and a list of rule-based caveats. When the data cannot answer a question, EcoMetric says so instead of guessing.

## Features

| Area | What it does |
|---|---|
| Five-step flow | Load dataset, Ask in plain language, Calculate with code, Chart and answer, Explain caveats. Steps unlock one at a time. |
| Six issue areas | Sample datasets for electricity, water usage, waste collection, air quality, mobility and campus resources. |
| Upload | CSV or Excel up to 5 MB. Roles (month, group, metric, denominator) are inferred automatically. |
| Health check | Blank readings, missing months, duplicates, negative values and outliers are found before any question is asked. |
| Analysis tools | rank_entities, trend_over_time, compare_entities, aggregate_total, normalize_by and cannot_answer. |
| Verification | Dual computation (DuckDB and pandas must agree), evidence rows, rows used and skipped, data-source label. |
| Caveat engine | Missing readings, outliers, non-additive measures, seasonal effects, period interpretation and refusals. |
| Confidence label | Verified, Partial data, or Could not answer. |
| Languages | English and Hindi questions, answers, caveats and interface. |
| Offline mode | Gemma 4 E2B through Ollama, so data never leaves the machine. |
| Audit log | Every answer is appended to `data/audit_log.jsonl` and viewable in step 5. |

## Architecture

```
Question (English or Hindi)
   |
   v
Planner: Gemma 4 via Gemini API | Gemma 4 E2B via Ollama | rule-based fallback
   |  one function call, arguments validated against the dataset profile
   v
Tool layer: parameterised DuckDB query  +  independent pandas cross-check
   |
   v
Caveat engine (rule-based)  ->  answer template  ->  optional Gemma wording with number guard
   |
   v
Answer, chart, evidence, caveats, confidence, audit log
```

| Layer | Location |
|---|---|
| API and static frontend | `backend/app/main.py` |
| Ask pipeline | `backend/app/pipeline.py` |
| Data loading, profiling, health check | `backend/app/data/` |
| Analysis tools and function schemas | `backend/app/tools/registry.py` |
| Gemma 4 providers and rule-based planner | `backend/app/llm/` |
| Caveats, answer text, narration guard, audit | `backend/app/verify/` |
| Charts (Plotly specs) | `backend/app/charts.py` |
| Web interface | `frontend/` |
| Sample data and data dictionaries | `data/samples/` |

## Requirements

- Python 3.10 or newer
- Optional: a Google AI Studio API key for Gemma 4 online
- Optional: Ollama with `gemma4:e2b` for offline mode

## Setup

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env        # Windows: copy .env.example .env
```

Edit `.env`:

- **Gemma 4 online:** set `GEMINI_API_KEY` (create one at https://aistudio.google.com/apikey).
- **Gemma 4 offline:** install Ollama, run `ollama pull gemma4:e2b`, and keep Ollama running.
- With neither, EcoMetric runs with the rule-based parser, and the interface shows this.

## Run

```bash
./run.sh          # macOS or Linux
run.bat           # Windows
```

Open http://127.0.0.1:8000. API documentation is at http://127.0.0.1:8000/api/docs.

## Test

```bash
python -m pytest
```

The suite covers profiling, health checks, every tool, SQL-injection attempts, the rule-based planner on all sample questions, Gemini and Ollama tool-call parsing with mocked transports, fallback behaviour, the money guard, the narration number guard and the HTTP API. No test calls a real model.

## Demo script

Load **Electricity**, then ask:

1. Which building used the most electricity in September 2026? (Verified)
2. How has Hostel B electricity changed since January? (Partial data: July outlier flagged)
3. Which building is most efficient per occupant? (Partial data: missing Library month flagged)
4. What was the electricity cost last month? (Could not answer: no cost column)

The same questions are available in Hindi as example buttons.

## Security and privacy

- The model receives only the dataset profile (column names, roles, units, group names, month range), never data rows.
- Model output is never executed. SQL identifiers come only from the validated profile; all values are bound parameters.
- Uploads are limited by type, size, row count and column count, and are held in memory only.
- The API key stays on the server and is never sent to the browser.
- The interface inserts all data as text and runs under a strict Content Security Policy.
- The server binds to 127.0.0.1 by default.

## Configuration

| Variable | Default | Purpose |
|---|---|---|
| `ECOMETRIC_PROVIDER` | `auto` | `auto`, `gemini`, `ollama` or `rules` |
| `GEMINI_API_KEY` | empty | Enables Gemma 4 through the Gemini API |
| `GEMINI_MODEL` | `gemma-4-26b-a4b-it` | Hosted Gemma 4 model |
| `OLLAMA_URL` | `http://localhost:11434` | Ollama server |
| `OLLAMA_MODEL` | `gemma4:e2b` | Offline Gemma 4 model |
| `ECOMETRIC_NARRATE` | `1` | Allow Gemma to reword answers (numbers are checked) |
| `LLM_TIMEOUT` | `60` | Seconds per model request |
| `MAX_UPLOAD_MB` | `5` | Upload size limit |
| `MAX_ROWS` / `MAX_COLUMNS` | `100000` / `60` | Upload shape limits |

## Data

All sample datasets are synthetic and labelled as such in every answer. They include deliberate problems so the health check and caveat engine can be demonstrated. Regenerate them with `python scripts/generate_samples.py`.

Planned: live data from OpenAQ and data.gov.in.

## Licensing

Gemma 4 is released by Google under the Apache 2.0 license. Add a license file for this repository before publishing it.
