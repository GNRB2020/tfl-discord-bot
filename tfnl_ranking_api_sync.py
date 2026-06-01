<div id="tfnl-overall-ranking-app" class="tfnl-overall-ranking-app">

  <nav class="tfnl-top-nav" aria-label="TFNL Navigation">
    <a href="index.php?option=com_content&amp;view=article&amp;id=19">TFNL Übersicht</a>
    <a href="index.php?option=com_content&amp;view=article&amp;id=20">Schedule</a>
    <a href="index.php?option=com_content&amp;view=article&amp;id=21">Results</a>
    <a href="index.php?option=com_content&amp;view=article&amp;id=22" class="is-active">Overall Ranking</a>
    <a href="index.php?option=com_content&amp;view=article&amp;id=23">Season Ranking</a>
    <a href="index.php?option=com_content&amp;view=article&amp;id=24">Invitationals</a>
  </nav>
  <section class="tfnl-ranking-hero">
    <div>
      <div class="tfnl-kicker">TRY FORCE NACHTEULEN LADDER</div>
      <h1>TFNL Overall Ranking</h1>
      <p>
        All-Time ELO Ranking der TFNL. Umschaltbar zwischen Gesamtwertung und
        den einzelnen Modis.
      </p>
    </div>

    <div class="tfnl-hero-stats">
      <div class="tfnl-stat-card">
        <span id="tfnl-total-players">0</span>
        <small>Runner</small>
      </div>
      <div class="tfnl-stat-card">
        <span id="tfnl-total-games">0</span>
        <small>Races</small>
      </div>
      <div class="tfnl-stat-card">
        <span id="tfnl-total-modes">0</span>
        <small>Modis</small>
      </div>
    </div>
  </section>

  <section class="tfnl-controls">
    <div class="tfnl-tabs">
      <button type="button" class="tfnl-tab is-active" data-scope="overall">Gesamt</button>
      <button type="button" class="tfnl-tab" data-scope="mode">Nach Modus</button>
    </div>

    <div class="tfnl-control-grid">
      <div>
        <label for="tfnl-mode-select">Modus</label>
        <select id="tfnl-mode-select" class="tfnl-select" disabled="">
          <option value="ALL">Gesamt</option>
        </select>
      </div>

      <div>
        <label for="tfnl-min-games">Mindestspiele</label>
        <select id="tfnl-min-games" class="tfnl-select">
          <option value="0">Alle</option>
          <option value="1">mind. 1</option>
          <option value="3">mind. 3</option>
          <option value="5">mind. 5</option>
          <option value="10">mind. 10</option>
        </select>
      </div>

      <div>
        <label for="tfnl-search">Suche</label>
        <input id="tfnl-search" class="tfnl-input" type="text" placeholder="Runner suchen …">
      </div>
    </div>
  </section>

  <section class="tfnl-summary">
    <div>
      <strong id="tfnl-visible-players">0</strong>
      sichtbare Runner
    </div>
    <div id="tfnl-current-view">Overall Gesamt</div>
    <div id="tfnl-last-update">Stand: -</div>
  </section>

  <section id="tfnl-mode-overview" class="tfnl-mode-overview"></section>

  <section class="tfnl-ranking-table-wrap">
    <table class="tfnl-ranking-table">
      <thead>
        <tr>
          <th data-sort="rank">#</th>
          <th data-sort="player_name">Runner</th>
          <th data-sort="games">G</th>
          <th data-sort="wins">S</th>
          <th data-sort="draws">U</th>
          <th data-sort="lose">N</th>
          <th data-sort="winrate">Winrate</th>
          <th data-sort="elo">ELO</th>
        </tr>
      </thead>
      <tbody id="tfnl-ranking-body">
        <tr>
          <td colspan="8">Lade Ranking …</td>
        </tr>
      </tbody>
    </table>
  </section>
</div>

<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700;800;900&family=Press+Start+2P&display=swap');

