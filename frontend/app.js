const form = document.querySelector("#searchForm");
const queryInput = document.querySelector("#queryInput");
const seasonSelect = document.querySelector("#seasonSelect");
const playByPlayToggle = document.querySelector("#playByPlayToggle");
const apiBaseInput = document.querySelector("#apiBaseInput");
const searchButton = document.querySelector("#searchButton");
const clearButton = document.querySelector("#clearButton");
const resultsList = document.querySelector("#resultsList");
const emptyState = document.querySelector("#emptyState");
const resultMeta = document.querySelector("#resultMeta");
const detailPane = document.querySelector("#detailPane");
const loadMoreSentinel = document.querySelector("#loadMoreSentinel");
const apiStatus = document.querySelector("#apiStatus");
const apiStatusDot = document.querySelector("#apiStatusDot");
const interpretationText = document.querySelector("#interpretationText");
const warningBox = document.querySelector("#warningBox");
const themeButton = document.querySelector("#themeButton");
const teamsButton = document.querySelector("#teamsButton");
const teamsModal = document.querySelector("#teamsModal");
const teamsContent = document.querySelector("#teamsContent");
const teamsIntro = document.querySelector("#teamsIntro");
const closeTeamsButton = document.querySelector("#closeTeamsButton");
const vocabularyButton = document.querySelector("#vocabularyButton");
const vocabularyModal = document.querySelector("#vocabularyModal");
const vocabularyContent = document.querySelector("#vocabularyContent");
const vocabularyIntro = document.querySelector("#vocabularyIntro");
const closeVocabularyButton = document.querySelector("#closeVocabularyButton");

let currentResults = [];
let selectedIndex = null;
let loadingAnimationId = null;
let teamsCacheBySeason = {};
let teamRostersBySeason = {};
let rosterLoadingTeamId = null;
let rosterErrorsBySeason = {};
let selectedTeamId = null;
let vocabularyCache = null;
let expandedVocabularyGroups = new Set();
let currentSearchId = null;
let currentQuery = "";
let currentSeason = "";
let hasMoreResults = false;
let isLoadingMore = false;

const PAGE_SIZE = 25;
let resultObserver = null;

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
  themeButton.textContent = isDark ? "\u2600\uFE0F" : "\uD83C\uDF19";
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

function teamBrowserLogoUrl(team) {
  return team.logo_url || teamLogoUrl(team.abbreviation);
}

