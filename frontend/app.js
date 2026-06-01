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
const themeButton = document.querySelector("#themeButton");
const vocabularyButton = document.querySelector("#vocabularyButton");
const vocabularyModal = document.querySelector("#vocabularyModal");
const vocabularyContent = document.querySelector("#vocabularyContent");
const vocabularyIntro = document.querySelector("#vocabularyIntro");
const closeVocabularyButton = document.querySelector("#closeVocabularyButton");

let currentResults = [];
let selectedIndex = null;
let loadingAnimationId = null;
let vocabularyCache = null;

const TEAM_IDS_BY_ABBREVIATION = {
  ATL: 1610612737,
  BOS: 1610612738,
  BKN: 1610612751,
  CHA: 1610612766,
  CHI: 1610612741,
  CLE: 1610612739,
  DAL: 1610612742,
  DEN: 1610612743,
  DET: 1610612765,
  GSW: 1610612744,
  HOU: 1610612745,
  IND: 1610612754,
  LAC: 1610612746,
  LAL: 1610612747,
  MEM: 1610612763,
  MIA: 1610612748,
  MIL: 1610612749,
  MIN: 1610612750,
  NOP: 1610612740,
  NYK: 1610612752,
  OKC: 1610612760,
  ORL: 1610612753,
  PHI: 1610612755,
  PHX: 1610612756,
  PHO: 1610612756,
  POR: 1610612757,
  SAC: 1610612758,
  SAS: 1610612759,
  TOR: 1610612761,
  UTA: 1610612762,
  WAS: 1610612764
};

function setApiStatus(label, tone) {
  apiStatus.textContent = label;
  apiStatusDot.className = "h-2.5 w-2.5 rounded-full";
  apiStatusDot.classList.add(tone === "ok" ? "bg-mint" : tone === "bad" ? "bg-red-500" : "bg-zinc-300");
}

function setTheme(theme) {
  const isDark = theme === "dark";
  document.documentElement.classList.toggle("dark", isDark);
  themeButton.textContent = isDark ? "☀️" : "🌙";
  themeButton.setAttribute("aria-label", isDark ? "Switch to light mode" : "Switch to dark mode");
  themeButton.setAttribute("title", isDark ? "Light mode" : "Dark mode");
  localStorage.setItem("courtvision-theme", theme);
}

function initializeTheme() {
  const savedTheme = localStorage.getItem("courtvision-theme");
  const prefersDark = window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches;
  setTheme(savedTheme || (prefersDark ? "dark" : "light"));
}

function toggleTheme() {
  setTheme(document.documentElement.classList.contains("dark") ? "light" : "dark");
}

function getApiBase() {
  return apiBaseInput.value.trim().replace(/\/$/, "");
}

function formatScore(row) {
  return `${row.Visitor_Team} ${row.Visitor_Points_After} @ ${row.Home_Team} ${row.Home_Points_After}`;
}

function teamLogoUrl(teamAbbreviation) {
  const teamId = TEAM_IDS_BY_ABBREVIATION[safeText(teamAbbreviation).toUpperCase()];
  return teamId ? `https://cdn.nba.com/logos/nba/${teamId}/primary/L/logo.svg` : null;
}

function renderTeamLogo(teamAbbreviation, className = "h-5 w-5") {
  const logoUrl = teamLogoUrl(teamAbbreviation);
  if (!logoUrl) {
    return "";
  }

  return `<img class="${className} shrink-0 object-contain" src="${logoUrl}" alt="${escapeHtml(teamAbbreviation)} logo" loading="lazy" onerror="this.style.display='none'" />`;
}

