(() => {
  let ws = null;
  let retry = null;
  let popupTimer = null;
  const $ = (id) => document.getElementById(id);

  function connect() {
    const proto = location.protocol === "https:" ? "wss" : "ws";
    ws = new WebSocket(`${proto}://${location.host}/dartmarathon/ws`);
    ws.onmessage = (event) => {
      let msg;
      try { msg = JSON.parse(event.data); } catch (_) { return; }
      if (msg.type === "state") render(msg.data);
      if (msg.type === "ad_popup") showAd(msg);
      if (msg.type === "recent_matches_popup") showRecent(msg);
      if (msg.type === "specials_popup") showSpecials(msg);
      if (msg.type === "stats_popup") showStats(msg);
    };
    ws.onclose = () => { clearTimeout(retry); retry = setTimeout(connect, 1200); };
    ws.onerror = () => { try { ws.close(); } catch (_) {} };
  }

  function hideAllPopups() {
    for (const id of ["adPopup","recentPopup","specialsPopup","statsPopup"]) $(id).classList.add("hidden");
    clearTimeout(popupTimer);
  }

  function displayPopup(id, duration) {
    hideAllPopups();
    $(id).classList.remove("hidden");
    popupTimer = setTimeout(() => $(id).classList.add("hidden"), Number(duration) || 20000);
  }

  function setPauseColor(el, seconds) {
    el.classList.remove("pause-red","pause-yellow","pause-green");
    if (seconds <= 300) el.classList.add("pause-red");
    else if (seconds <= 600) el.classList.add("pause-yellow");
    else el.classList.add("pause-green");
  }

  function render(s) {
    $("ovTzmarty").textContent = `${s.legs.tzmarty} / ${s.player_special_totals.tzmarty}`;
    $("ovKorsar").textContent = `${s.legs.korsar} / ${s.player_special_totals.korsar}`;
    $("ovTotalLegs").textContent = s.total_legs;
    $("ovSpecials").textContent = s.total_specials;
    $("ovPause").textContent = s.pause_display;
    $("ovStream").textContent = s.stream_display;
    $("pauseCenterTime").textContent = s.pause_display;
    setPauseColor($("ovPause"), s.pause_seconds);
    setPauseColor($("pauseCenterTime"), s.pause_seconds);
    $("pauseCenter").classList.toggle("hidden", !s.pause_active || s.event_ended);
    $("eventEnded").classList.toggle("hidden", !s.event_ended);
  }

  function showAd(msg) {
    $("adPopupImage").src = `${msg.image}?t=${Date.now()}`;
    $("adPopupImage").alt = msg.label || "Werbeeinblendung";
    displayPopup("adPopup", msg.duration_ms);
  }

  function showRecent(msg) {
    const list = msg.matches || [];
    $("recentMatchesList").innerHTML = list.length ? list.map((m) => `<div class="recent-row"><strong>#${m.id} · ${escapeHtml(m.mode)}</strong><span>${escapeHtml(m.result)}</span></div>`).join("") : '<div class="popup-empty">Noch keine Matches.</div>';
    displayPopup("recentPopup", msg.duration_ms);
  }

  function detailLines(detail) {
    const lines = [];
    if (detail.hf?.length) lines.push(["HF", detail.hf.join(", ")]);
    if (detail.bf?.length) lines.push(["BF", detail.bf.join(", ")]);
    for (const key of ["180","177","174","171"]) if (detail[key]) lines.push([key, `× ${detail[key]}`]);
    if (detail.ld?.length) lines.push(["LD", detail.ld.join(", ")]);
    if (detail.legacy) lines.push(["Altbestand", detail.legacy]);
    return lines;
  }

  function renderSpecialCard(id, detail) {
    const lines = detailLines(detail);
    $(id).innerHTML = lines.length ? lines.map(([label,value]) => `<div class="special-popup-row"><span>${escapeHtml(label)}</span><strong>${escapeHtml(value)}</strong></div>`).join("") : '<div class="popup-empty">Noch keine Specials.</div>';
  }

  function showSpecials(msg) {
    renderSpecialCard("tzSpecialPopup", msg.players?.tzmarty || {});
    renderSpecialCard("koSpecialPopup", msg.players?.korsar || {});
    displayPopup("specialsPopup", msg.duration_ms);
  }

  function showStats(msg) {
    const s = msg.stats || {};
    $("statsPopupTitle").textContent = msg.title || "EVENT-KENNZAHLEN";
    $("popLegs").textContent = s.total_legs ?? 0;
    $("popSpecials").textContent = s.total_specials ?? 0;
    $("popSpecialsPerLeg").textContent = Number(s.specials_per_leg || 0).toLocaleString("de-DE", {minimumFractionDigits:2,maximumFractionDigits:2});
    $("popLegsPerHour").textContent = Number(s.legs_per_hour || 0).toLocaleString("de-DE", {minimumFractionDigits:1,maximumFractionDigits:1});
    $("popSpecialsPerHour").textContent = Number(s.specials_per_hour || 0).toLocaleString("de-DE", {minimumFractionDigits:1,maximumFractionDigits:1});
    $("popPauseUsed").textContent = s.pause_used_display || "00:00:00";
    displayPopup("statsPopup", msg.duration_ms);
  }

  function escapeHtml(value) {
    return String(value).replace(/[&<>'"]/g, (c) => ({"&":"&amp;","<":"&lt;",">":"&gt;","'":"&#39;",'"':"&quot;"}[c]));
  }

  connect();
})();
