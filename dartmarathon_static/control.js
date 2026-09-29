(() => {
  let ws;
  let reconnectTimer;
  let lastState = null;

  const $ = (id) => document.getElementById(id);
  const all = (sel) => [...document.querySelectorAll(sel)];

  function connect() {
    const proto = location.protocol === "https:" ? "wss" : "ws";
    ws = new WebSocket(`${proto}://${location.host}/dartmarathon/ws`);
    ws.onopen = () => {
      $("connectionDot").className = "dot online";
      $("connectionText").textContent = "live verbunden";
    };
    ws.onclose = () => {
      $("connectionDot").className = "dot offline";
      $("connectionText").textContent = "Verbindung getrennt";
      clearTimeout(reconnectTimer);
      reconnectTimer = setTimeout(connect, 1500);
    };
    ws.onerror = () => ws.close();
    ws.onmessage = (event) => {
      const msg = JSON.parse(event.data);
      if (msg.type === "state") render(msg.data);
      if (msg.type === "error") toast(msg.message);
    };
  }

  function send(payload) {
    if (!ws || ws.readyState !== WebSocket.OPEN) return toast("Keine Verbindung zum Server.");
    ws.send(JSON.stringify(payload));
  }

  function render(s) {
    lastState = s;
    $("streamTime").textContent = s.stream_display;
    $("pauseTime").textContent = s.pause_display;
    $("legsTzmarty").textContent = s.legs.tzmarty;
    $("legsKorsar").textContent = s.legs.korsar;
    $("totalLegs").textContent = s.total_legs;
    $("specialHighfinish").textContent = s.specials.highfinish;
    $("specialBullfinish").textContent = s.specials.bullfinish;
    $("specialLowdarts").textContent = s.specials.lowdarts;
    $("specialScore171").textContent = s.specials.score171;
    $("totalSpecials").textContent = s.total_specials;
    $("ownDonations").textContent = Number(s.own_donations).toLocaleString("de-DE", {minimumFractionDigits:2, maximumFractionDigits:2});
    $("pauseStatus").textContent = s.event_ended ? "EVENT BEENDET" : (s.pause_active ? "PAUSE LÄUFT" : "PAUSE STEHT");
    $("endedBanner").classList.toggle("hidden", !s.event_ended);

    $("streamStart").disabled = s.stream_running;
    $("streamStop").disabled = !s.stream_running;
    $("pauseStart").disabled = s.pause_active || s.pause_seconds <= 0 || s.event_ended;
    $("pauseStop").disabled = !s.pause_active;
    $("undoButton").disabled = !s.can_undo;
    $("unlockEvent").disabled = !s.event_ended;

    all('[data-leg-player], [data-special], [data-donation]').forEach(b => b.disabled = s.event_ended);
    $("donationAdd").disabled = s.event_ended;
    $("donationSubtract").disabled = s.event_ended;
    all('[data-pause]').forEach(b => {
      const v = Number(b.dataset.pause);
      b.disabled = (s.event_ended && v > 0) || (v < 0 && s.pause_seconds <= 0);
    });

    $("history").innerHTML = s.history.length
      ? [...s.history].reverse().map(h => `<div class="history-item"><span class="history-time">${escapeHtml(h.time)}</span><span>${escapeHtml(h.text)}</span></div>`).join("")
      : '<div class="muted">Noch keine Aktionen.</div>';
  }

  function escapeHtml(v) {
    return String(v).replace(/[&<>'"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c]));
  }

  function toast(text) {
    const el = $("toast");
    el.textContent = text;
    el.classList.remove("hidden");
    clearTimeout(el._timer);
    el._timer = setTimeout(() => el.classList.add("hidden"), 2800);
  }

  $("streamStart").onclick = () => send({type:"stream_action", action:"start"});
  $("streamStop").onclick = () => send({type:"stream_action", action:"stop"});
  $("streamReset").onclick = () => confirm("Streamlaufzeit wirklich auf 00:00:00 zurücksetzen?") && send({type:"stream_action", action:"reset"});
  $("pauseStart").onclick = () => send({type:"pause_action", action:"start"});
  $("pauseStop").onclick = () => send({type:"pause_action", action:"stop"});
  $("pauseReset").onclick = () => confirm("Pausenkonto wirklich auf 00:00 zurücksetzen?") && send({type:"pause_action", action:"reset"});
  $("unlockEvent").onclick = () => confirm("Event wieder freigeben? Danach sind neue Gutschriften wieder möglich.") && send({type:"pause_action", action:"unlock"});
  $("undoButton").onclick = () => send({type:"undo"});
  $("fullReset").onclick = () => {
    if (confirm("ACHTUNG: Wirklich das gesamte Event zurücksetzen? Legs, Specials, Timer, eigene Spenden und Historie werden zurückgesetzt.")) send({type:"full_reset"});
  };

  all('[data-pause]').forEach(b => b.onclick = () => send({type:"pause_adjust", seconds:Number(b.dataset.pause)}));
  all('[data-leg-player]').forEach(b => b.onclick = () => send({type:"leg_adjust", player:b.dataset.legPlayer, delta:Number(b.dataset.delta)}));
  all('[data-special]').forEach(b => b.onclick = () => send({type:"special_adjust", category:b.dataset.special, delta:Number(b.dataset.delta)}));
  all('[data-donation]').forEach(b => b.onclick = () => send({type:"donation_adjust", amount:Number(b.dataset.donation)}));

  function donationAmount(sign) {
    const input = $("donationAmount");
    const amount = Number(String(input.value).replace(",", "."));
    if (!Number.isFinite(amount) || amount <= 0) return toast("Bitte einen gültigen Betrag eingeben.");
    send({type:"donation_adjust", amount:sign * amount});
    input.value = "";
  }
  $("donationAdd").onclick = () => donationAmount(1);
  $("donationSubtract").onclick = () => donationAmount(-1);

  connect();
})();