.tfnl-overall-ranking-app {
  --tfnl-bg: #05070b;
  --tfnl-panel: rgba(10, 16, 23, 0.92);
  --tfnl-panel-2: rgba(15, 25, 34, 0.94);
  --tfnl-border: rgba(255, 204, 64, 0.24);
  --tfnl-border-soft: rgba(89, 255, 216, 0.16);
  --tfnl-text: #f1fff9;
  --tfnl-muted: #9fb7b3;
  --tfnl-green: #00ffd0;
  --tfnl-gold: #ffd45c;
  --tfnl-red: #ff5d73;
  --tfnl-blue: #59c8ff;
  --tfnl-purple: #c58cff;
  --tfnl-shadow: 0 18px 44px rgba(0, 0, 0, 0.46);

  position: relative;
  overflow: hidden;
  color: var(--tfnl-text);
  background:
    radial-gradient(circle at 14% 0%, rgba(0, 255, 208, 0.17), transparent 26rem),
    radial-gradient(circle at 86% 10%, rgba(255, 212, 92, 0.12), transparent 25rem),
    linear-gradient(180deg, #071017 0%, #05070b 100%);
  border: 2px solid rgba(255, 212, 92, 0.42);
  border-radius: 22px;
  padding: 18px;
  box-shadow: var(--tfnl-shadow), inset 0 0 0 1px rgba(255,255,255,.025);
  font-family: 'Inter', Arial, Helvetica, sans-serif;
}

.tfnl-overall-ranking-app,
.tfnl-overall-ranking-app * {
  box-sizing: border-box;
}

.tfnl-overall-ranking-app::before {
  content: "▲";
  position: absolute;
  top: 12px;
  right: 24px;
  z-index: 0;
  font-family: 'Press Start 2P', monospace;
  font-size: 92px;
  line-height: 1;
  color: rgba(255, 212, 92, 0.055);
  text-shadow: 0 0 28px rgba(255, 212, 92, 0.18);
  pointer-events: none;
}

.tfnl-top-nav,
.tfnl-ranking-hero,
.tfnl-controls,
.tfnl-summary,
.tfnl-mode-overview,
.tfnl-ranking-table-wrap {
  position: relative;
  z-index: 1;
}

.tfnl-top-nav {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  align-items: center;
  justify-content: center;
  margin: 0 0 14px;
  padding: 10px;
  background: rgba(5, 9, 13, 0.82);
  border: 1px solid var(--tfnl-border-soft);
  border-radius: 16px;
}

.tfnl-top-nav a {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-height: 34px;
  padding: 8px 11px;
  color: var(--tfnl-muted) !important;
  text-decoration: none !important;
  border: 1px solid rgba(255, 255, 255, 0.07);
  border-radius: 999px;
  background: rgba(9, 15, 22, 0.86);
  font-size: 12px;
  font-weight: 800;
  line-height: 1.15;
  transition: border-color .14s ease, color .14s ease, background .14s ease, transform .14s ease;
}

.tfnl-top-nav a:hover,
.tfnl-top-nav a.is-active {
  color: var(--tfnl-green) !important;
  border-color: rgba(0, 255, 208, 0.46);
  background: rgba(0, 255, 208, 0.08);
  transform: translateY(-1px);
}

.tfnl-ranking-hero {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 18px;
  align-items: stretch;
  background:
    linear-gradient(135deg, rgba(16, 28, 39, 0.96), rgba(5, 9, 13, 0.94));
  border: 1px solid var(--tfnl-border);
  border-radius: 18px;
  padding: 20px;
  margin-bottom: 14px;
  box-shadow: inset 0 0 0 1px rgba(255,255,255,.025);
}

.tfnl-kicker {
  color: var(--tfnl-green);
  font-family: 'Press Start 2P', monospace;
  font-size: 9px;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  margin-bottom: 10px;
  line-height: 1.5;
}

.tfnl-ranking-hero h1 {
  margin: 0 0 10px;
  color: #fff6c6;
  font-family: 'Press Start 2P', monospace;
  font-size: clamp(20px, 3.1vw, 34px);
  line-height: 1.35;
  text-shadow: 0 0 12px rgba(255, 212, 92, 0.22);
}

.tfnl-ranking-hero p {
  margin: 0;
  color: var(--tfnl-muted);
  max-width: 780px;
  line-height: 1.55;
  font-size: 14px;
}

.tfnl-hero-stats {
  display: grid;
  grid-template-columns: repeat(3, minmax(92px, 1fr));
  gap: 8px;
  min-width: 300px;
}

.tfnl-stat-card {
  display: flex;
  flex-direction: column;
  justify-content: center;
  background: rgba(5, 9, 13, 0.84);
  border: 1px solid var(--tfnl-border-soft);
  border-radius: 15px;
  padding: 12px 10px;
  text-align: center;
}

.tfnl-stat-card span {
  display: block;
  color: var(--tfnl-gold);
  font-size: 24px;
  font-weight: 900;
  line-height: 1;
}

.tfnl-stat-card small {
  margin-top: 6px;
  color: var(--tfnl-muted);
  font-size: 10px;
  font-weight: 900;
  text-transform: uppercase;
  letter-spacing: .06em;
}

.tfnl-controls,
.tfnl-summary,
.tfnl-mode-overview,
.tfnl-ranking-table-wrap {
  background: var(--tfnl-panel);
  border: 1px solid var(--tfnl-border-soft);
  border-radius: 16px;
  padding: 14px;
  margin-bottom: 14px;
}

.tfnl-tabs {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 12px;
}

.tfnl-tab {
  appearance: none;
  border: 1px solid var(--tfnl-border-soft);
  background: rgba(5, 9, 13, 0.88);
  color: var(--tfnl-text);
  border-radius: 999px;
  padding: 9px 14px;
  cursor: pointer;
  font-weight: 900;
  font-size: 13px;
  transition: transform .12s ease, border-color .12s ease, background .12s ease, color .12s ease;
}

.tfnl-tab:hover,
.tfnl-tab.is-active {
  transform: translateY(-1px);
  background: rgba(0, 255, 208, 0.09);
  border-color: rgba(0, 255, 208, 0.48);
  color: var(--tfnl-green);
}

.tfnl-control-grid {
  display: grid;
  grid-template-columns: minmax(180px, 250px) minmax(130px, 170px) minmax(220px, 1fr);
  gap: 10px;
}

.tfnl-control-grid label {
  display: block;
  color: var(--tfnl-muted);
  font-size: 10px;
  font-weight: 900;
  margin-bottom: 6px;
  text-transform: uppercase;
  letter-spacing: 0.08em;
}

.tfnl-select,
.tfnl-input {
  width: 100%;
  min-height: 38px;
  background: rgba(5, 9, 13, 0.9);
  color: var(--tfnl-text);
  border: 1px solid var(--tfnl-border-soft);
  border-radius: 11px;
  padding: 9px 11px;
  outline: none;
  font: inherit;
  font-size: 13px;
}

.tfnl-select:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}

