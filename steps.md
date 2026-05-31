Step 1: Prove The NBA API Path

Start without NLP.

Hard-code a query like:

player_id = 1641705  # Victor Wembanyama
season = "2025-26"
context_measure = "PTS"
Call VideoDetailsAsset directly and inspect:

playlist
Meta.videoUrls
Goal: understand what NBA gives us before building anything else.

Output should be a small DataFrame with:

Game_ID
Event_Index
Description
Game_Date
Video_Link
Event_Link
This becomes the core data contract.

Step 2: Build Result Formatting

Once raw NBA data works, write process_videos().

This layer renames weird NBA fields:

gi -> Game_ID
ei -> Event_Index
dsc -> Description
hpb/hpa/vpb/vpa -> score fields
Then calculate useful derived fields:

Point_Change
Score_Diff
Score_Diff_After
Event_Link
At this stage, the project is still not “natural language.” It is just a reliable NBA video search wrapper.

Step 3: Add Player Lookup

Next, use:

nba_api.stats.static.players.get_active_players()
Build:

active_players = {
    "victor wembanyama": 1641705,
    "lebron james": 2544,
}
Now the user can pass:

player_name = "victor wembanyama"
instead of a numeric ID.

Important choice: use team_id=0 by default so historical/current team mismatches do not break searches.

Step 4: Add Keyword Maps

Before full NLP, define basketball vocabulary:

"miss", "misses", "brick" -> MISS
"dunk", "layup", "jumper" -> PTS + shot specifier
"assist", "dime" -> AST
"rebound", "board" -> REB
"steal" -> STL
"block" -> BLK
"turnover" -> TOV
This becomes keywords_constants.py.

At this point, simple token matching can support queries like:

lebron dunks
harden misses
wembanyama blocks
Step 5: Add spaCy Phrase Matching

Then introduce spaCy.

Use en_core_web_sm to create an nlp object, and PhraseMatcher to match:

player names
team names
This lets the query parser reliably find full names like:

"lebron james"
"oklahoma city thunder"
The goal is not fancy AI. It is controlled extraction.

Step 6: Add Fuzzy Matching

Use RapidFuzz to handle typos and partial names:

"wemby" -> "victor wembanyama"
"lebron" -> "lebron james"
"hardn" -> "james harden"
This becomes the EntityExtractor.

The extractor should return a structured tuple or object:

{
    "player_name": "victor wembanyama",
    "team_name": "thunder",
    "season_type": "Playoffs",
    "context_measures": ["PTS"],
    "month": "0",
    "clutch_time": None,
    "shot_specifiers": {"Dunk"},
    "score_specifier": None,
}
Step 7: Build The SearchEngine

Now wrap the whole flow:

search_engine = SearchEngine("2025-26")
results = search_engine.query("victor wembanyama dunk playoffs against thunder")
SearchEngine should:

Parse query with EntityExtractor.
Map player/team names to IDs.
Build NBA API params.
Fetch video data.
Apply local filters.
Return a DataFrame.
This is where I’d add the interpretation string:

Interpreted as: Victor Wembanyama dunk field goals made in the Playoffs during the 2025-26 season against the Oklahoma City Thunder
Step 8: Add Local Filtering

Some things are easier to filter after fetching results:

shot type
game-tying
lead-taking
misses
clutch fallback
For example:

MISS is fetched as FGA, then filtered with Point_Change == 0.
game tying is filtered with Score_Diff_After == 0.
lead taking is filtered by score before/after crossing.
clutch can be locally recovered when NBA’s ClutchTime parameter fails.
Step 9: Handle NBA API Weirdness

This project needs resilience because NBA endpoints are unofficial and fragile.

I’d build these protections early:

browser-like headers for stats.nba.com
empty playlist handling
timeout handling
fallback when ClutchTime returns empty 500
Event_Link as a reliable user-facing fallback
treat Video_Link as a candidate, not guaranteed playable
This is where the project becomes robust enough to demo.

Step 10: Add FastAPI

Once notebook usage works, wrap it:

POST /query
Input:

{"query": "victor wembanyama dunk"}
Output:

{
  "query": "...",
  "interpretation": "...",
  "data": [...]
}
FastAPI should only serialize results. It should not contain search logic.

Step 11: Add Frontend

Then build the frontend.

Minimal functional layout:

search box
example query chips
interpretation text
results list
sticky selected-play panel
NBA event link
candidate MP4 link
inline preview attempt
The frontend should assume MP4s may fail and always offer Event_Link.

Step 12: Clean Dependencies

Only after the app works, clean requirements.txt.

Keep direct deps only:

fastapi
nba_api
pandas
pydantic
RapidFuzz
requests
spacy
uvicorn
en_core_web_sm
Then test fresh install on Python 3.13.