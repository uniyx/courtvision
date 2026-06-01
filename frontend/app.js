const form = document.querySelector("#searchForm");
const queryInput = document.querySelector("#queryInput");
const seasonSelect = document.querySelector("#seasonSelect");
const apiBaseInput = document.querySelector("#apiBaseInput");
const searchButton = document.querySelector("#searchButton");
const clearButton = document.querySelector("#clearButton");
const resultsList = document.querySelector("#resultsList");
const emptyState = document.querySelector("#emptyState");
const resultMeta = document.querySelector("#resultMeta");
const detailPane = document.querySelector("#detailPane");
const apiStatus = document.querySelector("#apiStatus");
const apiStatusDot = document.querySelector("#apiStatusDot");
const interpretationText = document.querySelector("#interpretationText");
const warningBox = document.querySelector("#warningBox");

let currentResults = [];
let selectedIndex = null;

function setApiStatus(label, tone) {
  apiStatus.textContent = label;
  apiStatusDot.className = "h-2.5 w-2.5 rounded-full";
  apiStatusDot.classList.add(tone === "ok" ? "bg-mint" : tone === "bad" ? "bg-red-500" : "bg-zinc-300");
}

function getApiBase() {
  return apiBaseInput.value.trim().replace(/\/$/, "");
}

function formatScore(row) {
  return `${row.Visitor_Team} ${row.Visitor_Points_After} @ ${row.Home_Team} ${row.Home_Points_After}`;
}

function safeText(value) {
  return value === null || value === undefined || value === "" ? "Unknown" : String(value);
}

function escapeHtml(value) {
  return safeText(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function playDescription(row) {
  return row.Display_Description || row.Description;
}

function formatGameDate(value) {
  if (!value) {
    return "Unknown date";
  }

  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return safeText(value);
  }

  return new Intl.DateTimeFormat("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
    timeZone: "UTC"
  }).format(date);
}

function formatPlayMeta(row) {
  return `${formatGameDate(row.Game_Date)} - ${formatScore(row)}`;
}

function formatLatency(milliseconds) {
  return milliseconds >= 1000 ? `${(milliseconds / 1000).toFixed(1)}s` : `${milliseconds}ms`;
}

function renderResults(rows, query, season) {
  currentResults = rows;
  selectedIndex = null;
  resultsList.innerHTML = "";
  clearButton.classList.toggle("hidden", rows.length === 0);

  if (rows.length === 0) {
    resultsList.classList.add("hidden");
    emptyState.classList.remove("hidden");
    emptyState.textContent = `No results found for "${query}".`;
    resultMeta.textContent = `0 plays - ${season}`;
    detailPane.innerHTML = "Select a result to inspect links.";
    return;
  }

  emptyState.classList.add("hidden");
  resultsList.classList.remove("hidden");
  resultMeta.textContent = `${rows.length} loaded play${rows.length === 1 ? "" : "s"} for "${query}" - ${season}`;

  rows.forEach((row, index) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "block w-full px-4 py-3 text-left transition hover:bg-zinc-50 focus:bg-zinc-50 focus:outline-none";
    button.dataset.resultIndex = String(index);
    button.innerHTML = `
      <div class="flex items-start justify-between gap-3">
        <div class="min-w-0">
          <p class="truncate text-sm font-medium">${escapeHtml(playDescription(row))}</p>
          <p class="mt-1 text-xs text-zinc-500">${escapeHtml(formatPlayMeta(row))}</p>
        </div>
        <span class="shrink-0 rounded border border-line px-2 py-1 text-xs text-zinc-600">Q${safeText(row.Period)}</span>
      </div>
    `;
    button.addEventListener("click", () => selectResult(index));
    resultsList.appendChild(button);

    if (index === 0) {
      selectResult(index);
    }
  });
}

function renderInterpretation(interpretation) {
  if (!interpretation) {
    interpretationText.classList.add("hidden");
    interpretationText.textContent = "";
    return;
  }

  interpretationText.classList.remove("hidden");
  interpretationText.textContent = interpretation;
}

function renderWarnings(warnings) {
  const visibleWarnings = Array.isArray(warnings) ? warnings.filter(Boolean) : [];
  if (visibleWarnings.length === 0) {
    warningBox.classList.add("hidden");
    warningBox.innerHTML = "";
    return;
  }

  warningBox.classList.remove("hidden");
  warningBox.innerHTML = visibleWarnings.map((warning) => `<p>${escapeHtml(warning)}</p>`).join("");
}

function selectResult(index) {
  selectedIndex = index;
  [...resultsList.querySelectorAll("button[data-result-index]")].forEach((button) => {
    const isSelected = Number(button.dataset.resultIndex) === selectedIndex;
    button.classList.toggle("bg-zinc-100", isSelected);
  });
  renderDetail(currentResults[index]);
}