function formatPercent(value) {
  if (value === null || value === undefined || value === "") {
    return "Unknown";
  }

  const numericValue = Number(value);
  if (Number.isNaN(numericValue)) {
    return safeText(value);
  }

  return numericValue <= 1 ? numericValue.toFixed(3).replace(/^0/, "") : numericValue.toFixed(3);
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

function responseDetail(payload, fallback) {
  if (Array.isArray(payload?.detail)) {
    return payload.detail.map((item) => item.msg || item.message || String(item)).join(", ");
  }

  return payload?.detail || payload?.message || fallback;
}

async function readJsonResponse(response, label) {
  const text = await response.text();
  let payload = {};

  if (text) {
    try {
      payload = JSON.parse(text);
    } catch (error) {
      if (!response.ok) {
        throw new Error(`${label} failed with status ${response.status}: ${text.slice(0, 200)}`);
      }
      throw new Error(`${label} returned invalid JSON.`);
    }
  }

  if (!response.ok) {
    throw new Error(responseDetail(payload, `${label} failed with status ${response.status}`));
  }

  return payload;
}

function updateLoadMoreSentinel() {
  if (currentResults.length === 0 || !currentSearchId) {
    loadMoreSentinel.classList.add("hidden");
    loadMoreSentinel.textContent = "";
    return;
  }

  loadMoreSentinel.classList.remove("hidden");
  if (isLoadingMore) {
    loadMoreSentinel.textContent = "Loading more plays...";
  } else if (hasMoreResults) {
    loadMoreSentinel.textContent = "Scroll for more plays";
  } else {
    loadMoreSentinel.textContent = "All matching plays loaded";
  }
}

function renderResults(rows, query, season, append = false) {
  const startIndex = append ? currentResults.length : 0;
  if (append) {
    currentResults = [...currentResults, ...rows];
  } else {
    currentResults = rows;
    selectedIndex = null;
    resultsList.innerHTML = "";
  }
  clearButton.classList.toggle("hidden", currentResults.length === 0);
  updateLoadMoreSentinel();

  if (currentResults.length === 0) {
    resultsList.classList.add("hidden");
    emptyState.classList.remove("hidden");
    emptyState.textContent = `No results found for "${query}".`;
    resultMeta.textContent = `0 plays - ${season}`;
    detailPane.innerHTML = "Select a result to inspect links.";
    updateLoadMoreSentinel();
    return;
  }

  emptyState.classList.add("hidden");
  resultsList.classList.remove("hidden");
  resultMeta.textContent = `${currentResults.length} loaded play${currentResults.length === 1 ? "" : "s"} for "${query}" - ${season}`;

  rows.forEach((row, index) => {
    const resultIndex = startIndex + index;
    const button = document.createElement("button");
    button.type = "button";
    button.className = "block w-full px-4 py-3 text-left transition hover:bg-zinc-50 focus:bg-zinc-50 focus:outline-none dark:hover:bg-zinc-800 dark:focus:bg-zinc-800";
    button.dataset.resultIndex = String(resultIndex);
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
    button.addEventListener("click", () => selectResult(resultIndex));
    resultsList.appendChild(button);

    if (!append && index === 0) {
      selectResult(resultIndex);
    }
  });
  updateLoadMoreSentinel();
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

function teamStat(label, value) {
  return `
    <div class="border border-line px-3 py-2 dark:border-zinc-800">
      <dt class="text-xs text-zinc-500 dark:text-zinc-400">${escapeHtml(label)}</dt>
      <dd class="mt-1 font-semibold text-ink dark:text-zinc-100">${escapeHtml(value)}</dd>
    </div>
  `;
}

function renderPlayerRow(player) {
  return `
    <tr class="border-b border-line last:border-b-0 dark:border-zinc-800">
      <td class="px-3 py-2 font-medium text-ink dark:text-zinc-100">${escapeHtml(player.name)}</td>
      <td class="px-3 py-2 text-zinc-500 dark:text-zinc-400">${escapeHtml(player.number || "-")}</td>
      <td class="px-3 py-2 text-zinc-500 dark:text-zinc-400">${escapeHtml(player.position || "-")}</td>
      <td class="px-3 py-2 text-zinc-500 dark:text-zinc-400">${escapeHtml(player.height || "-")}</td>
      <td class="px-3 py-2 text-zinc-500 dark:text-zinc-400">${escapeHtml(player.age || "-")}</td>
      <td class="px-3 py-2 text-zinc-500 dark:text-zinc-400">${escapeHtml(player.experience || "-")}</td>
      <td class="px-3 py-2 text-zinc-500 dark:text-zinc-400">${escapeHtml(player.school || "-")}</td>
    </tr>
  `;
}

function renderTeamDetail(team) {
  const logoUrl = teamBrowserLogoUrl(team);
  const season = seasonSelect.value;
  const players = teamRostersBySeason[season]?.[team.id] || [];
  const rosterError = rosterErrorsBySeason[season]?.[team.id] || "";
  const isRosterLoading = String(rosterLoadingTeamId) === String(team.id);
  const rosterMessage = rosterError || (isRosterLoading ? "Loading roster..." : "Roster unavailable.");

  return `
    <article class="mt-4 border border-line bg-zinc-50 p-4 dark:border-zinc-800 dark:bg-zinc-900">
      <div class="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <div class="flex min-w-0 items-center gap-3">
          ${
            logoUrl
              ? `<img class="h-16 w-16 shrink-0 object-contain" src="${escapeHtml(logoUrl)}" alt="${escapeHtml(team.full_name)} logo" loading="lazy" onerror="this.style.display='none'" />`
              : ""
          }
          <div class="min-w-0">
            <h3 class="text-lg font-semibold text-ink dark:text-zinc-100">${escapeHtml(team.full_name)}</h3>
            <p class="mt-0.5 text-sm text-zinc-500 dark:text-zinc-400">${escapeHtml(team.conference)} - ${escapeHtml(team.division)}</p>
          </div>
        </div>
        <div class="text-left sm:text-right">
          <p class="text-2xl font-semibold text-ink dark:text-zinc-100">#${escapeHtml(team.conference_rank)}</p>
          <p class="text-xs text-zinc-500 dark:text-zinc-400">Conference rank</p>
        </div>
      </div>

      <dl class="mt-4 grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
        ${teamStat("Record", team.record || `${team.wins}-${team.losses}`)}
        ${teamStat("Win Pct", formatPercent(team.win_pct))}
        ${teamStat("Home / Road", `${safeText(team.home)} / ${safeText(team.road)}`)}
        ${teamStat("Last 10", team.last_10 || "Unknown")}
        ${teamStat("Conf / Div", `${safeText(team.conference_record)} / ${safeText(team.division_record)}`)}
        ${teamStat("Points PG", team.points_pg || "Unknown")}
        ${teamStat("Opp Points PG", team.opp_points_pg || "Unknown")}
        ${teamStat("Diff PG", team.diff_points_pg || "Unknown")}
      </dl>

      <div class="mt-4 overflow-x-auto border border-line bg-white dark:border-zinc-800 dark:bg-zinc-950">
        <table class="min-w-full text-left text-xs">
          <thead class="border-b border-line text-zinc-500 dark:border-zinc-800 dark:text-zinc-400">
            <tr>
              <th class="px-3 py-2 font-medium">Player</th>
              <th class="px-3 py-2 font-medium">No.</th>
              <th class="px-3 py-2 font-medium">Pos</th>
              <th class="px-3 py-2 font-medium">Ht</th>
              <th class="px-3 py-2 font-medium">Age</th>
              <th class="px-3 py-2 font-medium">Exp</th>
              <th class="px-3 py-2 font-medium">School</th>
            </tr>
          </thead>
          <tbody>
            ${players.length > 0 ? players.map(renderPlayerRow).join("") : `<tr><td class="px-3 py-3 text-zinc-500 dark:text-zinc-400" colspan="7">${escapeHtml(rosterMessage)}</td></tr>`}
          </tbody>
        </table>
      </div>
    </article>
  `;
}

function renderConference(conference) {
  const teams = Array.isArray(conference.teams) ? conference.teams : [];
  const selectedTeam = teams.find((team) => String(team.id) === String(selectedTeamId));

  return `
    <section class="border-b border-line py-5 first:pt-0 last:border-b-0 dark:border-zinc-800">
      <div class="mb-3 flex items-baseline justify-between gap-3">
        <h3 class="font-semibold">${escapeHtml(conference.name)}</h3>
        <span class="text-xs text-zinc-500 dark:text-zinc-400">${escapeHtml(teams.length)} teams</span>
      </div>
      <div class="grid grid-cols-3 gap-2 sm:grid-cols-5 lg:grid-cols-8 xl:grid-cols-10">
        ${teams
          .map((team) => {
            const logoUrl = teamBrowserLogoUrl(team);
            const isSelected = String(team.id) === String(selectedTeamId);
            return `
              <button class="relative flex aspect-square items-center justify-center border bg-white p-3 transition hover:border-ink focus:outline-none focus:ring-2 focus:ring-ink/20 dark:bg-zinc-900 dark:hover:border-zinc-400 ${
                isSelected ? "border-ink dark:border-zinc-100" : "border-line dark:border-zinc-800"
              }" type="button" data-team-id="${escapeHtml(team.id)}" title="#${escapeHtml(team.conference_rank)} ${escapeHtml(team.full_name)}" aria-label="Open ${escapeHtml(team.full_name)}">
                <span class="absolute left-1 top-1 text-[10px] font-semibold text-zinc-500 dark:text-zinc-400">#${escapeHtml(team.conference_rank)}</span>
                ${
                  logoUrl
                    ? `<img class="h-full max-h-14 w-full object-contain" src="${escapeHtml(logoUrl)}" alt="${escapeHtml(team.full_name)} logo" loading="lazy" onerror="this.style.display='none'" />`
                    : `<span class="text-sm font-semibold">${escapeHtml(team.abbreviation)}</span>`
                }
              </button>
            `;
          })
          .join("")}
      </div>
      ${selectedTeam ? renderTeamDetail(selectedTeam) : ""}
    </section>
  `;
}

function renderTeams(payload) {
  const conferences = Array.isArray(payload.conferences) ? payload.conferences : [];
  teamsIntro.textContent = `${payload.season || seasonSelect.value} regular-season standings, rosters, and team stats`;
  teamsContent.innerHTML = `
    ${
      Array.isArray(payload.warnings) && payload.warnings.length > 0
        ? `<div class="mb-4 border-l-2 border-amber-500 bg-amber-50 px-3 py-2 text-sm text-amber-800 dark:bg-zinc-900 dark:text-amber-300">${payload.warnings.map((warning) => `<p>${escapeHtml(warning)}</p>`).join("")}</div>`
        : ""
    }
    ${conferences.map(renderConference).join("")}
  `;
}

async function openTeams() {
  const season = seasonSelect.value;
  teamsModal.classList.remove("hidden");
  teamsContent.innerHTML = `<p class="text-zinc-500 dark:text-zinc-400">Loading teams...</p>`;
  teamsIntro.textContent = `${season} regular-season standings, rosters, and team stats`;

  try {
    if (!teamsCacheBySeason[season]) {
      const response = await fetch(`${getApiBase()}/teams?season=${encodeURIComponent(season)}`);
      teamsCacheBySeason[season] = await readJsonResponse(response, "Teams request");
    }
    renderTeams(teamsCacheBySeason[season]);
  } catch (error) {
    teamsContent.innerHTML = `<p class="text-red-600 dark:text-red-400">${escapeHtml(error.message)}</p>`;
  }
}

async function loadTeamRoster(teamId) {
  const season = seasonSelect.value;
  teamRostersBySeason[season] = teamRostersBySeason[season] || {};
  rosterErrorsBySeason[season] = rosterErrorsBySeason[season] || {};

  if (teamRostersBySeason[season][teamId]) {
    return;
  }

  rosterLoadingTeamId = String(teamId);
  rosterErrorsBySeason[season][teamId] = "";
  renderTeams(teamsCacheBySeason[season]);

  try {
    const response = await fetch(`${getApiBase()}/teams/${encodeURIComponent(teamId)}/roster?season=${encodeURIComponent(season)}`);
    const payload = await readJsonResponse(response, "Roster request");
    teamRostersBySeason[season][teamId] = Array.isArray(payload.players) ? payload.players : [];
  } catch (error) {
    rosterErrorsBySeason[season][teamId] = error.message;
  } finally {
    if (String(rosterLoadingTeamId) === String(teamId)) {
      rosterLoadingTeamId = null;
    }
    renderTeams(teamsCacheBySeason[season]);
  }
}

function closeTeams() {
  teamsModal.classList.add("hidden");
}

function titleizeKey(key) {
  return key
    .split("_")
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}

function entryPreview(values, expanded, limit = 18) {
  if (Array.isArray(values)) {
    const visibleValues = expanded ? values : values.slice(0, limit);
    return visibleValues.map((value) => `<code class="rounded bg-zinc-100 px-1.5 py-0.5 text-xs dark:bg-zinc-800">${escapeHtml(value)}</code>`).join(" ");
  }

  const entries = expanded ? Object.entries(values) : Object.entries(values).slice(0, limit);
  return entries
    .map(([key, value]) => `<code class="rounded bg-zinc-100 px-1.5 py-0.5 text-xs dark:bg-zinc-800">${escapeHtml(key)} -> ${escapeHtml(value)}</code>`)
    .join(" ");
}

function renderVocabulary(payload) {
  vocabularyIntro.textContent = payload.description || "Loaded from backend/names/*.py";
  vocabularyContent.innerHTML = Object.entries(payload.groups || {})
    .map(([groupName, values]) => {
      const count = payload.counts?.[groupName] ?? (Array.isArray(values) ? values.length : Object.keys(values).length);
      const expanded = expandedVocabularyGroups.has(groupName);
      return `
        <section class="border-b border-line py-4 last:border-b-0 dark:border-zinc-800">
          <div class="mb-2 flex items-center justify-between gap-3">
            <h3 class="font-semibold">${escapeHtml(titleizeKey(groupName))}</h3>
            <div class="flex items-center gap-2">
              <span class="text-xs text-zinc-500 dark:text-zinc-400">${escapeHtml(count)} entries</span>
              <button class="h-7 w-7 border border-line text-base leading-none hover:border-ink dark:border-zinc-700 dark:hover:border-zinc-400" type="button" data-vocab-group="${escapeHtml(groupName)}" aria-expanded="${expanded}" title="${expanded ? "Collapse" : "Expand"} ${escapeHtml(titleizeKey(groupName))}">
                ${expanded ? "-" : "+"}
              </button>
            </div>
          </div>
          <div class="flex flex-wrap gap-1.5 leading-7">${entryPreview(values, expanded)}</div>
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
      const payload = await readJsonResponse(response, "Vocabulary request");
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
        ${
          row.Recipient_Player
            ? `<div>
                <dt class="text-xs text-zinc-500">Recipient</dt>
                <dd class="mt-1 font-medium text-ink dark:text-zinc-100">${escapeHtml(row.Recipient_Player)}</dd>
              </div>`
            : ""
        }
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
  currentSearchId = null;
  currentQuery = query;
  currentSeason = season;
  hasMoreResults = false;
  isLoadingMore = false;
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
        limit: PAGE_SIZE,
        offset: 0,
        use_play_by_play: playByPlayToggle.checked
      })
    });

    const payload = await readJsonResponse(response, "Search request");
    const rows = Array.isArray(payload.results) ? payload.results : [];
    currentSearchId = payload.search_id || null;
    hasMoreResults = Boolean(payload.has_more);

    const totalElapsedMs = Math.round(performance.now() - startedAt);
    const apiLatencyMs = payload.latency_ms ?? totalElapsedMs;
    setApiStatus(`API ${formatLatency(apiLatencyMs)} / total ${formatLatency(totalElapsedMs)}`, "ok");
    renderInterpretation(payload.interpretation);
    renderWarnings(payload.warnings);
    renderResults(rows, payload.query || query, season);
    resultMeta.textContent = `${currentResults.length} of ${payload.filtered_result_count ?? currentResults.length} filtered plays - ${payload.raw_result_count ?? 0} raw`;
    setTimeout(maybeLoadNextPage, 0);
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

async function loadNextPage() {
  if (!currentSearchId || !hasMoreResults || isLoadingMore) {
    return;
  }

  isLoadingMore = true;
  updateLoadMoreSentinel();
  const apiBase = getApiBase();
  const offset = currentResults.length;
  setApiStatus("Loading more", "neutral");

  try {
    const response = await fetch(`${apiBase}/query/${currentSearchId}?offset=${offset}&limit=${PAGE_SIZE}`);
    const payload = await readJsonResponse(response, "Results page request");
    const rows = Array.isArray(payload.results) ? payload.results : [];
    hasMoreResults = Boolean(payload.has_more);
    renderResults(rows, payload.query || currentQuery, currentSeason, true);
    resultMeta.textContent = `${currentResults.length} of ${payload.filtered_result_count ?? currentResults.length} filtered plays - ${payload.raw_result_count ?? 0} raw`;
    setApiStatus("API connected", "ok");
    setTimeout(maybeLoadNextPage, 0);
  } catch (error) {
    hasMoreResults = false;
    setApiStatus("API error", "bad");
    renderWarnings([error.message]);
  } finally {
    isLoadingMore = false;
    updateLoadMoreSentinel();
  }
}

function maybeLoadNextPage() {
  const remainingPixels = document.documentElement.scrollHeight - window.innerHeight - window.scrollY;
  if (remainingPixels < 400) {
    loadNextPage();
  }
}

function initializeResultObserver() {
  if (!("IntersectionObserver" in window)) {
    return;
  }

  resultObserver = new IntersectionObserver(
    (entries) => {
      if (entries.some((entry) => entry.isIntersecting)) {
        loadNextPage();
      }
    },
    { root: null, rootMargin: "600px 0px 600px 0px", threshold: 0 }
  );
  resultObserver.observe(loadMoreSentinel);
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
  currentSearchId = null;
  currentQuery = "";
  currentSeason = "";
  hasMoreResults = false;
  isLoadingMore = false;
  resultsList.innerHTML = "";
  resultsList.classList.add("hidden");
  emptyState.classList.remove("hidden");
  emptyState.textContent = "Search results will appear here.";
  resultMeta.textContent = "Run a search to load plays.";
  detailPane.innerHTML = "Select a result to inspect links.";
  renderInterpretation(null);
  renderWarnings([]);
  updateLoadMoreSentinel();
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
      const payload = await readJsonResponse(seasonsResponse, "Seasons request");
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
window.addEventListener("scroll", maybeLoadNextPage);
themeButton.addEventListener("click", toggleTheme);
teamsButton.addEventListener("click", openTeams);
closeTeamsButton.addEventListener("click", closeTeams);
teamsContent.addEventListener("click", async (event) => {
  const button = event.target.closest("button[data-team-id]");
  if (!button || !teamsContent.contains(button)) {
    return;
  }

  selectedTeamId = String(button.dataset.teamId);
  renderTeams(teamsCacheBySeason[seasonSelect.value]);
  await loadTeamRoster(selectedTeamId);
});
vocabularyButton.addEventListener("click", openVocabulary);
closeVocabularyButton.addEventListener("click", closeVocabulary);
vocabularyContent.addEventListener("click", (event) => {
  const button = event.target.closest("button[data-vocab-group]");
  if (!button || !vocabularyContent.contains(button)) {
    return;
  }

  const groupName = button.dataset.vocabGroup;
  if (expandedVocabularyGroups.has(groupName)) {
    expandedVocabularyGroups.delete(groupName);
  } else {
    expandedVocabularyGroups.add(groupName);
  }
  renderVocabulary(vocabularyCache);
});
teamsModal.addEventListener("click", (event) => {
  if (event.target === teamsModal) {
    closeTeams();
  }
});
vocabularyModal.addEventListener("click", (event) => {
  if (event.target === vocabularyModal) {
    closeVocabulary();
  }
});
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && !teamsModal.classList.contains("hidden")) {
    closeTeams();
  }

  if (event.key === "Escape" && !vocabularyModal.classList.contains("hidden")) {
    closeVocabulary();
  }
});

initializeTheme();
initializeResultObserver();
checkApi();
