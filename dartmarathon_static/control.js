(() => {
  let ws = null;
  let reconnectTimer = null;
  let connectionAlarmTimer = null;
  let lastState = null;
  let editingMatchId = null;
  let matchSavePending = false;
  let activeTab = "matches";
  let clockBaseState = null;
  let clockBaseMs = 0;

  const $ = (id) => document.getElementById(id);
  const all = (selector) => [...document.querySelectorAll(selector)];

  function showToast(message, type = "info") {
    const toast = $("toast");
    if (!toast) return;

    toast.textContent = message;
    toast.dataset.type = type;
    toast.classList.remove("hidden");

    clearTimeout(toast._timer);

    toast._timer = setTimeout(() => {
      toast.classList.add("hidden");
    }, 3500);
  }

  function hideConnectionAlarm() {
    clearTimeout(connectionAlarmTimer);
    connectionAlarmTimer = null;

    const alarm = $("connectionAlarm");
    if (alarm) alarm.classList.add("hidden");
  }

  function scheduleConnectionAlarm() {
    clearTimeout(connectionAlarmTimer);

    connectionAlarmTimer = setTimeout(() => {
      if (!ws || ws.readyState !== WebSocket.OPEN) {
        const alarm = $("connectionAlarm");
        if (alarm) alarm.classList.remove("hidden");
      }
    }, 3000);
  }

  function connect() {
    clearTimeout(reconnectTimer);
    scheduleConnectionAlarm();

    const proto = location.protocol === "https:" ? "wss" : "ws";

    ws = new WebSocket(
      `${proto}://${location.host}/dartmarathon/ws`
    );

    ws.onopen = () => {
      $("connectionDot").className = "dot online";
      $("connectionText").textContent = "live verbunden";
      hideConnectionAlarm();
    };

    ws.onclose = () => {
      $("connectionDot").className = "dot offline";
      $("connectionText").textContent = "Verbindung getrennt";
      scheduleConnectionAlarm();

      clearTimeout(reconnectTimer);
      reconnectTimer = setTimeout(connect, 1500);
    };

    ws.onerror = () => {
      try {
        ws.close();
      } catch (_) {
        // nichts zu tun
      }
    };

    ws.onmessage = (event) => {
      let message;

      try {
        message = JSON.parse(event.data);
      } catch (_) {
        return;
      }

      if (message.type === "state") {
        render(message.data);
        return;
      }

      if (message.type === "error") {
        matchSavePending = false;
        syncSaveButton();
        showToast(message.message || "Aktion fehlgeschlagen.", "error");
        return;
      }

      if (message.type === "match_saved") {
        matchSavePending = false;
        showToast(
          message.message || `Match #${message.id} gespeichert.`,
          "success"
        );
        clearMatchForm();
        activateTab("matches");
        syncSaveButton();
        return;
      }

      if (message.type === "match_deleted") {
        showToast(
          message.message || `Match #${message.id} gelöscht.`,
          "success"
        );

        if (editingMatchId === Number(message.id)) {
          clearMatchForm();
        }

        return;
      }

      if (message.type === "popup_sent") {
        const labels = {
          foltershop: "Foltershop",
          malteser: "Malteser",
          koala: "KoalaDarts",
          recent_matches: "Letzte Spiele",
          specials: "Specials",
          stats: "Event-Kennzahlen",
        };

        showToast(
          `${labels[message.kind] || "Einblendung"} wird 20 Sekunden angezeigt.`,
          "success"
        );
        return;
      }

      if (message.type === "full_reset_done") {
        clearMatchForm();
        activateTab("matches");
        showToast("Gesamtes Event zurückgesetzt.", "success");
      }
    };
  }

  function send(payload) {
    if (!ws || ws.readyState !== WebSocket.OPEN) {
      scheduleConnectionAlarm();
      showToast("Keine Verbindung zum Server.", "error");
      return false;
    }

    ws.send(JSON.stringify(payload));
    return true;
  }

  function parseList(
    value,
    minimum,
    maximum = null,
    label = "Wert"
  ) {
    const text = String(value || "").trim();

    if (!text) return [];

    const parts = text
      .split(/[\s,;]+/)
      .filter(Boolean);

    const values = parts.map((part) => Number(part));

    if (
      values.some(
        (value) => !Number.isInteger(value)
      )
    ) {
      throw new Error(
        `${label}: Bitte nur ganze Zahlen eingeben.`
      );
    }

    if (
      values.some(
        (value) =>
          value < minimum
          || (
            maximum !== null
            && value > maximum
          )
      )
    ) {
      const range = maximum === null
        ? `ab ${minimum}`
        : `${minimum} bis ${maximum}`;

      throw new Error(
        `${label}: Erlaubt sind nur Werte ${range}.`
      );
    }

    return values;
  }

  function countValue(id) {
    const input = $(id);
    const value = Number(input.value || 0);

    if (
      !Number.isInteger(value)
      || value < 0
      || value > 999
    ) {
      throw new Error(
        "Special-Anzahlen müssen ganze Zahlen ab 0 sein."
      );
    }

    return value;
  }

  function readSpecials(prefix) {
    return {
      hf: parseList(
        $(prefix + "HF").value,
        100,
        null,
        "HF"
      ),
      bf: parseList(
        $(prefix + "BF").value,
        50,
        null,
        "BF"
      ),
      "180": countValue(prefix + "180"),
      "177": countValue(prefix + "177"),
      "174": countValue(prefix + "174"),
      "171": countValue(prefix + "171"),
      ld: parseList(
        $(prefix + "LD").value,
        9,
        18,
        "LD"
      ),
    };
  }

  function specialCount(detail) {
    return (
      (detail.hf?.length || 0)
      + (detail.bf?.length || 0)
      + (detail.ld?.length || 0)
      + Number(detail["180"] || 0)
      + Number(detail["177"] || 0)
      + Number(detail["174"] || 0)
      + Number(detail["171"] || 0)
    );
  }

  function readNonnegativeInt(id, label) {
    const value = Number($(id).value || 0);

    if (
      !Number.isInteger(value)
      || value < 0
      || value > 999
    ) {
      throw new Error(
        `${label}: Bitte eine ganze Zahl ab 0 eingeben.`
      );
    }

    return value;
  }

  function readMatchForm() {
    const mode = $("matchMode").value;

    const result = mode === "set"
      ? {
          tzmarty_legs: readNonnegativeInt(
            "setLegsTzmarty",
            "Tzmarty Legs"
          ),
          korsar_legs: readNonnegativeInt(
            "setLegsKorsar",
            "Korsar Legs"
          ),
          tzmarty_sets: readNonnegativeInt(
            "setsTzmarty",
            "Tzmarty Sets"
          ),
          korsar_sets: readNonnegativeInt(
            "setsKorsar",
            "Korsar Sets"
          ),
        }
      : {
          tzmarty_legs: readNonnegativeInt(
            "resultTzmarty",
            "Tzmarty"
          ),
          korsar_legs: readNonnegativeInt(
            "resultKorsar",
            "Korsar"
          ),
          tzmarty_sets: 0,
          korsar_sets: 0,
        };

    if (
      result.tzmarty_legs
      + result.korsar_legs
      <= 0
    ) {
      throw new Error(
        "Bitte ein Spielergebnis mit mindestens einem Leg eintragen."
      );
    }

    if (
      mode === "set"
      && (
        result.tzmarty_sets
        + result.korsar_sets
        <= 0
      )
    ) {
      throw new Error(
        "Beim Setmodus bitte auch das Settergebnis eintragen."
      );
    }

    const specials = {
      tzmarty: readSpecials("tz"),
      korsar: readSpecials("ko"),
    };

    return {
      mode,
      result,
      specials,
    };
  }

  function formatPause(seconds) {
    const value = Math.max(
      0,
      Math.round(
        Number(seconds || 0)
      )
    );

    const minutes = Math.floor(
      value / 60
    );

    const secs = value % 60;

    return (
      `${String(minutes).padStart(2, "0")}:`
      + `${String(secs).padStart(2, "0")}`
    );
  }

  function safeSpecialsFromForm(prefix) {
    try {
      return readSpecials(prefix);
    } catch (_) {
      return null;
    }
  }

  function updateMatchPreview() {
    const tzSpecials = safeSpecialsFromForm("tz");
    const koSpecials = safeSpecialsFromForm("ko");

    $("tzFormSpecialCount").textContent = tzSpecials
      ? specialCount(tzSpecials)
      : "–";

    $("koFormSpecialCount").textContent = koSpecials
      ? specialCount(koSpecials)
      : "–";

    try {
      const data = readMatchForm();

      const legs = (
        data.result.tzmarty_legs
        + data.result.korsar_legs
      );

      const specials = (
        specialCount(data.specials.tzmarty)
        + specialCount(data.specials.korsar)
      );

      const pauseSeconds = (
        legs * 30
        + specials * 60
      );

      const preview = $("matchPreview");

      preview.textContent = (
        `${legs} Legs · ${specials} Specials · `
        + `+${formatPause(pauseSeconds)} Pausenguthaben`
      );

      preview.classList.remove(
        "preview-error"
      );
    } catch (error) {
      const preview = $("matchPreview");

      preview.textContent = (
        error?.message
        || "Eingaben prüfen"
      );

      preview.classList.add(
        "preview-error"
      );
    }
  }

  function toggleSetMode() {
    const isSet = (
      $("matchMode").value === "set"
    );

    $("normalResult").classList.toggle(
      "hidden",
      isSet
    );

    $("setResult").classList.toggle(
      "hidden",
      !isSet
    );

    updateMatchPreview();
  }

  function fillSpecials(prefix, detail) {
    const safe = detail || {};

    $(prefix + "HF").value = (
      safe.hf || []
    ).join(", ");

    $(prefix + "BF").value = (
      safe.bf || []
    ).join(", ");

    $(prefix + "LD").value = (
      safe.ld || []
    ).join(", ");

    for (const key of [
      "180",
      "177",
      "174",
      "171",
    ]) {
      $(prefix + key).value = Number(
        safe[key] || 0
      );
    }
  }

  function clearMatchForm() {
    editingMatchId = null;
    matchSavePending = false;

    $("matchMode").value = "sido";

    for (const id of [
      "resultTzmarty",
      "resultKorsar",
      "setsTzmarty",
      "setsKorsar",
      "setLegsTzmarty",
      "setLegsKorsar",
      "tz180",
      "tz177",
      "tz174",
      "tz171",
      "ko180",
      "ko177",
      "ko174",
      "ko171",
    ]) {
      $(id).value = 0;
    }

    for (const id of [
      "tzHF",
      "tzBF",
      "tzLD",
      "koHF",
      "koBF",
      "koLD",
    ]) {
      $(id).value = "";
    }

    $("editHint").textContent = (
      "Neues Match eintragen"
    );

    $("cancelEdit").classList.add(
      "hidden"
    );

    toggleSetMode();
    syncSaveButton();
    updateMatchPreview();
  }

  function editMatch(id) {
    if (!lastState?.matches) return;

    const match = lastState.matches.find(
      (item) => Number(item.id) === Number(id)
    );

    if (!match) {
      showToast(
        "Match konnte nicht geladen werden.",
        "error"
      );
      return;
    }

    editingMatchId = Number(match.id);

    $("matchMode").value = match.mode;

    $("resultTzmarty").value = Number(
      match.result?.tzmarty_legs || 0
    );

    $("resultKorsar").value = Number(
      match.result?.korsar_legs || 0
    );

    $("setsTzmarty").value = Number(
      match.result?.tzmarty_sets || 0
    );

    $("setsKorsar").value = Number(
      match.result?.korsar_sets || 0
    );

    $("setLegsTzmarty").value = Number(
      match.result?.tzmarty_legs || 0
    );

    $("setLegsKorsar").value = Number(
      match.result?.korsar_legs || 0
    );

    fillSpecials(
      "tz",
      match.specials?.tzmarty
    );

    fillSpecials(
      "ko",
      match.specials?.korsar
    );

    $("editHint").textContent = (
      `Match #${match.id} bearbeiten`
    );

    $("cancelEdit").classList.remove(
      "hidden"
    );

    toggleSetMode();
    updateMatchPreview();
    syncSaveButton();

    window.scrollTo({
      top: 0,
      behavior: "smooth",
    });
  }

  function deleteMatch(id) {
    const confirmed = confirm(
      `Match #${id} wirklich löschen?\n\n`
      + "Legs, Specials und die tatsächlich "
      + "gutgeschriebene Pausenzeit werden korrigiert."
    );

    if (!confirmed) return;

    send({
      type: "match_delete",
      id: Number(id),
    });
  }

  function compactValueList(values) {
    const source = Array.isArray(values) ? values : [];
    const counts = new Map();
    const order = [];

    for (const raw of source) {
      const value = Number(raw);
      if (!Number.isFinite(value)) continue;

      if (!counts.has(value)) {
        counts.set(value, 0);
        order.push(value);
      }

      counts.set(
        value,
        counts.get(value) + 1
      );
    }

    return order.map((value) => {
      const count = counts.get(value);
      return count > 1
        ? `${count}x${value}`
        : String(value);
    }).join(", ");
  }

  function formatSpecialSummary(detail) {
    const safe = detail || {};
    const parts = [];

    if (safe.hf?.length) {
      parts.push(
        `HF ${compactValueList(safe.hf)}`
      );
    }

    if (safe.bf?.length) {
      parts.push(
        `BF ${compactValueList(safe.bf)}`
      );
    }

    for (const key of [
      "180",
      "177",
      "174",
      "171",
    ]) {
      if (Number(safe[key] || 0) > 0) {
        parts.push(
          `${key} ×${safe[key]}`
        );
      }
    }

    if (safe.ld?.length) {
      parts.push(
        `LD ${compactValueList(safe.ld)}`
      );
    }

    return parts.length
      ? parts.join(" · ")
      : "keine Specials";
  }

  function escapeHtml(value) {
    return String(
      value ?? ""
    ).replace(
      /[&<>'"]/g,
      (char) => ({
        "&": "&amp;",
        "<": "&lt;",
        ">": "&gt;",
        "'": "&#39;",
        '"': "&quot;",
      }[char])
    );
  }

  function renderMatches(matches) {
    const safeMatches = Array.isArray(matches)
      ? matches
      : [];

    $("matchCountBadge").textContent = (
      safeMatches.length
    );

    const container = $("matchHistory");

    if (!safeMatches.length) {
      container.innerHTML = (
        '<div class="empty-state">'
        + "Noch keine Matches gespeichert."
        + "</div>"
      );
      return;
    }

    container.innerHTML = safeMatches.map(
      (match) => (
        '<div class="match-history-row">'
        + `<div class="match-id">#${Number(match.id)}</div>`
        + `<div class="match-mode">${escapeHtml(match.mode_label)}</div>`
        + `<div class="match-result">${escapeHtml(match.result_text)}</div>`
        + `<div class="match-specials">${Number(match.special_total || 0)} Specials</div>`
        + `<div class="match-pause">+${formatPause(match.pause_credit_applied_seconds)} Pause</div>`
        + '<div class="row-actions">'
        + `<button class="mini-btn ghost" type="button" data-edit-match="${Number(match.id)}">BEARBEITEN</button>`
        + `<button class="mini-btn danger" type="button" data-delete-match="${Number(match.id)}">LÖSCHEN</button>`
        + "</div>"
        + "</div>"
      )
    ).join("");

    all("[data-edit-match]").forEach(
      (button) => {
        button.onclick = () => {
          editMatch(
            Number(
              button.dataset.editMatch
            )
          );
        };
      }
    );

    all("[data-delete-match]").forEach(
      (button) => {
        button.onclick = () => {
          deleteMatch(
            Number(
              button.dataset.deleteMatch
            )
          );
        };
      }
    );
  }

  function renderSpecialHistory(matches) {
    const safeMatches = Array.isArray(matches)
      ? matches
      : [];

    const entries = [];

    for (const match of safeMatches) {
      for (const player of [
        "tzmarty",
        "korsar",
      ]) {
        const count = Number(
          match.special_totals?.[player]
          || 0
        );

        if (count <= 0) continue;

        entries.push({
          matchId: Number(match.id),
          mode: match.mode_label,
          player,
          count,
          detail: match.specials?.[player] || {},
        });
      }
    }

    $("specialEntryBadge").textContent = (
      entries.length
    );

    const container = $("specialHistory");

    if (!entries.length) {
      container.innerHTML = (
        '<div class="empty-state">'
        + "Noch keine Specials gespeichert."
        + "</div>"
      );
      return;
    }

    container.innerHTML = entries.map(
      (entry) => (
        '<div class="special-history-row">'
        + `<div class="match-id">#${entry.matchId}</div>`
        + `<div>${escapeHtml(entry.mode)}</div>`
        + `<div class="player-name">${entry.player === "tzmarty" ? "Tzmarty" : "Korsar"} · ${entry.count}</div>`
        + `<div class="details">${escapeHtml(formatSpecialSummary(entry.detail))}</div>`
        + "</div>"
      )
    ).join("");
  }

  function setPauseColor(
    element,
    seconds
  ) {
    element.classList.remove(
      "pause-red",
      "pause-yellow",
      "pause-green"
    );

    if (seconds <= 300) {
      element.classList.add(
        "pause-red"
      );
    } else if (seconds <= 600) {
      element.classList.add(
        "pause-yellow"
      );
    } else {
      element.classList.add(
        "pause-green"
      );
    }
  }

  function renderActionHistory(history) {
    const entries = Array.isArray(history)
      ? [...history].reverse()
      : [];

    $("history").innerHTML = entries.length
      ? entries.map(
          (entry) => (
            '<div class="history-line">'
            + `<span>${escapeHtml(entry.time)}</span>`
            + `<b>${escapeHtml(entry.text)}</b>`
            + "</div>"
          )
        ).join("")
      : (
          '<div class="empty-state">'
          + "Noch keine Aktionen."
          + "</div>"
        );
  }

  function formatClock(seconds, withHours = false) {
    const value = Math.max(0, Math.floor(Number(seconds || 0)));
    const hours = Math.floor(value / 3600);
    const minutes = Math.floor((value % 3600) / 60);
    const secs = value % 60;
    if (withHours) {
      return `${String(hours).padStart(2, "0")}:${String(minutes).padStart(2, "0")}:${String(secs).padStart(2, "0")}`;
    }
    const totalMinutes = Math.floor(value / 60);
    return `${String(totalMinutes).padStart(2, "0")}:${String(secs).padStart(2, "0")}`;
  }

  function renderLocalClocks() {
    if (!clockBaseState) return;
    const elapsed = Math.max(0, (Date.now() - clockBaseMs) / 1000);
    const streamSeconds = Number(clockBaseState.stream_seconds || 0)
      + (clockBaseState.stream_running ? elapsed : 0);
    const pauseSeconds = Math.max(0, Number(clockBaseState.pause_seconds || 0)
      - (clockBaseState.pause_active ? elapsed : 0));

    $("streamTime").textContent = formatClock(streamSeconds, true);
    $("pauseTime").textContent = formatClock(pauseSeconds, false);
    setPauseColor($("pauseTime"), pauseSeconds);
  }

  function render(state) {
    if (!state) return;

    lastState = state;
    clockBaseState = state;
    clockBaseMs = Date.now();
    renderLocalClocks();

    if (state.event_ended) {
      $("pauseStatus").textContent = (
        "EVENT BEENDET"
      );
    } else if (state.pause_active) {
      $("pauseStatus").textContent = (
        "PAUSE LÄUFT"
      );
    } else if (state.pause_full) {
      $("pauseStatus").textContent = (
        "PAUSE VOLL"
      );
    } else {
      $("pauseStatus").textContent = (
        "PAUSE STEHT"
      );
    }

    $("endedBanner").classList.toggle(
      "hidden",
      !state.event_ended
    );

    $("pauseFullBanner").classList.toggle(
      "hidden",
      !state.pause_full
    );

    $("legsTzmarty").textContent = Number(
      state.legs?.tzmarty || 0
    );

    $("legsKorsar").textContent = Number(
      state.legs?.korsar || 0
    );

    $("specialsTzmarty").textContent = Number(
      state.player_special_totals?.tzmarty
      || 0
    );

    $("specialsKorsar").textContent = Number(
      state.player_special_totals?.korsar
      || 0
    );

    $("totalLegs").textContent = Number(
      state.total_legs || 0
    );

    $("totalSpecials").textContent = Number(
      state.total_specials || 0
    );

    $("statMatches").textContent = Number(
      state.match_count || 0
    );

    const tzmartyWins = Number(
      state.match_wins?.tzmarty || 0
    );

    const korsarWins = Number(
      state.match_wins?.korsar || 0
    );

    const draws = Number(
      state.match_draws || 0
    );

    $("statMatchBalance").textContent = (
      `${tzmartyWins} : ${korsarWins}`
      + (draws > 0 ? ` · ${draws} U` : "")
    );

    $("statAvgLegsMatch").textContent = Number(
      state.avg_legs_per_match || 0
    ).toLocaleString(
      "de-DE",
      {
        minimumFractionDigits: 1,
        maximumFractionDigits: 1,
      }
    );

    $("statAvgSpecialsMatch").textContent = Number(
      state.avg_specials_per_match || 0
    ).toLocaleString(
      "de-DE",
      {
        minimumFractionDigits: 1,
        maximumFractionDigits: 1,
      }
    );

    $("statSpecialsPerLeg").textContent = Number(
      state.specials_per_leg || 0
    ).toLocaleString(
      "de-DE",
      {
        minimumFractionDigits: 2,
        maximumFractionDigits: 2,
      }
    );

    $("statLegsPerHour").textContent = Number(
      state.legs_per_hour || 0
    ).toLocaleString(
      "de-DE",
      {
        minimumFractionDigits: 1,
        maximumFractionDigits: 1,
      }
    );

    $("statSpecialsPerHour").textContent = Number(
      state.specials_per_hour || 0
    ).toLocaleString(
      "de-DE",
      {
        minimumFractionDigits: 1,
        maximumFractionDigits: 1,
      }
    );

    $("statPauseUsed").textContent = (
      state.pause_used_display
      || "00:00:00"
    );

    $("ownDonations").textContent = Number(
      state.own_donations || 0
    ).toLocaleString(
      "de-DE",
      {
        minimumFractionDigits: 2,
        maximumFractionDigits: 2,
      }
    );

    renderMatches(
      state.matches
    );

    renderSpecialHistory(
      state.matches
    );

    renderActionHistory(
      state.history
    );

    $("streamStart").disabled = Boolean(
      state.stream_running
    );

    $("streamStop").disabled = !Boolean(
      state.stream_running
    );

    $("pauseStart").disabled = (
      Boolean(state.pause_active)
      || Number(state.pause_seconds || 0) <= 0
      || Boolean(state.event_ended)
    );

    $("pauseStop").disabled = !Boolean(
      state.pause_active
    );

    $("undoButton").disabled = !Boolean(
      state.can_undo
    );

    $("unlockEvent").disabled = !Boolean(
      state.event_ended
    );

    $("donationAdd").disabled = Boolean(
      state.event_ended
    );

    $("donationSubtract").disabled = Boolean(
      state.event_ended
    );

    all("[data-donation]").forEach(
      (button) => {
        button.disabled = Boolean(
          state.event_ended
        );
      }
    );

    all("[data-pause]").forEach(
      (button) => {
        const value = Number(
          button.dataset.pause
        );

        button.disabled = (
          (
            state.event_ended
            && value > 0
          )
          || (
            value > 0
            && state.pause_full
          )
          || (
            value < 0
            && Number(
              state.pause_seconds || 0
            ) <= 0
          )
        );
      }
    );

    syncSaveButton();
  }

  function syncSaveButton() {
    const button = $("saveMatch");

    const blocked = (
      Boolean(lastState?.event_ended)
      || matchSavePending
    );

    button.disabled = blocked;

    if (matchSavePending) {
      button.textContent = (
        "SPEICHERT…"
      );
    } else if (
      editingMatchId !== null
    ) {
      button.textContent = (
        "ÄNDERUNGEN SPEICHERN"
      );
    } else {
      button.textContent = (
        "MATCH SPEICHERN"
      );
    }
  }

  function activateTab(name) {
    const panel = $(`tab-${name}`);

    if (!panel) return;

    activeTab = name;

    all(".tab").forEach(
      (button) => {
        button.classList.toggle(
          "active",
          button.dataset.tab === name
        );
      }
    );

    all(".tab-panel").forEach(
      (item) => {
        item.classList.toggle(
          "active",
          item.id === `tab-${name}`
        );
      }
    );
  }

  async function toggleFullscreen() {
    try {
      if (!document.fullscreenElement) {
        await document.documentElement
          .requestFullscreen();
      } else {
        await document
          .exitFullscreen();
      }
    } catch (_) {
      showToast(
        "Vollbildmodus konnte nicht gestartet werden.",
        "error"
      );
    }
  }

  function updateFullscreenButton() {
    $("fullscreenButton").textContent = (
      document.fullscreenElement
        ? "VOLLBILD BEENDEN"
        : "VOLLBILD"
    );
  }

  function donationAmount(sign) {
    const input = $("donationAmount");

    const amount = Number(
      String(input.value)
        .replace(",", ".")
    );

    if (
      !Number.isFinite(amount)
      || amount <= 0
    ) {
      showToast(
        "Bitte einen gültigen Betrag eingeben.",
        "error"
      );
      return;
    }

    if (
      send({
        type: "donation_adjust",
        amount: sign * amount,
      })
    ) {
      input.value = "";
    }
  }

  // -------------------------------------------------------
  // Event-Bindings
  // -------------------------------------------------------

  $("matchMode").addEventListener(
    "change",
    toggleSetMode
  );

  all(
    ".match-card input, .match-card select"
  ).forEach(
    (element) => {
      element.addEventListener(
        "input",
        updateMatchPreview
      );

      element.addEventListener(
        "change",
        updateMatchPreview
      );
    }
  );

  $("saveMatch").onclick = () => {
    if (matchSavePending) return;

    try {
      const data = readMatchForm();

      matchSavePending = true;
      syncSaveButton();

      const sent = send({
        type: "match_save",
        id: editingMatchId,
        ...data,
      });

      if (!sent) {
        matchSavePending = false;
        syncSaveButton();
      }
    } catch (error) {
      matchSavePending = false;
      syncSaveButton();

      showToast(
        error?.message
        || "Bitte Eingaben prüfen.",
        "error"
      );
    }
  };

  $("cancelEdit").onclick = (
    clearMatchForm
  );

  $("streamStart").onclick = () => send({
    type: "stream_action",
    action: "start",
  });

  $("streamStop").onclick = () => send({
    type: "stream_action",
    action: "stop",
  });

  $("streamReset").onclick = () => {
    if (
      confirm(
        "Streamlaufzeit wirklich "
        + "auf 00:00:00 zurücksetzen?"
      )
    ) {
      send({
        type: "stream_action",
        action: "reset",
      });
    }
  };

  $("pauseStart").onclick = () => send({
    type: "pause_action",
    action: "start",
  });

  $("pauseStop").onclick = () => send({
    type: "pause_action",
    action: "stop",
  });

  $("pauseReset").onclick = () => {
    if (
      confirm(
        "Pausenkonto wirklich "
        + "auf 15:00 zurücksetzen?"
      )
    ) {
      send({
        type: "pause_action",
        action: "reset",
      });
    }
  };

  $("unlockEvent").onclick = () => {
    if (
      confirm(
        "Event wieder freigeben?"
      )
    ) {
      send({
        type: "pause_action",
        action: "unlock",
      });
    }
  };

  $("undoButton").onclick = () => send({
    type: "undo",
  });

  $("fullscreenButton").onclick = (
    toggleFullscreen
  );

  document.addEventListener(
    "fullscreenchange",
    updateFullscreenButton
  );

  all("[data-pause]").forEach(
    (button) => {
      button.onclick = () => {
        send({
          type: "pause_adjust",
          seconds: Number(
            button.dataset.pause
          ),
        });
      };
    }
  );

  all("[data-popup]").forEach(
    (button) => {
      button.onclick = () => {
        send({
          type: "popup_action",
          kind: button.dataset.popup,
        });
      };
    }
  );

  all("[data-donation]").forEach(
    (button) => {
      button.onclick = () => {
        send({
          type: "donation_adjust",
          amount: Number(
            button.dataset.donation
          ),
        });
      };
    }
  );

  $("donationAdd").onclick = () => (
    donationAmount(1)
  );

  $("donationSubtract").onclick = () => (
    donationAmount(-1)
  );

  all(".tab").forEach(
    (button) => {
      button.onclick = () => {
        activateTab(
          button.dataset.tab
        );
      };
    }
  );

  $("fullReset").onclick = () => {
    if (
      confirm(
        "ACHTUNG: Wirklich das gesamte Event "
        + "zurücksetzen?\n\n"
        + "Matches, Specials, Timer, Spenden "
        + "und Historien werden gelöscht."
      )
    ) {
      send({
        type: "full_reset",
      });
    }
  };

  updateFullscreenButton();
  activateTab(activeTab);
  clearMatchForm();
  setInterval(renderLocalClocks, 250);
  connect();
})();
