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
      $("connectionAlarm").classList.add("hidden");
    };

    ws.onclose = () => {
      $("connectionDot").className = "dot offline";
      $("connectionText").textContent = "Verbindung getrennt";
      $("connectionAlarm").classList.remove("hidden");
      clearTimeout(reconnectTimer);
      reconnectTimer = setTimeout(connect, 1500);
    };

    ws.onerror = () => ws.close();

    ws.onmessage = (event) => {
      const msg = JSON.parse(event.data);

      if (msg.type === "state") {
        render(msg.data);
      }

      if (msg.type === "error") {
        toast(msg.message);
      }
    };
  }

  function send(payload) {
    if (!ws || ws.readyState !== WebSocket.OPEN) {
      toast("Keine Verbindung zum Server.");
      return;
    }

    ws.send(JSON.stringify(payload));
  }

  function setPauseColor(element, seconds) {
    element.classList.remove(
      "pause-red",
      "pause-yellow",
      "pause-green"
    );

    if (seconds <= 300) {
      element.classList.add("pause-red");
    } else if (seconds <= 600) {
      element.classList.add("pause-yellow");
    } else {
      element.classList.add("pause-green");
    }
  }

  function render(s) {
    lastState = s;
    $("streamTime").textContent = s.stream_display;
    $("pauseTime").textContent = s.pause_display;

    $("legsTzmarty").textContent = s.legs.tzmarty;
    $("legsKorsar").textContent = s.legs.korsar;
    $("specialsTzmarty").textContent = s.player_special_totals.tzmarty;
    $("specialsKorsar").textContent = s.player_special_totals.korsar;

    $("totalLegs").textContent = s.total_legs;
    $("totalSpecialsTop").textContent = s.total_specials;

    $("specialTzmartyHighfinish").textContent =
      s.specials.tzmarty.highfinish;
    $("specialTzmartyBullfinish").textContent =
      s.specials.tzmarty.bullfinish;
    $("specialTzmartyLowdarts").textContent =
      s.specials.tzmarty.lowdarts;
    $("specialTzmartyScore171").textContent =
      s.specials.tzmarty.score171;

    $("specialKorsarHighfinish").textContent =
      s.specials.korsar.highfinish;
    $("specialKorsarBullfinish").textContent =
      s.specials.korsar.bullfinish;
    $("specialKorsarLowdarts").textContent =
      s.specials.korsar.lowdarts;
    $("specialKorsarScore171").textContent =
      s.specials.korsar.score171;

    $("totalSpecials").textContent = s.total_specials;

    $("ownDonations").textContent =
      Number(s.own_donations).toLocaleString(
        "de-DE",
        {
          minimumFractionDigits: 2,
          maximumFractionDigits: 2,
        }
      );

    setPauseColor(
      $("pauseTime"),
      s.pause_seconds
    );

    $("pauseStatus").textContent =
      s.event_ended
        ? "EVENT BEENDET"
        : (
            s.pause_active
              ? "PAUSE LÄUFT"
              : "PAUSE STEHT"
          );

    $("endedBanner").classList.toggle(
      "hidden",
      !s.event_ended
    );

    $("streamStart").disabled =
      s.stream_running;

    $("streamStop").disabled =
      !s.stream_running;

    $("pauseStart").disabled =
      s.pause_active
      || s.pause_seconds <= 0
      || s.event_ended;

    $("pauseStop").disabled =
      !s.pause_active;

    $("undoButton").disabled =
      !s.can_undo;

    $("unlockEvent").disabled =
      !s.event_ended;

    all(
      "[data-leg-player], [data-special-player], [data-donation]"
    ).forEach((button) => {
      button.disabled = s.event_ended;
    });

    $("donationAdd").disabled =
      s.event_ended;

    $("donationSubtract").disabled =
      s.event_ended;

    all("[data-pause]").forEach((button) => {
      const value =
        Number(button.dataset.pause);

      button.disabled =
        (s.event_ended && value > 0)
        || (
          value < 0
          && s.pause_seconds <= 0
        );
    });

    $("history").innerHTML =
      s.history.length
        ? [...s.history]
            .reverse()
            .map(
              (h) =>
                `<div class="history-item">`
                + `<span class="history-time">${escapeHtml(h.time)}</span>`
                + `<span>${escapeHtml(h.text)}</span>`
                + `</div>`
            )
            .join("")
        : '<div class="muted">Noch keine Aktionen.</div>';
  }

  function escapeHtml(value) {
    return String(value).replace(
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

  function toast(text) {
    const element = $("toast");

    element.textContent = text;
    element.classList.remove("hidden");

    clearTimeout(element._timer);

    element._timer =
      setTimeout(
        () => element.classList.add("hidden"),
        2800
      );
  }

  $("streamStart").onclick = () =>
    send({
      type: "stream_action",
      action: "start",
    });

  $("streamStop").onclick = () =>
    send({
      type: "stream_action",
      action: "stop",
    });

  $("streamReset").onclick = () => {
    if (
      confirm(
        "Streamlaufzeit wirklich auf 00:00:00 zurücksetzen?"
      )
    ) {
      send({
        type: "stream_action",
        action: "reset",
      });
    }
  };

  $("pauseStart").onclick = () =>
    send({
      type: "pause_action",
      action: "start",
    });

  $("pauseStop").onclick = () =>
    send({
      type: "pause_action",
      action: "stop",
    });

  $("pauseReset").onclick = () => {
    if (
      confirm(
        "Pausenkonto wirklich auf 15:00 zurücksetzen?"
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
        "Event wieder freigeben? Danach sind neue Gutschriften wieder möglich."
      )
    ) {
      send({
        type: "pause_action",
        action: "unlock",
      });
    }
  };

  $("undoButton").onclick = () =>
    send({
      type: "undo",
    });

  $("fullReset").onclick = () => {
    if (
      confirm(
        "ACHTUNG: Wirklich das gesamte Event zurücksetzen? "
        + "Legs, Specials, Timer, eigene Spenden und Historie "
        + "werden zurückgesetzt. Das Pausenkonto startet wieder bei 15:00."
      )
    ) {
      send({
        type: "full_reset",
      });
    }
  };

  all("[data-pause]").forEach(
    (button) => {
      button.onclick = () =>
        send({
          type: "pause_adjust",
          seconds:
            Number(button.dataset.pause),
        });
    }
  );

  all("[data-leg-player]").forEach(
    (button) => {
      button.onclick = () =>
        send({
          type: "leg_adjust",
          player:
            button.dataset.legPlayer,
          delta:
            Number(button.dataset.delta),
        });
    }
  );

  all("[data-special-player]").forEach(
    (button) => {
      button.onclick = () =>
        send({
          type: "special_adjust",
          player:
            button.dataset.specialPlayer,
          category:
            button.dataset.special,
          delta:
            Number(button.dataset.delta),
        });
    }
  );

  all("[data-donation]").forEach(
    (button) => {
      button.onclick = () =>
        send({
          type: "donation_adjust",
          amount:
            Number(button.dataset.donation),
        });
    }
  );

  all('[data-ad]').forEach(b => b.onclick = () => {
    send({type:"ad_popup", sponsor:b.dataset.ad});
    toast(`${b.textContent.trim()} wird für 20 Sekunden eingeblendet.`);
  });

  function donationAmount(sign) {
    const input =
      $("donationAmount");

    const amount =
      Number(
        String(input.value)
          .replace(",", ".")
      );

    if (
      !Number.isFinite(amount)
      || amount <= 0
    ) {
      toast(
        "Bitte einen gültigen Betrag eingeben."
      );
      return;
    }

    send({
      type: "donation_adjust",
      amount: sign * amount,
    });

    input.value = "";
  }

  $("donationAdd").onclick =
    () => donationAmount(1);

  $("donationSubtract").onclick =
    () => donationAmount(-1);

  updateFullscreenButton();
  connect();
})();
