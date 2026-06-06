.\.venv\Scripts\python.exe -m uvicorn backend.api:app --host 127.0.0.1 --port 8000 --reload

.\.venv\Scripts\python.exe -m http.server 5173 --directory frontend --bind 127.0.0.1

.\start.ps1