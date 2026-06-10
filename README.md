# Courtvision

Courtvision is a natural-language NBA play and video search engine. It lets a user type basketball queries such as:

```text
victor wembanyama dunk playoffs against thunder
cade assists duren dunk
james harden clutch misses
```

The backend resolves the query into NBA Stats API parameters, fetches video play rows, applies local filters, and returns JSON-safe results to a lightweight browser frontend.

## Project Layout

```text
backend/
  api.py                 FastAPI app and HTTP endpoints
  search_engine.py       Main search orchestration layer
  parsing.py             Natural-language query parsing
  entities.py            Player/team lookup and fuzzy matching
  nba_client.py          NBA Stats API request helpers
  formatters.py          DataFrame normalization and local filters
  query.py               Small command-line/notebook entry point
  names/
    aliases.py           Player/team nicknames and shorthand
    keywords.py          Basketball vocabulary and filter words

frontend/
  index.html             Static application shell
  app.js                 Frontend state, API calls, rendering

start.ps1                Starts API and frontend together on Windows
start.md                 Manual run commands
requirements.txt         Python dependencies
```

## How The Application Works

### 1. Frontend

The frontend is a static HTML/JavaScript app served from `frontend/`.

It provides:

- A natural-language search input.
- A season dropdown.
- A `PBPV3` checkbox for exact play-by-play clock enrichment.
- Example query buttons.
- API URL configuration.
- A vocabulary modal showing the parser's aliases and keywords.
- Result list and selected-play detail view.
- Infinite scrolling backed by cached search results.

When a search is submitted, `frontend/app.js` sends:

```json
{
  "query": "cade assists duren dunk",
  "season": "2025-26",
  "limit": 25,
  "offset": 0,
  "use_play_by_play": false
}
```

to `POST /query`.

The first search request runs the full backend search and returns the first page of rows plus a `search_id`. As the user scrolls, the frontend calls `GET /query/{search_id}` with the next `offset` and `limit`, so additional pages are sliced from the cached backend result instead of rerunning NBA API calls.

### 2. FastAPI Layer

`backend/api.py` exposes the HTTP API:

- `GET /health`: basic health check.
- `GET /seasons`: supported seasons for the UI dropdown.
- `GET /vocabulary`: live parser vocabulary and aliases.
- `POST /query`: runs a search and returns paged results.
- `GET /query/{search_id}`: returns additional pages from a cached search.

The API validates season and pagination input, reuses cached `SearchEngine` instances, converts pandas/numpy values into JSON-safe values, and returns warnings instead of crashing when NBA endpoints fail.

### 3. Search Engine

`backend/search_engine.py` is the main orchestration layer.

For each query it:

1. Parses the natural-language text.
2. Builds NBA Stats request parameters.
3. Fetches VideoDetailsAsset rows for the relevant season type.
4. Normalizes rows into a DataFrame.
5. Optionally fetches PlayByPlayV3 clock data.
6. Applies local keyword filters.
7. Returns a `SearchResult` containing results, raw rows, warnings, query interpretation, query params, and user-agent metadata.

If a query does not specify `regular season` or `playoffs`, Courtvision searches both regular season and playoffs.

### 4. Query Parsing

`backend/parsing.py` turns user text into structured fields:

- Primary player.
- Optional assist recipient player.
- Optional opponent team.
- Season type.
- Month bucket.
- Period/quarter.
- Basketball action keywords.
- Shot descriptors.
- Miss filters.
- Clutch/time filters.
- Score-context filters such as go-ahead or game-tying.

Player and team matching is handled with spaCy `PhraseMatcher` first, then RapidFuzz fallback matching. Aliases such as `wemby`, `cade`, `duren`, `sga`, `okc`, and `mavs` live in `backend/names/aliases.py`.

Two-player assist queries are supported. Examples:

```text
victor wembanyama assist to castle in playoffs
wemby to castle playoffs
cade assists duren dunk
luka pass kyrie
```

These parse as primary-player assists and locally filter descriptions to rows where the recipient appears.

### 5. NBA API Client

`backend/nba_client.py` centralizes calls to the unofficial NBA Stats endpoints through `nba_api`.

It handles:

- Browser-like request headers.
- Optional user-agent rotation.
- VideoDetailsAsset requests.
- PlayByPlayV3 requests.
- Retries and warnings for transient failures.

Important note: NBA Stats endpoints are unofficial and can be slow or inconsistent. A timeout or non-JSON response from `stats.nba.com` usually means the upstream NBA API failed, not that Courtvision failed to parse the query.

### 6. Data Formatting And Filtering

`backend/formatters.py` normalizes raw NBA rows into consistent columns such as:

- `Game_ID`
- `Event_Index`
- `Game_Date`
- `Description`
- `Point_Change`
- `Score_Diff`
- `Video_Link`
- `Event_Link`
- `Recipient_Player`

It also applies local filters that are easier to handle after fetching raw rows:

- Shot descriptor filters, such as dunks, threes, fadeaways.
- Miss filters.
- Game-tying and go-ahead filters.
- Clutch/time filters.
- Assist-recipient filters.

For PBPV3-enabled searches, play-by-play clock data can add `Clock` and `Seconds_Remaining` so exact time windows such as final two minutes can be applied more accurately.

### 7. Vocabulary Files

`backend/names/keywords.py` contains the basketball words Courtvision understands:

- Context measures: points, assists, rebounds, steals, blocks, turnovers.
- Shot words: dunk, layup, three, fadeaway, hook, alley oop, etc.
- Phrase keywords: step-back three, driving dunk, reverse layup, etc.
- Time keywords: clutch, last two minutes, final minute, buzzer.
- Score context: game-tying, go-ahead.
- Season, month, and period keywords.

`backend/names/aliases.py` contains explicit shorthand for player and team names that the official NBA static data does not cover well enough.

## API Response Shape

`POST /query` returns:

```json
{
  "search_id": "e885dc419fff40cf8a0d79316602a1c6",
  "query": "cade assists duren dunk",
  "interpretation": "Cade Cunningham assists to Jalen Duren on dunk during the 2025-26 season",
  "latency_ms": 1200,
  "raw_result_count": 739,
  "filtered_result_count": 78,
  "limit": 25,
  "offset": 0,
  "has_more": true,
  "warnings": [],
  "user_agent": "...",
  "query_params": {},
  "results": []
}
```

Warnings are expected when NBA endpoints timeout, return no rows, or when PBPV3 is disabled for a query that asks for clutch/time filtering.

## Known Constraints

- NBA Stats endpoints are unofficial and can timeout.
- Video availability is expected from `2018-19` onward; older seasons may have play data but not usable clips.
- PBPV3 enrichment can be slow because it may fetch play-by-play data for many games.
- Search result pages are cached in memory for a limited time. Restarting the API clears cached `search_id` values.

## Development Setup

Create and activate a virtual environment, then install dependencies:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

The project is tested on Python 3.13. `requirements.txt` installs the spaCy English model from the official model wheel URL.

## How To Run

You can run the API and frontend manually in two terminals:

```powershell
.\.venv\Scripts\python.exe -m uvicorn backend.api:app --host 127.0.0.1 --port 8000
```

```powershell
.\.venv\Scripts\python.exe -m http.server 5173 --directory frontend --bind 127.0.0.1
```

Then open:

```text
http://127.0.0.1:5173
```

API docs are available at:

```text
http://127.0.0.1:8000/docs
```

Or start both services together with:

```powershell
.\start.ps1
```

`start.ps1` launches FastAPI on `127.0.0.1:8000` and the static frontend on `127.0.0.1:5173`, then stops both child processes when the script exits.