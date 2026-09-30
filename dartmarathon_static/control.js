(() => {
  let ws = null;
  let reconnectTimer = null;
  let connectionAlarmTimer = null;
  let lastState = null;
  let editingMatchId = null;

  const $ = (id) => document.getElementById(id);
  const all = (selector) => [...document.querySelectorAll(selector)];

  function connect() {
    clearTimeout(reconnectTimer);
    scheduleConnectionAlarm();
    const proto = location.protocol === "https:" ? "wss" : "ws";
    ws = new WebSocket(`${proto}://${location.host}/dartmarathon/ws`);

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

    ws.onerror = () => { try { ws.close(); } catch (_) {} };

    ws.onmessage = (event) => {
      let msg;
      try { msg = JSON.parse(event.data); } catch (_) { return; }
      if (msg.type === "state") render(msg.data);
      if (msg.type === "error") toast(msg.message);
    };
  }

  function hideConnectionAlarm() {
    clearTimeout(connectionAlarmTimer);
    $("connectionAlarm").classList.add("hidden");
  }

  function scheduleConnectionAlarm() {
    clearTimeout(connectionAlarmTimer);
    connectionAlarmTimer = setTimeout(() => {
      if (!ws || ws.readyState !== WebSocket.OPEN) {
        $("connectionAlarm").classList.remove("hidden");
      }
    }, 3000);
  }

  function send(payload) {
    if (!ws || ws.readyState !== WebSocket.OPEN) {
      scheduleConnectionAlarm();
      toast("Keine Verbindung zum Server.");
      return false;
    }
    ws.send(JSON.stringify(payload));
    return true;
  }

  function parseList(value, minimum, maximum = null, label = "Wert") {
    const text = String(value || "").trim();
    if (!text) return [];
    const parts = text.split(/[\s,;]+/).filter(Boolean);
    const values = parts.map((part) => Number(part));
    if (values.some((v) => !Number.isInteger(v))) {
      throw new Error(`${label}: Bitte nur ganze Zahlen eingeben.`);
    }
    if (values.some((v) => v < minimum || (maximum !== null && v > maximum))) {
      const range = maximum === null ? `ab ${minimum}` : `${minimum} bis ${maximum}`;
      throw new Error(`${label}: Erlaubt sind nur Werte ${range}.`);
    }
    return values;
  }

  function countValue(id) {
    const value = Number($(id).value || 0);
    if (!Number.isInteger(value) || value < 0) throw new Error("Special-Anzahlen müssen ganze Zahlen ab 0 sein.");
    return value;
  }

  function readSpecials(prefix) {
    return {
      hf: parseList($(prefix + "HF").value, 100, null, "HF"),
      bf: parseList($(prefix + "BF").value, 50, null, "BF"),
      "180": countValue(prefix + "180"),
      "177": countValue(prefix + "177"),
      "174": countValue(prefix + "174"),
      "171": countValue(prefix + "171"),
      ld: parseList($(prefix + "LD").value, 9, 18, "LD"),
    };
  }

  function specialCount(detail) {
    return detail.hf.length + detail.bf.length + detail.ld.length
      + detail["180"] + detail["177"] + detail["174"] + detail["171"];
  }

  function readMatchForm() {
    const mode = $("matchMode").value;
    const result = {
      tzmarty_legs: mode === "set" ? Number($("setLegsTzmarty").value || 0) : Number($("resultTzmarty").value || 0),
      korsar_legs: mode === "set" ? Number($("setLegsKorsar").value || 0) : Number($("resultKorsar").value || 0),
      tzmarty_sets: mode === "set" ? Number($("setsTzmarty").value || 0) : 0,
      korsar_sets: mode === "set" ? Number($("setsKorsar").value || 0) : 0,
    };
    for (const value of Object.values(result)) {
      if (!Number.isInteger(value) || value < 0) throw new Error("Ergebnisse müssen ganze Zahlen ab 0 sein.");
    }
    if (result.tzmarty_legs + result.korsar_legs <= 0) throw new Error("Bitte ein Spielergebnis eintragen.");
    if (mode === "set" && result.tzmarty_sets + result.korsar_sets <= 0) throw new Error("Beim Setmodus bitte das Settergebnis eintragen.");

    const specials = {
      tzmarty: readSpecials("tz"),
      korsar: readSpecials("ko"),
    };
    return { mode, result, specials };
  }

  function formatPause(seconds) {
    const value = Math.max(0, Math.round(seconds));
    const m = Math.floor(value / 60);
    const s = value % 60;
    return `${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
  }

  function updateMatchPreview() {
    try {
      const data = readMatchForm();
      const legs = data.result.tzmarty_legs + data.result.korsar_legs;
      const specials = specialCount(data.specials.tzmarty) + specialCount(data.specials.korsar);
      const pause = legs * 30 + specials * 60;
      $("matchPreview").textContent = `${legs} Legs · ${specials} Specials · +${formatPause(pause)} Pause`;
      $("matchPreview").classList.remove("preview-error");
    } catch (_) {
      $("matchPreview").textContent = "Eingaben prüfen";
      $("matchPreview").classList.add("preview-error");
    }
  }

  function clearMatchForm() {
    editingMatchId = null;
    $("matchMode").value = "sido";
    for (const id of ["resultTzmarty","resultKorsar","setsTzmarty","setsKorsar","setLegsTzmarty","setLegsKorsar","tz180","tz177","tz174","tz171","ko180","ko177","ko174","ko171"]) $(id).value = 0;
    for (const id of ["tzHF","tzBF","tzLD","koHF","koBF","koLD"]) $(id).value = "";
    $("editHint").textContent = "Neues Match";
    $("saveMatch").textContent = "MATCH SPEICHERN";
    $("cancelEdit").classList.add("hidden");
    toggleSetMode();
    updateMatchPreview();
  }

  function fillSpecials(prefix, detail) {
    $(prefix + "HF").value = detail.hf.join(", ");
    $(prefix + "BF").value = detail.bf.join(", ");
    $(prefix + "180").value = detail["180"];
    $(prefix + "177").value = detail["177"];
    $(prefix + "174").value = detail["174"];
    $(prefix + "171").value = detail["171"];
    $(prefix + "LD").value = detail.ld.join(", ");
  }

  function editMatch(id) {
    const match = lastState?.matches.find((m) => m.id === id);
    if (!match) return;
    editingMatchId = id;
    $("matchMode").value = match.mode;
    $("resultTzmarty").value = match.result.tzmarty_legs;
    $("resultKorsar").value = match.result.korsar_legs;
    $("setsTzmarty").value = match.result.tzmarty_sets;
    $("setsKorsar").value = match.result.korsar_sets;
    $("setLegsTzmarty").value = match.result.tzmarty_legs;
    $("setLegsKorsar").value = match.result.korsar_legs;
    fillSpecials("tz", match.specials.tzmarty);
    fillSpecials("ko", match.specials.korsar);
    $("editHint").textContent = `Bearbeitung Match #${id}`;
    $("saveMatch").textContent = "ÄNDERUNGEN SPEICHERN";
    $("cancelEdit").classList.remove("hidden");
    toggleSetMode();
    updateMatchPreview();
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  function deleteMatch(id) {
    if (confirm(`Match #${id} wirklich löschen? Legs, Specials und die zugehörige Pausengutschrift werden korrigiert.`)) {
      send({ type: "match_delete", id });
      if (editingMatchId === id) clearMatchForm();
    }
  }

  function formatSpecialSummary(detail) {
    const parts = [];
    if (detail.hf.length) parts.push(`HF ${detail.hf.join(", ")}`);
    if (detail.bf.length) parts.push(`BF ${detail.bf.join(", ")}`);
    for (const key of ["180","177","174","171"]) if (detail[key]) parts.push(`${key} ×${detail[key]}`);
    if (detail.ld.length) parts.push(`LD ${detail.ld.join(", ")}`);
    return parts.length ? parts.join(" · ") : "keine Specials";
  }

  function renderMatches(matches) {
    $("matchHistory").innerHTML = matches.length ? matches.map((m) => `
      <div class="match-row">
        <div class="match-main"><strong>#${m.id} · ${escapeHtml(m.mode_label)}</strong><span>${escapeHtml(m.result_text)}</span></div>
        <div class="match-meta">${m.special_total} Specials · +${formatPause(m.pause_credit_applied_seconds)} Pause gutgeschrieben</div>
        <div class="row-actions"><button class="mini ghost" data-edit-match="${m.id}">BEARBEITEN</button><button class="mini danger" data-delete-match="${m.id}">LÖSCHEN</button></div>
      </div>`).join("") : '<div class="empty-state">Noch keine Matches gespeichert.</div>';

    all("[data-edit-match]").forEach((b) => b.onclick = () => editMatch(Number(b.dataset.editMatch)));
    all("[data-delete-match]").forEach((b) => b.onclick = () => deleteMatch(Number(b.dataset.deleteMatch)));
  }

  function renderSpecialHistory(matches) {
    const entries = [];
    for (const m of matches) {
      for (const player of ["tzmarty", "korsar"]) {
        if (m.special_totals[player] <= 0) continue;
        entries.push(`<div class="special-history-row"><strong>#${m.id} · ${player === "tzmarty" ? "Tzmarty" : "Korsar"}</strong><span>${escapeHtml(formatSpecialSummary(m.specials[player]))}</span></div>`);
      }
    }
    $("specialHistory").innerHTML = entries.length ? entries.join("") : '<div class="empty-state">Noch keine Specials gespeichert.</div>';
  }

  function setPauseColor(element, seconds) {
    element.classList.remove("pause-red", "pause-yellow", "pause-green");
    if (seconds <= 300) element.classList.add("pause-red");
    else if (seconds <= 600) element.classList.add("pause-yellow");
    else element.classList.add("pause-green");
  }

  function render(s) {
    lastState = s;
    $("streamTime").textContent = s.stream_display;
    $("pauseTime").textContent = s.pause_display;
    setPauseColor($("pauseTime"), s.pause_seconds);
    $("pauseStatus").textContent = s.event_ended ? "EVENT BEENDET" : s.pause_active ? "PAUSE LÄUFT" : s.pause_full ? "PAUSE VOLL" : "PAUSE STEHT";
    $("endedBanner").classList.toggle("hidden", !s.event_ended);
    $("pauseFullBanner").classList.toggle("hidden", !s.pause_full);

    $("legsTzmarty").textContent = s.legs.tzmarty;
    $("legsKorsar").textContent = s.legs.korsar;
    $("totalLegs").textContent = s.total_legs;
    $("specialsTzmarty").textContent = s.player_special_totals.tzmarty;
    $("specialsKorsar").textContent = s.player_special_totals.korsar;
    $("totalSpecials").textContent = s.total_specials;

    $("statLegs").textContent = s.total_legs;
    $("statSpecials").textContent = s.total_specials;
    $("statSpecialsPerLeg").textContent = Number(s.specials_per_leg).toLocaleString("de-DE", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    $("statLegsPerHour").textContent = Number(s.legs_per_hour).toLocaleString("de-DE", { minimumFractionDigits: 1, maximumFractionDigits: 1 });
    $("statSpecialsPerHour").textContent = Number(s.specials_per_hour).toLocaleString("de-DE", { minimumFractionDigits: 1, maximumFractionDigits: 1 });
    $("statPauseUsed").textContent = s.pause_used_display;

    $("ownDonations").textContent = Number(s.own_donations).toLocaleString("de-DE", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    renderMatches(s.matches);
    renderSpecialHistory(s.matches);

    $("history").innerHTML = s.history.length ? [...s.history].reverse().map((h) => `<div class="history-line"><span>${escapeHtml(h.time)}</span><b>${escapeHtml(h.text)}</b></div>`).join("") : '<div class="empty-state">Noch keine Aktionen.</div>';

    $("streamStart").disabled = s.stream_running;
    $("streamStop").disabled = !s.stream_running;
    $("pauseStart").disabled = s.pause_active || s.pause_seconds <= 0 || s.event_ended;
    $("pauseStop").disabled = !s.pause_active;
    $("undoButton").disabled = !s.can_undo;
    $("unlockEvent").disabled = !s.event_ended;
    $("saveMatch").disabled = s.event_ended;
    $("donationAdd").disabled = s.event_ended;
    $("donationSubtract").disabled = s.event_ended;
    all("[data-donation]").forEach((b) => b.disabled = s.event_ended);
    all("[data-pause]").forEach((b) => {
      const value = Number(b.dataset.pause);
      b.disabled = (s.event_ended && value > 0) || (value > 0 && s.pause_full) || (value < 0 && s.pause_seconds <= 0);
    });
  }

  function escapeHtml(value) {
    return String(value).replace(/[&<>'"]/g, (c) => ({"&":"&amp;","<":"&lt;",">":"&gt;","'":"&#39;",'"':"&quot;"}[c]));
  }

  function toast(text) {
    const el = $("toast");
    el.textContent = text;
    el.classList.remove("hidden");
    clearTimeout(el._timer);
    el._timer = setTimeout(() => el.classList.add("hidden"), 3500);
  }

  function toggleSetMode() {
    const isSet = $("matchMode").value === "set";
    $("normalResult").classList.toggle("hidden", isSet);
    $("setResult").classList.toggle("hidden", !isSet);
    updateMatchPreview();
  }

  async function toggleFullscreen() {
    try {
      if (!document.fullscreenElement) await document.documentElement.requestFullscreen();
      else await document.exitFullscreen();
    } catch (_) { toast("Vollbildmodus konnte nicht gestartet werden."); }
  }

  function updateFullscreenButton() {
    $("fullscreenButton").textContent = document.fullscreenElement ? "VOLLBILD BEENDEN" : "VOLLBILD";
  }

  $("matchMode").onchange = toggleSetMode;
  all(".match-entry-card input, .match-entry-card select").forEach((el) => el.addEventListener("input", updateMatchPreview));
  $("saveMatch").onclick = () => {
    try {
      const data = readMatchForm();
      if (send({ type: "match_save", id: editingMatchId, ...data })) {
        setTimeout(clearMatchForm, 150);
      }
    } catch (error) { toast(error.message); }
  };
  $("cancelEdit").onclick = clearMatchForm;

  $("streamStart").onclick = () => send({ type: "stream_action", action: "start" });
  $("streamStop").onclick = () => send({ type: "stream_action", action: "stop" });
  $("streamReset").onclick = () => { if (confirm("Streamlaufzeit wirklich auf 00:00:00 zurücksetzen?")) send({ type: "stream_action", action: "reset" }); };
  $("pauseStart").onclick = () => send({ type: "pause_action", action: "start" });
  $("pauseStop").onclick = () => send({ type: "pause_action", action: "stop" });
  $("pauseReset").onclick = () => { if (confirm("Pausenkonto wirklich auf 15:00 zurücksetzen?")) send({ type: "pause_action", action: "reset" }); };
  $("unlockEvent").onclick = () => { if (confirm("Event wieder freigeben?")) send({ type: "pause_action", action: "unlock" }); };
  $("undoButton").onclick = () => send({ type: "undo" });
  $("fullscreenButton").onclick = toggleFullscreen;
  document.addEventListener("fullscreenchange", updateFullscreenButton);

  all("[data-pause]").forEach((b) => b.onclick = () => send({ type: "pause_adjust", seconds: Number(b.dataset.pause) }));
  all("[data-popup]").forEach((b) => b.onclick = () => send({ type: "popup_action", kind: b.dataset.popup }));
  all("[data-donation]").forEach((b) => b.onclick = () => send({ type: "donation_adjust", amount: Number(b.dataset.donation) }));

  function donationAmount(sign) {
    const input = $("donationAmount");
    const amount = Number(String(input.value).replace(",", "."));
    if (!Number.isFinite(amount) || amount <= 0) return toast("Bitte einen gültigen Betrag eingeben.");
    send({ type: "donation_adjust", amount: sign * amount });
    input.value = "";
  }
  $("donationAdd").onclick = () => donationAmount(1);
  $("donationSubtract").onclick = () => donationAmount(-1);

  all(".tab").forEach((button) => button.onclick = () => {
    all(".tab").forEach((b) => b.classList.remove("active"));
    all(".tab-panel").forEach((p) => p.classList.remove("active"));
    button.classList.add("active");
    $(`tab-${button.dataset.tab}`).classList.add("active");
  });

  $("fullReset").onclick = () => {
    if (confirm("ACHTUNG: Wirklich das gesamte Event zurücksetzen? Matches, Specials, Timer, Spenden und Historie werden gelöscht.")) {
      send({ type: "full_reset" });
      clearMatchForm();
    }
  };

  updateFullscreenButton();
  clearMatchForm();
  connect();
})();
