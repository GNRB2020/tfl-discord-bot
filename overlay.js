(() => {
  let ws;
  let retry;
  let initialized = false;
  let lastWholeHour = 0;
  let hourPopupTimer = null;

  const $ = (id) =>
    document.getElementById(id);

  function connect() {
    const proto =
      location.protocol === "https:"
        ? "wss"
        : "ws";

    ws = new WebSocket(
      `${proto}://${location.host}/dartmarathon/ws`
    );

    ws.onmessage = (event) => {
      const msg =
        JSON.parse(event.data);

      if (msg.type === "state") {
        render(msg.data);
      }
    };

    ws.onclose = () => {
      clearTimeout(retry);

      retry =
        setTimeout(
          connect,
          1200
        );
    };

    ws.onerror = () =>
      ws.close();
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

  function checkHourPopup(s) {
    const currentHour =
      Math.floor(
        s.stream_seconds / 3600
      );

    if (!initialized) {
      lastWholeHour =
        currentHour;

      initialized =
        true;

      return;
    }

    if (
      currentHour > lastWholeHour
      && currentHour > 0
    ) {
      showHourPopup(
        currentHour
      );
    }

    lastWholeHour =
      currentHour;
  }

  function showHourPopup(hours) {
    const popup =
      $("hourPopup");

    const number =
      $("hourPopupNumber");

    const text =
      $("hourPopupText");

    if (hours === 1) {
      number.textContent =
        "1 STUNDE!";

      text.textContent =
        "WIR SPIELEN BEREITS SEIT 1 STUNDE";
    } else {
      number.textContent =
        `${hours} STUNDEN!`;

      text.textContent =
        `WIR SPIELEN BEREITS SEIT ${hours} STUNDEN`;
    }

    popup.classList.remove(
      "hidden"
    );

    clearTimeout(
      hourPopupTimer
    );

    hourPopupTimer =
      setTimeout(
        () => {
          popup.classList.add(
            "hidden"
          );
        },
        15000
      );
  }

  function render(s) {
    $("ovTzmarty").textContent =
      `${s.legs.tzmarty} / ${s.player_special_totals.tzmarty}`;

    $("ovKorsar").textContent =
      `${s.legs.korsar} / ${s.player_special_totals.korsar}`;

    $("ovTotalLegs").textContent =
      s.total_legs;

    $("ovSpecials").textContent =
      s.total_specials;

    $("ovPause").textContent =
      s.pause_display;

    $("ovStream").textContent =
      s.stream_display;

    $("pauseCenterTime").textContent =
      s.pause_display;

    setPauseColor(
      $("ovPause"),
      s.pause_seconds
    );

    setPauseColor(
      $("pauseCenterTime"),
      s.pause_seconds
    );

    $("pauseCenter")
      .classList.toggle(
        "hidden",
        !s.pause_active
        || s.event_ended
      );

    $("eventEnded")
      .classList.toggle(
        "hidden",
        !s.event_ended
      );

    checkHourPopup(s);
  }

  connect();
})();
