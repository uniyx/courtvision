# Courtvision Rebuild

This folder is a clean rebuild path for the NBA video search project.

## Step 1: Prove The NBA API Path

The first step proved that `nba_api.stats.endpoints.VideoDetailsAsset` can return NBA playlist rows and candidate video URLs when called with browser-like NBA Stats headers.

## Step 2: Parameterize The Query

The second step moves the hard-coded query into reusable helpers in `query.py`.

Current capabilities:

- Resolve an active NBA player by name.
- Build `VideoDetailsAsset` query parameters from a `VideoSearchConfig`.
- Change season, season type, context measure, and player without editing endpoint code.
- Convert the NBA response into a clean pandas DataFrame.
- Add NBA stats event-page links for each play.
- Apply simple local description filters such as `DUNK` or `MISS`.

Run the CLI sample:

```powershell
python query.py --player "Victor Wembanyama" --season 2025-26 --context PTS --contains DUNK
```

Or open `demo.ipynb` to run the same flow step by step.