.tfnl-select:focus,
.tfnl-input:focus {
  border-color: var(--tfnl-green);
  box-shadow: 0 0 0 3px rgba(0, 255, 208, 0.1);
}

.tfnl-summary {
  display: flex;
  justify-content: space-between;
  gap: 10px;
  flex-wrap: wrap;
  color: var(--tfnl-muted);
  font-size: 13px;
}

.tfnl-summary strong {
  color: var(--tfnl-green);
}

.tfnl-mode-overview {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(170px, 1fr));
  gap: 9px;
}

.tfnl-mode-card {
  border: 1px solid var(--tfnl-border-soft);
  background: rgba(5, 9, 13, 0.82);
  color: var(--tfnl-text);
  border-radius: 14px;
  padding: 12px;
  cursor: pointer;
  text-align: left;
  transition: border-color .14s ease, box-shadow .14s ease, transform .14s ease;
}

.tfnl-mode-card:hover,
.tfnl-mode-card.is-active {
  transform: translateY(-1px);
  border-color: rgba(0, 255, 208, 0.48);
  box-shadow: 0 0 0 2px rgba(0, 255, 208, 0.1);
}

.tfnl-mode-card strong {
  display: block;
  color: #fff6c6;
  margin-bottom: 7px;
  font-weight: 900;
}

.tfnl-mode-card span {
  color: var(--tfnl-gold);
  font-weight: 900;
  font-size: 13px;
}

.tfnl-ranking-table-wrap {
  overflow-x: auto;
  -webkit-overflow-scrolling: touch;
}