function renderScore(row) {
  return `
    <span class="inline-flex min-w-0 items-center gap-1.5">
      ${renderTeamLogo(row.Visitor_Team)}
      <span>${escapeHtml(row.Visitor_Team)} ${escapeHtml(row.Visitor_Points_After)}</span>
      <span class="text-zinc-400">@</span>
      ${renderTeamLogo(row.Home_Team)}
      <span>${escapeHtml(row.Home_Team)} ${escapeHtml(row.Home_Points_After)}</span>
    </span>
  `;
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
    button.className = "block w-full px-4 py-3 text-left transition hover:bg-zinc-50 focus:bg-zinc-50 focus:outline-none dark:hover:bg-zinc-800 dark:focus:bg-zinc-800";
    button.dataset.resultIndex = String(index);
    button.innerHTML = `
      <div class="flex items-start justify-between gap-3">
        <div class="min-w-0">
          <p class="truncate text-sm font-medium">${escapeHtml(playDescription(row))}</p>
          <p class="mt-1 flex flex-wrap items-center gap-x-1.5 gap-y-1 text-xs text-zinc-500">
            <span>${escapeHtml(formatGameDate(row.Game_Date))}</span>
            <span class="text-zinc-300">-</span>
            ${renderScore(row)}
          </p>
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

function titleizeKey(key) {
  return key
    .split("_")
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}

function entryPreview(values, limit = 18) {
  if (Array.isArray(values)) {
    return values.slice(0, limit).map((value) => `<code class="rounded bg-zinc-100 px-1.5 py-0.5 text-xs dark:bg-zinc-800">${escapeHtml(value)}</code>`).join(" ");
  }

  return Object.entries(values)
    .slice(0, limit)
    .map(([key, value]) => `<code class="rounded bg-zinc-100 px-1.5 py-0.5 text-xs dark:bg-zinc-800">${escapeHtml(key)} -> ${escapeHtml(value)}</code>`)
    .join(" ");
}

function renderVocabulary(payload) {
  vocabularyIntro.textContent = payload.description || "Loaded from backend/names/*.py";
  vocabularyContent.innerHTML = Object.entries(payload.groups || {})
    .map(([groupName, values]) => {
      const count = payload.counts?.[groupName] ?? (Array.isArray(values) ? values.length : Object.keys(values).length);
      return `
        <section class="border-b border-line py-4 last:border-b-0 dark:border-zinc-800">
          <div class="mb-2 flex items-center justify-between gap-3">
            <h3 class="font-semibold">${escapeHtml(titleizeKey(groupName))}</h3>
            <span class="text-xs text-zinc-500 dark:text-zinc-400">${escapeHtml(count)} entries</span>
          </div>
          <div class="flex flex-wrap gap-1.5 leading-7">${entryPreview(values)}</div>
        </section>
      `;
    })
    .join("");
}

async function openVocabulary() {
  vocabularyModal.classList.remove("hidden");
  vocabularyContent.innerHTML = `<p class="text-zinc-500 dark:text-zinc-400">Loading vocabulary...</p>`;

  try {
    if (!vocabularyCache) {
      const response = await fetch(`${getApiBase()}/vocabulary`);
      const payload = await response.json();
      if (!response.ok) {
        throw new Error(payload.detail || `Vocabulary request failed with status ${response.status}`);
      }
      vocabularyCache = payload;
    }
    renderVocabulary(vocabularyCache);
  } catch (error) {
    vocabularyContent.innerHTML = `<p class="text-red-600 dark:text-red-400">${escapeHtml(error.message)}</p>`;
  }
}

function closeVocabulary() {
  vocabularyModal.classList.add("hidden");
}

function selectResult(index) {
  selectedIndex = index;
  [...resultsList.querySelectorAll("button[data-result-index]")].forEach((button) => {
    const isSelected = Number(button.dataset.resultIndex) === selectedIndex;
    button.classList.toggle("bg-zinc-100", isSelected);
    button.classList.toggle("dark:bg-zinc-800", isSelected);
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
        <p class="text-base font-semibold text-ink dark:text-zinc-100">${escapeHtml(playDescription(row))}</p>
        <p class="mt-1 text-xs text-zinc-500">${escapeHtml(formatGameDate(row.Game_Date))} - Event ${escapeHtml(row.Event_Index)}</p>
        ${
          row.Original_Description && row.Original_Description !== playDescription(row)
            ? `<p class="mt-2 border-l-2 border-line pl-2 text-xs text-zinc-500 dark:border-zinc-700 dark:text-zinc-400">NBA: ${escapeHtml(row.Original_Description)}</p>`
            : ""
        }
      </div>

      <dl class="grid grid-cols-2 gap-3 border-y border-line py-3 text-sm dark:border-zinc-800">
        <div>
          <dt class="text-xs text-zinc-500">Score</dt>
          <dd class="mt-1 font-medium text-ink dark:text-zinc-100">${renderScore(row)}</dd>
        </div>
        <div>
          <dt class="text-xs text-zinc-500">Period</dt>
          <dd class="mt-1 font-medium text-ink dark:text-zinc-100">${escapeHtml(row.Period)}</dd>
        </div>
        <div>
          <dt class="text-xs text-zinc-500">Season Type</dt>
          <dd class="mt-1 font-medium text-ink dark:text-zinc-100">${escapeHtml(row.Season_Type)}</dd>
        </div>
        <div>
          <dt class="text-xs text-zinc-500">Point Change</dt>
          <dd class="mt-1 font-medium text-ink dark:text-zinc-100">${escapeHtml(row.Point_Change)}</dd>
        </div>
        <div>
          <dt class="text-xs text-zinc-500">Score Diff</dt>
          <dd class="mt-1 font-medium text-ink dark:text-zinc-100">${escapeHtml(row.Score_Diff)}</dd>
        </div>
      </dl>

      <div class="space-y-2">
        <a class="block border border-ink bg-ink px-3 py-2 text-center text-sm font-medium text-white hover:bg-zinc-700 dark:border-zinc-100 dark:bg-zinc-100 dark:text-zinc-950 dark:hover:bg-zinc-300" href="${escapeHtml(eventLink)}" target="_blank" rel="noreferrer">Open NBA Event Page</a>
        <a class="block border border-line px-3 py-2 text-center text-sm font-medium text-ink hover:border-ink dark:border-zinc-700 dark:text-zinc-100 dark:hover:border-zinc-400 ${hasVideoLink ? "" : "pointer-events-none opacity-50"}" href="${escapeHtml(videoLink)}" target="_blank" rel="noreferrer">Open Direct MP4</a>
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
  if (loadingAnimationId) {
    clearInterval(loadingAnimationId);
    loadingAnimationId = null;
  }

  searchButton.disabled = isLoading;
  if (!isLoading) {
    searchButton.textContent = "Search";
    return;
  }

  let dotCount = 0;
  const updateLabel = () => {
    searchButton.textContent = `Searching${".".repeat(dotCount)}`;
    dotCount = (dotCount + 1) % 4;
  };

  updateLabel();
  loadingAnimationId = setInterval(updateLabel, 350);
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
themeButton.addEventListener("click", toggleTheme);
vocabularyButton.addEventListener("click", openVocabulary);
closeVocabularyButton.addEventListener("click", closeVocabulary);
vocabularyModal.addEventListener("click", (event) => {
  if (event.target === vocabularyModal) {
    closeVocabulary();
  }
});
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && !vocabularyModal.classList.contains("hidden")) {
    closeVocabulary();
  }
});

initializeTheme();
checkApi();
