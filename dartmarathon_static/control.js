(() => {
  let ws = null;
  let reconnectTimer = null;
  let connectionAlarmTimer = null;
  let lastState = null;

  const $ = (id) => document.getElementById(id);
  const all = (sel) => [...document.querySelectorAll(sel)];

  function hideConnectionAlarm() {
    clearTimeout(connectionAlarmTimer);
    connectionAlarmTimer = null;
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

    ws.onerror = () => {
      try { ws.close(); } catch (_) {}
    };

    ws.onmessage = (event) => {
      let msg;
      try {
        msg = JSON.parse(event.data);
      } catch (_) {
        return;
      }

      if (msg.type === "state") render(msg.data);
      if (msg.type === "error") toast(msg.message);
    };
  }

  function send(payload) {
    if (!ws || ws.readyState !== WebSocket.OPEN) {
      scheduleConnectionAlarm();
      toast("Keine Verbindung zum Server.");
      return;
    }
    ws.send(JSON.stringify(payload));
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

    $("legsTzmarty").textContent = s.legs.tzmarty;
    $("legsKorsar").textContent = s.legs.korsar;
    $("specialsTzmarty").textContent = s.player_special_totals.tzmarty;
    $("specialsKorsar").textContent = s.player_special_totals.korsar;
    $("totalLegs").textContent = s.total_legs;
    $("totalSpecialsTop").textContent = s.total_specials;

    $("specialTzmartyHighfinish").textContent = s.specials.tzmarty.highfinish;
    $("specialTzmartyBullfinish").textContent = s.specials.tzmarty.bullfinish;
    $("specialTzmartyLowdarts").textContent = s.specials.tzmarty.lowdarts;
    $("specialTzmartyScore171").textContent = s.specials.tzmarty.score171;
    $("specialKorsarHighfinish").textContent = s.specials.korsar.highfinish;
    $("specialKorsarBullfinish").textContent = s.specials.korsar.bullfinish;
    $("specialKorsarLowdarts").textContent = s.specials.korsar.lowdarts;
    $("specialKorsarScore171").textContent = s.specials.korsar.score171;
    $("totalSpecials").textContent = s.total_specials;

    $("ownDonations").textContent = Number(s.own_donations).toLocaleString("de-DE", {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    });

    if (s.event_ended) $("pauseStatus").textContent = "EVENT BEENDET";
    else if (s.pause_full) $("pauseStatus").textContent = "PAUSENKONTO VOLL";
    else if (s.pause_active) $("pauseStatus").textContent = "PAUSE LÄUFT";
    else $("pauseStatus").textContent = "PAUSE STEHT";

    $("endedBanner").classList.toggle("hidden", !s.event_ended);
    $("pauseFullBanner").classList.toggle("hidden", !s.pause_full);

    $("streamStart").disabled = s.stream_running;
    $("streamStop").disabled = !s.stream_running;
    $("pauseStart").disabled = s.pause_active || s.pause_seconds <= 0 || s.event_ended;
    $("pauseStop").disabled = !s.pause_active;
    $("undoButton").disabled = !s.can_undo;
    $("unlockEvent").disabled = !s.event_ended;

    all('[data-leg-player], [data-special-player], [data-donation]').forEach((b) => {
      b.disabled = s.event_ended;
    });

    $("donationAdd").disabled = s.event_ended;
    $("donationSubtract").disabled = s.event_ended;

    all('[data-pause]').forEach((b) => {
      const value = Number(b.dataset.pause);
      b.disabled =
        (s.event_ended && value > 0) ||
        (value < 0 && s.pause_seconds <= 0) ||
        (value > 0 && s.pause_full);
    });

    $("statOnline").textContent = s.stream_display;
    $("statLegs").textContent = s.total_legs;
    $("statSpecials").textContent = s.total_specials;
    $("statLegsPerHour").textContent = Number(s.legs_per_hour).toLocaleString("de-DE", {
      minimumFractionDigits: 1,
      maximumFractionDigits: 1,
    });
    $("statSpecialsPerHour").textContent = Number(s.specials_per_hour).toLocaleString("de-DE", {
      minimumFractionDigits: 1,
      maximumFractionDigits: 1,
    });
    $("statPauseUsed").textContent = s.pause_used_display;

    $("history").innerHTML = s.history.length
      ? [...s.history].reverse().map((h) =>
          `<div class="history-item"><span class="history-time">${escapeHtml(h.time)}</span><span>${escapeHtml(h.text)}</span></div>`
        ).join("")
      : '<div class="muted">Noch keine Aktionen.</div>';
  }

  function escapeHtml(value) {
    return String(value).replace(/[&<>'"]/g, (char) => ({
      "&": "&amp;",
      "<": "&lt;",
      ">": "&gt;",
      "'": "&#39;",
      '"': "&quot;",
    }[char]));
  }

  function toast(text) {
    const el = $("toast");
    el.textContent = text;
    el.classList.remove("hidden");
    clearTimeout(el._timer);
    el._timer = setTimeout(() => el.classList.add("hidden"), 3200);
  }

  function warnIfPauseFull(isPositive) {
    if (isPositive && lastState && lastState.pause_full) {
      toast("Pausenkonto ist voll. Der Wert wird gezählt, die Pause bleibt bei 30:00.");
    }
  }

  async function toggleFullscreen() {
    try {
      if (!document.fullscreenElement) await document.documentElement.requestFullscreen();
      else await document.exitFullscreen();
    } catch (_) {
      toast("Vollbildmodus konnte vom Browser nicht gestartet werden.");
    }
  }

  function updateFullscreenButton() {
    $("fullscreenButton").textContent = document.fullscreenElement
      ? "VOLLBILD BEENDEN"
      : "VOLLBILD";
  }

  $("fullscreenButton").onclick = toggleFullscreen;
  document.addEventListener("fullscreenchange", updateFullscreenButton);

  $("streamStart").onclick = () => send({type: "stream_action", action: "start"});
  $("streamStop").onclick = () => send({type: "stream_action", action: "stop"});
  $("streamReset").onclick = () => {
    if (confirm("Streamlaufzeit wirklich auf 00:00:00 zurücksetzen?")) {
      send({type: "stream_action", action: "reset"});
    }
  };

  $("pauseStart").onclick = () => send({type: "pause_action", action: "start"});
  $("pauseStop").onclick = () => send({type: "pause_action", action: "stop"});
  $("pauseReset").onclick = () => {
    if (confirm("Pausenkonto wirklich auf 15:00 zurücksetzen?")) {
      send({type: "pause_action", action: "reset"});
    }
  };
  $("unlockEvent").onclick = () => {
    if (confirm("Event wieder freigeben? Danach sind neue Gutschriften wieder möglich.")) {
      send({type: "pause_action", action: "unlock"});
    }
  };

  $("undoButton").onclick = () => send({type: "undo"});
  $("fullReset").onclick = () => {
    if (confirm("ACHTUNG: Wirklich das gesamte Event zurücksetzen? Legs, Specials, Timer, Pausenstatistik, eigene Spenden und Historie werden zurückgesetzt. Das Pausenkonto startet wieder bei 15:00.")) {
      send({type: "full_reset"});
    }
  };

  all('[data-pause]').forEach((b) => {
    b.onclick = () => send({type: "pause_adjust", seconds: Number(b.dataset.pause)});
  });

  all('[data-leg-player]').forEach((b) => {
    b.onclick = () => {
      const delta = Number(b.dataset.delta);
      warnIfPauseFull(delta > 0);
      send({type: "leg_adjust", player: b.dataset.legPlayer, delta});
    };
  });

  all('[data-special-player]').forEach((b) => {
    b.onclick = () => {
      const delta = Number(b.dataset.delta);
      warnIfPauseFull(delta > 0);
      send({
        type: "special_adjust",
        player: b.dataset.specialPlayer,
        category: b.dataset.special,
        delta,
      });
    };
  });

  all('[data-donation]').forEach((b) => {
    b.onclick = () => {
      const amount = Number(b.dataset.donation);
      warnIfPauseFull(amount > 0);
      send({type: "donation_adjust", amount});
    };
  });

  all('[data-ad]').forEach((b) => {
    b.onclick = () => {
      send({type: "ad_popup", sponsor: b.dataset.ad});
      toast(`${b.textContent.trim()} wird für 20 Sekunden eingeblendet.`);
    };
  });

  function donationAmount(sign) {
    const input = $("donationAmount");
    const amount = Number(String(input.value).replace(",", "."));
    if (!Number.isFinite(amount) || amount <= 0) {
      toast("Bitte einen gültigen Betrag eingeben.");
      return;
    }
    if (sign > 0) warnIfPauseFull(true);
    send({type: "donation_adjust", amount: sign * amount});
    input.value = "";
  }

  $("donationAdd").onclick = () => donationAmount(1);
  $("donationSubtract").onclick = () => donationAmount(-1);

  updateFullscreenButton();
  connect();
})();