.tfnl-ranking-table {
  width: 100%;
  border-collapse: separate;
  border-spacing: 0;
  min-width: 660px;
  font-size: 13px;
}

.tfnl-ranking-table th,
.tfnl-ranking-table td {
  padding: 9px 8px;
  border-bottom: 1px solid rgba(118, 255, 209, 0.12);
  text-align: right;
  white-space: nowrap;
}

.tfnl-ranking-table th {
  position: sticky;
  top: 0;
  z-index: 2;
  background: #0b1118;
  color: var(--tfnl-gold);
  font-size: 10px;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  cursor: pointer;
  user-select: none;
}

.tfnl-ranking-table th:hover {
  color: var(--tfnl-green);
}

.tfnl-ranking-table th:nth-child(1),
.tfnl-ranking-table td:nth-child(1) {
  text-align: center;
  width: 48px;
}

.tfnl-ranking-table th:nth-child(2),
.tfnl-ranking-table td:nth-child(2) {
  text-align: left;
  min-width: 170px;
}

.tfnl-ranking-table td {
  color: var(--tfnl-text);
  font-weight: 800;
  background: rgba(7, 13, 19, 0.68);
}

.tfnl-ranking-table tbody tr:nth-child(even) td {
  background: rgba(13, 22, 30, 0.72);
}

.tfnl-ranking-table tbody tr:hover td {
  background: rgba(0, 255, 208, 0.07);
}

.tfnl-rank {
  color: var(--tfnl-gold);
  font-weight: 900;
}

.tfnl-player {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 150px;
}

.tfnl-medal {
  display: inline-flex;
  justify-content: center;
  align-items: center;
  flex: 0 0 auto;
  width: 24px;
  height: 24px;
  border-radius: 999px;
  background: rgba(255, 212, 92, 0.11);
  border: 1px solid rgba(255, 212, 92, 0.32);
  color: var(--tfnl-gold);
  font-size: 12px;
  font-weight: 900;
}

.tfnl-elo {
  color: var(--tfnl-green);
  font-size: 15px;
  font-weight: 900;
}

.tfnl-winrate {
  color: var(--tfnl-blue);
}

.tfnl-empty,
.tfnl-error {
  color: var(--tfnl-muted);
  border: 1px dashed var(--tfnl-border-soft);
  border-radius: 14px;
  padding: 16px;
  text-align: center;
}

.tfnl-error {
  color: var(--tfnl-red);
  border-color: rgba(255, 93, 115, 0.35);
}