function renderDetail(row) {
  const eventLink = row.Event_Link || "#";
  const videoLink = row.Video_Link || "#";
  const hasVideoLink = Boolean(row.Video_Link);

  detailPane.innerHTML = `
    <div class="space-y-4">
      <div>
        <p class="text-base font-semibold text-ink">${escapeHtml(playDescription(row))}</p>
        <p class="mt-1 text-xs text-zinc-500">${escapeHtml(formatGameDate(row.Game_Date))} - Event ${escapeHtml(row.Event_Index)}</p>
        ${
          row.Original_Description && row.Original_Description !== playDescription(row)
            ? `<p class="mt-2 border-l-2 border-line pl-2 text-xs text-zinc-500">NBA: ${escapeHtml(row.Original_Description)}</p>`
            : ""
        }
      </div>

      <dl class="grid grid-cols-2 gap-3 border-y border-line py-3 text-sm">
        <div>
          <dt class="text-xs text-zinc-500">Score</dt>
          <dd class="mt-1 font-medium text-ink">${escapeHtml(formatScore(row))}</dd>
        </div>
        <div>
          <dt class="text-xs text-zinc-500">Period</dt>
          <dd class="mt-1 font-medium text-ink">${escapeHtml(row.Period)}</dd>
        </div>
        <div>
          <dt class="text-xs text-zinc-500">Season Type</dt>
          <dd class="mt-1 font-medium text-ink">${escapeHtml(row.Season_Type)}</dd>
        </div>
        <div>
          <dt class="text-xs text-zinc-500">Point Change</dt>
          <dd class="mt-1 font-medium text-ink">${escapeHtml(row.Point_Change)}</dd>
        </div>
        <div>
          <dt class="text-xs text-zinc-500">Score Diff</dt>
          <dd class="mt-1 font-medium text-ink">${escapeHtml(row.Score_Diff)}</dd>
        </div>
      </dl>

      <div class="space-y-2">
        <a class="block border border-ink bg-ink px-3 py-2 text-center text-sm font-medium text-white hover:bg-zinc-700" href="${escapeHtml(eventLink)}" target="_blank" rel="noreferrer">Open NBA Event Page</a>
        <a class="block border border-line px-3 py-2 text-center text-sm font-medium text-ink hover:border-ink ${hasVideoLink ? "" : "pointer-events-none opacity-50"}" href="${escapeHtml(videoLink)}" target="_blank" rel="noreferrer">Open Direct MP4</a>
      </div>

      <div>
        <p class="mb-2 text-xs font-medium uppercase tracking-wide text-zinc-500">Inline MP4 Preview</p>
        ${
          hasVideoLink
            ? `<video class="aspect-video w-full bg-black" src="${escapeHtml(videoLink)}" controls muted playsinline></video>`
            : `<div class="flex aspect-video w-full items-center justify-center bg-zinc-100 text-xs text-zinc-500">No MP4 returned</div>`
        }
      </div>
    </div>
  `;
}

function setLoading(isLoading) {
  searchButton.disabled = isLoading;
  searchButton.textContent = isLoading ? "Searching..." : "Search";
}

async function runSearch(query) {
  const apiBase = getApiBase();
  const season = seasonSelect.value;
  const startedAt = performance.now();
  setLoading(true);
  resultMeta.textContent = "Searching...";
  setApiStatus("Querying API", "neutral");
  renderWarnings([]);

  try {
    const response = await fetch(`${apiBase}/query`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        query,
        season,
        limit: 25,
        offset: 0,
        use_play_by_play: false
      })
    });

    const payload = await response.json();
    if (!response.ok) {
      const detail = Array.isArray(payload.detail)
        ? payload.detail.map((item) => item.msg).join(", ")
        : payload.detail || `Request failed with status ${response.status}`;
      throw new Error(detail);
    }

    const totalElapsedMs = Math.round(performance.now() - startedAt);
    const apiLatencyMs = payload.latency_ms ?? totalElapsedMs;
    setApiStatus(`API ${formatLatency(apiLatencyMs)} / total ${formatLatency(totalElapsedMs)}`, "ok");
    renderInterpretation(payload.interpretation);
    renderWarnings(payload.warnings);
    renderResults(payload.results || [], payload.query || query, season);
    resultMeta.textContent = `${payload.results.length} of ${payload.filtered_result_count} filtered plays - ${payload.raw_result_count} raw`;
  } catch (error) {
    setApiStatus("API error", "bad");
    renderInterpretation(null);
    renderWarnings([]);
    resultsList.classList.add("hidden");
    emptyState.classList.remove("hidden");
    emptyState.textContent = error.message;
    resultMeta.textContent = "Search failed";
    detailPane.innerHTML = "Check that FastAPI is running on the configured API URL.";
  } finally {
    setLoading(false);
  }
}

form.addEventListener("submit", (event) => {
  event.preventDefault();
  const query = queryInput.value.trim();
  if (query) {
    runSearch(query);
  }
});

document.querySelectorAll(".example").forEach((button) => {
  button.addEventListener("click", () => {
    queryInput.value = button.textContent;
    runSearch(button.textContent);
  });
});

clearButton.addEventListener("click", () => {
  currentResults = [];
  selectedIndex = null;
  resultsList.innerHTML = "";
  resultsList.classList.add("hidden");
  emptyState.classList.remove("hidden");
  emptyState.textContent = "Search results will appear here.";
  resultMeta.textContent = "Run a search to load plays.";
  detailPane.innerHTML = "Select a result to inspect links.";
  renderInterpretation(null);
  renderWarnings([]);
  clearButton.classList.add("hidden");
});

async function checkApi() {
  const apiBase = getApiBase();
  setApiStatus("Checking API", "neutral");

  try {
    const [healthResponse, seasonsResponse] = await Promise.all([
      fetch(`${apiBase}/health`),
      fetch(`${apiBase}/seasons`)
    ]);

    if (!healthResponse.ok) {
      throw new Error(`Health check failed with status ${healthResponse.status}`);
    }

    if (seasonsResponse.ok) {
      const payload = await seasonsResponse.json();
      if (Array.isArray(payload.seasons) && payload.seasons.length > 0) {
        seasonSelect.innerHTML = payload.seasons
          .map((season) => `<option value="${escapeHtml(season)}">${escapeHtml(season)}</option>`)
          .join("");
        seasonSelect.value = payload.default || payload.seasons[0];
      }
    }

    setApiStatus("API connected", "ok");
  } catch (error) {
    setApiStatus("API offline", "bad");
  }
}

apiBaseInput.addEventListener("change", checkApi);
checkApi();
