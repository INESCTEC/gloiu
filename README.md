# GLOIU - **G**enerativeAI for **L**oad **O**ptimization **I**nterpretability for **U**ser engagement 

Generate a short, persona-styled daily report from an optimized schedule and return **text** (JSON) and **audio** (MP3) using [OpenAI TTS](https://platform.openai.com/docs/guides/text-to-speech).

Supports **15-minute intervals** and **cost analysis**.

## Project Status

- 🚧 In Progress: Actively being developed; features and structure may change.

## Overview

- [Project details](#project-details)
- [Installation](#installation)
- [Run the RESTful API server](#run-the-restful-api-server)
- [API client / server interactions](#api-client--server-interactions)
- [Requests JSON payload](#requests-json-payload-15-minute-schedule--costs)
- [Endpoints](#endpoints)
- [Quick tests](#quick-tests)
- [Persona & style](#persona--style)
- [Configuration](#configuration)
- [Troubleshooting](#troubleshooting)
- [Open source licensing info](#open-source-licensing-info)
- [Contacts](#contacts)


## Project details

### Repository structure

``` bash
.                             # Current directory
├── app                       # REST API server module source code
├── hems_client.py            # CLI client to interact with the RESTful API server (optional)
├── LICENSE                   # Rights and licensing information
├── requirements.txt          # Python dependencies
```


### Technology Stack

- **Language:** Python 3.11+ (also tested for 3.12)
- **External Tools:** 
    - This project integrates with **OpenAI APIs** (Text-to-Speech `gpt-4o-mini-tts` and related models).
    - Use of these services is governed by the [OpenAI Terms of Use](https://openai.com/policies/terms-of-use).
    - You need a valid **OpenAI API key** to run the TTS features.


### Dependencies

Dependencies are listed in the `requirements.txt` file.


## Installation

Clone the repository:

```sh
git clone https://github.com/INESCTEC/gloiu.git
cd gloiu
```

Create and activate a virtual environment:

```sh
python3 -m venv venv
source venv/bin/activate
```

Install dependencies:

```sh
pip install -r requirements.txt
```


Configure OpenAI TTS API key:

*Option A — environment variable (one-off terminal)*

```bash
export OPENAI_API_KEY=sk-xxxx...
```

*Option B — `.env` file (recommended)*

Create `.env` in the project root:

```
OPENAI_API_KEY=sk-xxxx...
# Optional overrides:
# OPENAI_TTS_MODEL=gpt-4o-mini-tts
# OPENAI_TTS_VOICE=alloy
```

`app/main.py` loads this automatically using `python-dotenv`.

---

## Run the RESTful API server:

To run the main application:

```sh
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

Health check:

```bash
curl -s http://localhost:8000/health
# {"ok": true}
```

## API client / server interactions:

You can test the API locally with the provided client script:

```bash
# Call persona_report and print the text in the style of Sherlock Holmes
python hems_client.py example_schedule.json --persona "Sherlock Holmes"
```

```bash
# Save also as Markdown and JSON
python hems_client.py example_schedule.json --persona "Homer Simpson" \
  --out-md out/report.md \
  --out-json out/report.json
```

```bash
# Get spoken audio (WAV) of the same persona report
python hems_client.py example_schedule.json --persona "Gandalf the Grey" \
  --audio out/report.wav
```

### Requests JSON payload (15-minute schedule + costs)

Send a JSON with the following structure:
- `schedule`: list of slots, each containing an ISO8601 `timestamp` and `data` array with `{name, value}` where `value` is **kW** for that 15-min slot.
- `cost_analysis` (optional): totals for the day.

> Energy per load is computed as `kW × slot_hours` (0.25h by default).  
> The server derives contiguous windows (e.g., `05h00–08h00`) for each load.


#### Minimal example

```JSON
{
  "schedule": [
    {
      "timestamp": "2024-05-01T05:00:00Z",
      "data": [{"name": "Greenhouse Heating", "value": 1.8}]
    },
    {
      "timestamp": "2024-05-01T05:15:00Z",
      "data": [{"name": "Greenhouse Heating", "value": 1.8}]
    }
    // ... slots every 15 minutes for the day
  ],
  "cost_analysis": {
    "total_cost": 5.1730555,
    "total_load_cost": 5.268342,
    "total_solar_revenue": 0.0952865,
    "currency": "EUR"
  }
}
````


### Endpoints

#### Text report

```
POST /persona_report
Query param (optional): ?persona=Harry%20Potter
```

**Response (JSON):**

```json
{
  "persona": "Harry Potter",
  "text": "...texto em PT-PT com janelas ótimas e custos..."
}
```

#### Audio (MP3) of the same text

```
POST /persona_report_audio
Query param (optional): ?persona=Harry%20Potter
```

**Response:** `audio/mpeg` stream (MP3).  
The server strips Markdown (e.g., `**16,0 kWh**` → `16,0 kWh`) before TTS.



## Quick tests

### Using curl

```bash
# Text report (prints JSON)
curl -s -X POST http://localhost:8000/persona_report \
  -H 'content-type: application/json' \
  -d @example_schedule.json

# Audio (MP3)
curl -s -X POST "http://localhost:8000/persona_report_audio?persona=Harry%20Potter" \
  -H 'content-type: application/json' \
  -d @example_schedule.json \
  -o report.mp3
```

### Using the client script

```bash
python hems_client.py example_schedule.json \
  --url http://localhost:8000/persona_report \
  --persona "Harry Potter" \
  --out-md report.md \
  --out-json report.json \
  --audio report.mp3
```


## Persona & style

- If you set `?persona=Elsa%20from%20Arendelle` (or any of the built-ins), the model writes in PT-PT with that persona’s tone.
- The server **guarantees** the opening line starts with the selected persona (post-processing fallback).
- The prompt enforces **no invented numbers** and includes **“Custos do dia”** when provided.



## Configuration

You can tweak voices/models via env:

```
OPENAI_TTS_MODEL=gpt-4o-mini-tts
OPENAI_TTS_VOICE=alloy
```

(Defaults shown; other OpenAI TTS voices include `verse`, `aria`, etc.)

## Troubleshooting

- **401/403/`api_key` error**: set `OPENAI_API_KEY` in your shell or `.env`, then restart the server.
- **429 insufficient_quota**: add billing/credits to your OpenAI account, or ask us to enable a local fallback (e.g., Piper) if you want a no-cloud option.
- **500 TTS failed**: check server logs; usually API key/quota/network.
- **Persona incorrect in first sentence**: the server prepends the correct persona line; if you still see issues, share the JSON you sent.
- **No costs in text**: ensure you send `cost_analysis` exactly as in the example. The server includes a “Custos do dia” section when totals are present.


### Contacts

- Alexandre Lucas (alexandre.lucas@inesctec.pt)

---