@media (max-width: 900px) {
  .tfnl-ranking-hero {
    grid-template-columns: 1fr;
  }

  .tfnl-hero-stats {
    width: 100%;
    min-width: 0;
    grid-template-columns: repeat(3, 1fr);
  }

  .tfnl-control-grid {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 560px) {
  .tfnl-overall-ranking-app {
    padding: 12px;
    border-radius: 18px;
  }

  .tfnl-top-nav {
    justify-content: flex-start;
    overflow-x: auto;
    flex-wrap: nowrap;
  }

  .tfnl-top-nav a {
    flex: 0 0 auto;
    font-size: 11px;
  }

  .tfnl-ranking-hero,
  .tfnl-controls,
  .tfnl-summary,
  .tfnl-mode-overview,
  .tfnl-ranking-table-wrap {
    padding: 12px;
  }

  .tfnl-ranking-hero h1 {
    font-size: 18px;
  }

  .tfnl-hero-stats {
    grid-template-columns: 1fr;
  }

  .tfnl-ranking-table {
    min-width: 610px;
    font-size: 12px;
  }

  .tfnl-ranking-table th,
  .tfnl-ranking-table td {
    padding: 8px 7px;
  }
}
</style>

<script>
(function () {
  "use strict";

  const CONFIG = {
    apiUrl: "https://tfl-discord-api.onrender.com/api/tfnl-overall-ranking"
  };

  const SCOPE_ALLTIME_OVERALL = "alltime_overall";
  const SCOPE_ALLTIME_MODE = "alltime_mode";

  const state = {
    allRows: [],
    filteredRows: [],
    meta: {},
    scopeView: "overall",
    selectedMode: "ALL",
    minGames: 0,
    search: "",
    sortKey: "elo",
    sortDirection: "desc"
  };

  const el = {
    totalPlayers: document.getElementById("tfnl-total-players"),
    totalGames: document.getElementById("tfnl-total-games"),
    totalModes: document.getElementById("tfnl-total-modes"),
    visiblePlayers: document.getElementById("tfnl-visible-players"),
    currentView: document.getElementById("tfnl-current-view"),
    lastUpdate: document.getElementById("tfnl-last-update"),
    modeSelect: document.getElementById("tfnl-mode-select"),
    minGames: document.getElementById("tfnl-min-games"),
    search: document.getElementById("tfnl-search"),
    modeOverview: document.getElementById("tfnl-mode-overview"),
    rankingBody: document.getElementById("tfnl-ranking-body")
  };

  function escapeHtml(value) {
    return String(value || "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function normalize(value) {
    return String(value || "").trim();
  }

  function num(value) {
    const parsed = Number(String(value || "0").replace(",", "."));
    return Number.isFinite(parsed) ? parsed : 0;
  }

  function formatDateTime(date) {
    return String(date.getDate()).padStart(2, "0") + "." +
      String(date.getMonth() + 1).padStart(2, "0") + "." +
      date.getFullYear() + " " +
      String(date.getHours()).padStart(2, "0") + ":" +
      String(date.getMinutes()).padStart(2, "0") + " Uhr";
  }

  function normalizeScope(value) {
    const raw = normalize(value).toLowerCase();

    if (raw === "alltime_overall" || raw === "scope_alltime_overall") {
      return SCOPE_ALLTIME_OVERALL;
    }

    if (raw === "alltime_mode" || raw === "scope_alltime_mode") {
      return SCOPE_ALLTIME_MODE;
    }

    if (raw.includes("alltime") && raw.includes("mode")) {
      return SCOPE_ALLTIME_MODE;
    }

    if (raw.includes("alltime")) {
      return SCOPE_ALLTIME_OVERALL;
    }

    return raw;
  }

  function rowToRanking(row, index) {
    return {
      player_id: normalize(row.player_id || row["Player ID"]),
      player_name: normalize(row.player_name || row["Player Name"]) || "Unbekannt",
      season: normalize(row.season || row["Season"]) || "ALL_TIME",
      mode: normalize(row.mode || row["Mode"]) || "ALL",
      scope: normalizeScope(row.scope || row["Scope"]),
      elo: num(row.elo || row["Elo"]),
      wins: num(row.wins || row["Wins"]),
      draws: num(row.draws || row["Draws"]),
      lose: num(row.lose || row["Lose"]),
      games: num(row.games || row["Games"]),
      winrate: num(row.winrate || row["Winrate"]),
      updated_at: normalize(row.updated_at || row["Updated At"]),
      match_count_total: num(row.match_count_total || row["Match Count Total"]),
      match_count_mode: num(row.match_count_mode || row["Match Count Mode"]),
      index: index
    };
  }

  async function loadRanking() {
    try {
      const response = await fetch(CONFIG.apiUrl, {
        cache: "no-store"
      });

      if (!response.ok) {
        throw new Error("HTTP " + response.status);
      }

      const json = await response.json();
      const rows = Array.isArray(json.items) ? json.items : [];

      state.meta = json && typeof json.meta === "object" && json.meta ? json.meta : {};

      state.allRows = rows
        .map(rowToRanking)
        .filter(function (row) {
          return row.player_name && row.elo > 0;
        });

      fillModeSelect();
      renderStats();
      applyFilters();

      el.lastUpdate.textContent = "Stand: " + formatDateTime(new Date());
    } catch (error) {
      el.rankingBody.innerHTML =
        '<tr><td colspan="8" class="tfnl-error">Overall Ranking konnte nicht über die TFNL-API geladen werden. Fehler: ' +
        escapeHtml(error.message) +
        '</td></tr>';
    }
  }

  function fillModeSelect() {
    const modes = Array.from(new Set(state.allRows
      .filter(function (row) {
        return row.scope === SCOPE_ALLTIME_MODE && row.mode && row.mode !== "ALL";
      })
      .map(function (row) {
        return row.mode;
      })))
      .sort(function (a, b) {
        return a.localeCompare(b, "de");
      });

    el.modeSelect.innerHTML =
      '<option value="ALL">Alle Modis</option>' +
      modes.map(function (mode) {
        return '<option value="' + escapeHtml(mode) + '">' + escapeHtml(mode) + '</option>';
      }).join("");
  }

  function renderStats() {
    const overallRows = state.allRows.filter(function (row) {
      return row.scope === SCOPE_ALLTIME_OVERALL;
    });

    const players = new Set(overallRows.map(function (row) {
      return row.player_id || row.player_name;
    }));

    const playerGames = overallRows.reduce(function (sum, row) {
      return sum + row.games;
    }, 0);

    const apiMatchCount = num(state.meta.alltime_match_count);

    const rowMatchCount = overallRows.reduce(function (max, row) {
      return Math.max(max, num(row.match_count_total));
    }, 0);

    const games = apiMatchCount || rowMatchCount || Math.floor(playerGames / 2);

    const modes = new Set(state.allRows
      .filter(function (row) {
        return row.scope === SCOPE_ALLTIME_MODE && row.mode && row.mode !== "ALL";
      })
      .map(function (row) {
        return row.mode;
      }));

    el.totalPlayers.textContent = String(players.size);
    el.totalGames.textContent = String(games);
    el.totalModes.textContent = String(modes.size);
  }

  function applyFilters() {
    const wantedScope = state.scopeView === "overall"
      ? SCOPE_ALLTIME_OVERALL
      : SCOPE_ALLTIME_MODE;

    const search = state.search.toLowerCase();

    state.filteredRows = state.allRows.filter(function (row) {
      if (row.scope !== wantedScope) return false;

      if (state.scopeView === "overall") {
        if (row.mode !== "ALL") return false;
      } else {
        if (state.selectedMode !== "ALL" && row.mode !== state.selectedMode) return false;
        if (row.mode === "ALL") return false;
      }

      if (row.games < state.minGames) return false;

      if (search) {
        const searchText = [
          row.player_name,
          row.player_id,
          row.mode,
          row.season
        ].join(" ").toLowerCase();

        if (!searchText.includes(search)) return false;
      }

      return true;
    });

    sortRows();
    renderCurrentView();
    renderModeOverview();
    renderTable();
  }

  function sortRows() {
    state.filteredRows.sort(function (a, b) {
      let valueA = a[state.sortKey];
      let valueB = b[state.sortKey];

      if (typeof valueA === "string") {
        valueA = valueA.toLowerCase();
      }

      if (typeof valueB === "string") {
        valueB = valueB.toLowerCase();
      }

      if (valueA < valueB) return state.sortDirection === "asc" ? -1 : 1;
      if (valueA > valueB) return state.sortDirection === "asc" ? 1 : -1;

      return b.elo - a.elo;
    });
  }

  function renderCurrentView() {
    el.visiblePlayers.textContent = String(state.filteredRows.length);

    if (state.scopeView === "overall") {
      el.currentView.textContent = "Overall Gesamt";
    } else if (state.selectedMode === "ALL") {
      el.currentView.textContent = "Overall nach Modis";
    } else {
      el.currentView.textContent = "Overall Modus: " + state.selectedMode;
    }
  }

  function renderModeOverview() {
    if (state.scopeView !== "mode") {
      el.modeOverview.style.display = "none";
      return;
    }

    el.modeOverview.style.display = "grid";

    const modeRows = state.allRows.filter(function (row) {
      return row.scope === SCOPE_ALLTIME_MODE && row.mode && row.mode !== "ALL";
    });

    const grouped = {};

    modeRows.forEach(function (row) {
      if (!grouped[row.mode]) {
        grouped[row.mode] = {
          mode: row.mode,
          players: 0,
          games: 0,
          topElo: 0,
          topPlayer: ""
        };
      }

      grouped[row.mode].players++;
      grouped[row.mode].games += row.games;

      if (row.elo > grouped[row.mode].topElo) {
        grouped[row.mode].topElo = row.elo;
        grouped[row.mode].topPlayer = row.player_name;
      }
    });

    const modes = Object.values(grouped).sort(function (a, b) {
      return a.mode.localeCompare(b.mode, "de");
    });

    if (!modes.length) {
      el.modeOverview.innerHTML = '<div class="tfnl-empty">Keine Modus-Rankings vorhanden.</div>';
      return;
    }

    el.modeOverview.innerHTML = modes.map(function (item) {
      return (
        '<button type="button" class="tfnl-mode-card' +
          (state.selectedMode === item.mode ? ' is-active' : '') +
          '" data-mode-card="' + escapeHtml(item.mode) + '">' +
          '<strong>' + escapeHtml(item.mode) + '</strong>' +
          '<span>' + item.players + ' Runner · Top ELO ' + item.topElo.toFixed(1) + '</span>' +
          '<div style="color: var(--tfnl-muted); margin-top: 6px; font-size: 12px;">' +
            escapeHtml(item.topPlayer || "-") +
          '</div>' +
        '</button>'
      );
    }).join("");

    el.modeOverview.querySelectorAll("[data-mode-card]").forEach(function (button) {
      button.addEventListener("click", function () {
        state.selectedMode = button.getAttribute("data-mode-card") || "ALL";
        el.modeSelect.value = state.selectedMode;
        applyFilters();
      });
    });
  }

  function renderTable() {
    if (!state.filteredRows.length) {
      el.rankingBody.innerHTML =
        '<tr><td colspan="8" class="tfnl-empty">Keine Runner in der aktuellen Auswahl.</td></tr>';
      return;
    }

    el.rankingBody.innerHTML = state.filteredRows.map(function (row, index) {
      const rank = index + 1;
      let medal = String(rank);

      if (rank === 1) medal = "1";
      if (rank === 2) medal = "2";
      if (rank === 3) medal = "3";

      return (
        '<tr>' +
          '<td><span class="tfnl-rank">' + rank + '</span></td>' +
          '<td>' +
            '<div class="tfnl-player">' +
              '<span class="tfnl-medal">' + escapeHtml(medal) + '</span>' +
              '<span>' + escapeHtml(row.player_name) + '</span>' +
            '</div>' +
          '</td>' +
          '<td>' + row.games + '</td>' +
          '<td>' + row.wins + '</td>' +
          '<td>' + row.draws + '</td>' +
          '<td>' + row.lose + '</td>' +
          '<td class="tfnl-winrate">' + row.winrate.toFixed(1) + '%</td>' +
          '<td class="tfnl-elo">' + row.elo.toFixed(1) + '</td>' +
        '</tr>'
      );
    }).join("");
  }

  document.querySelectorAll("#tfnl-overall-ranking-app .tfnl-tab").forEach(function (button) {
    button.addEventListener("click", function () {
      document.querySelectorAll("#tfnl-overall-ranking-app .tfnl-tab").forEach(function (tab) {
        tab.classList.remove("is-active");
      });

      button.classList.add("is-active");

      state.scopeView = button.getAttribute("data-scope") || "overall";

      if (state.scopeView === "overall") {
        state.selectedMode = "ALL";
        el.modeSelect.value = "ALL";
        el.modeSelect.disabled = true;
      } else {
        el.modeSelect.disabled = false;
      }

      applyFilters();
    });
  });

  el.modeSelect.addEventListener("change", function () {
    state.selectedMode = el.modeSelect.value;
    applyFilters();
  });

  el.minGames.addEventListener("change", function () {
    state.minGames = num(el.minGames.value);
    applyFilters();
  });

  el.search.addEventListener("input", function () {
    state.search = el.search.value.trim();
    applyFilters();
  });

  document.querySelectorAll("#tfnl-overall-ranking-app th[data-sort]").forEach(function (th) {
    th.addEventListener("click", function () {
      const key = th.getAttribute("data-sort");

      if (state.sortKey === key) {
        state.sortDirection = state.sortDirection === "asc" ? "desc" : "asc";
      } else {
        state.sortKey = key;
        state.sortDirection = key === "player_name" ? "asc" : "desc";
      }

      applyFilters();
    });
  });

  loadRanking();
})();
</script>
