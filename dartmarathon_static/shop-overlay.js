(() => {
  let ws = null;
  let retryTimer = null;
  let supporterSignature = "";
  let supporterHtml = "";
  let tickerLayoutSignature = "";
  let tickerRebuildTimer = null;
  let bannerTimer = null;
  let bannerBusy = false;
  const bannerQueue = [];

  const $ = (id) => document.getElementById(id);

  function escapeHtml(value) {
    return String(value ?? "").replace(/[&<>'"]/g, (char) => ({
      "&":"&amp;",
      "<":"&lt;",
      ">":"&gt;",
      "'":"&#39;",
      '"':"&quot;",
    }[char]));
  }

  function euro(cents) {
    return (Number(cents || 0) / 100).toLocaleString("de-DE", {
      minimumFractionDigits:2,
      maximumFractionDigits:2,
    }) + " €";
  }

  function buildSupportTicker() {
    const ticker = $("supportTicker");
    const track = $("supportTrack");

    if (!ticker || !track || !supporterHtml) return;

    clearTimeout(tickerRebuildTimer);

    track.classList.remove("ticker-running");
    track.style.animation = "none";
    track.innerHTML = (
      `<div class="support-set support-master">${supporterHtml}</div>`
    );

    requestAnimationFrame(() => {
      const master = track.querySelector(".support-master");
      if (!master) return;

      const viewportWidth = Math.max(
        1,
        ticker.getBoundingClientRect().width
      );

      const masterWidth = Math.max(
        1,
        master.getBoundingClientRect().width
      );

      // Immer genug Kopien hintereinander, sodass auch bei 1920px Breite
      // niemals eine Lücke bzw. ein sichtbarer Neustart in der Mitte entsteht.
      const copies = Math.max(
        3,
        Math.ceil(viewportWidth / masterWidth) + 3
      );

      track.innerHTML = Array.from(
        {length:copies},
        (_, index) => (
          `<div class="support-set" ${index ? 'aria-hidden="true"' : ''}>${supporterHtml}</div>`
        )
      ).join("");

      // Exakt um die Breite EINER Kopie verschieben. Da alle Kopien gleich
      // sind, ist der Sprung am Animationsende optisch unsichtbar.
      track.style.setProperty(
        "--support-shift",
        `${masterWidth}px`
      );

      // Konstante Lesegeschwindigkeit statt fixer Laufzeit.
      const pixelsPerSecond = 62;
      const duration = Math.max(
        8,
        masterWidth / pixelsPerSecond
      );

      track.style.setProperty(
        "--support-duration",
        `${duration.toFixed(2)}s`
      );

      track.style.animation = "";
      void track.offsetWidth;
      track.classList.add("ticker-running");
    });
  }

  function scheduleTickerRebuild() {
    clearTimeout(tickerRebuildTimer);
    tickerRebuildTimer = setTimeout(
      buildSupportTicker,
      80
    );
  }

  function renderSupporters(shop, tickerLayout) {
    $("ovEventMoney").textContent = euro(
      shop?.event_total_cents || 0
    );

    const supporters = Array.isArray(shop?.supporters)
      ? shop.supporters
      : [];

    const signature = supporters
      .map((supporter) => `${supporter.name}:${supporter.amount_cents}`)
      .join("|");

    const layoutSignature = JSON.stringify(
      tickerLayout || {}
    );

    if (
      signature === supporterSignature
      && layoutSignature === tickerLayoutSignature
    ) {
      return;
    }

    supporterSignature = signature;
    tickerLayoutSignature = layoutSignature;

    supporterHtml = supporters.length
      ? supporters.map(
          (supporter) =>
            `<span class="support-entry">${escapeHtml(supporter.name)} <b>${euro(supporter.amount_cents)}</b></span>`
        ).join("")
      : '<span class="support-empty">FOLTERSHOP &amp; SPENDENTOPF · NOCH KEINE UNTERSTÜTZER</span>';

    scheduleTickerRebuild();
  }


  function enqueueShopBanner(message) {
    bannerQueue.push(message);
    showNextShopBanner();
  }

  function showNextShopBanner() {
    if (bannerBusy || !bannerQueue.length) return;

    bannerBusy = true;
    const message = bannerQueue.shift();
    const donation =
      message.type === "shop_donation_popup";

    const popup = $("shopActionPopup");
    popup.classList.remove(
      "hidden",
      "donation",
      "purchase",
      "leaving"
    );
    popup.classList.add(
      donation ? "donation" : "purchase"
    );

    $("shopActionKicker").textContent =
      donation ? "SPENDE" : "FOLTERSHOP";

    $("shopActionAmount").textContent =
      `${Number(message.amount || 0).toLocaleString(
        "de-DE",
        {
          minimumFractionDigits:2,
          maximumFractionDigits:2,
        }
      )} €`;

    $("shopActionTitle").textContent =
      donation
        ? "Vielen Dank für deine Unterstützung!"
        : (message.item_name || "Neue Foltershop-Aktion");

    $("shopActionText").textContent =
      donation
        ? "für den gemeinsamen Dartmarathon-Spendentopf"
        : (
            message.stream_text
            || message.item_name
            || "Neue Foltershop-Aufgabe"
          );

    $("shopActionBuyer").textContent =
      message.name && message.name !== "Anonym"
        ? `von ${message.name}`
        : "anonym";

    const messageBox = $("shopActionMessage");

    if (message.message) {
      messageBox.textContent = `„${message.message}“`;
      messageBox.classList.remove("hidden");
    } else {
      messageBox.textContent = "";
      messageBox.classList.add("hidden");
    }

    clearTimeout(bannerTimer);

    bannerTimer = setTimeout(() => {
      popup.classList.add("leaving");

      setTimeout(() => {
        popup.classList.add("hidden");
        popup.classList.remove(
          "leaving",
          "donation",
          "purchase"
        );
        bannerBusy = false;
        showNextShopBanner();
      }, 360);
    }, Number(message.duration_ms) || (donation ? 10000 : 15000));
  }

  function connect() {
    clearTimeout(retryTimer);

    const proto =
      location.protocol === "https:"
        ? "wss"
        : "ws";

    ws = new WebSocket(
      `${proto}://${location.host}/dartmarathon/ws`
    );

    ws.onmessage = (event) => {
      let message;

      try {
        message = JSON.parse(event.data);
      } catch (_) {
        return;
      }

      if (message.type === "state") {
        const state = message.data || {};

        renderSupporters(
          state.shop || {},
          state.overlay_layout?.support_ticker || {}
        );

        const ticker = $("supportTicker");
        if (ticker) {
          ticker.classList.toggle(
            "hidden",
            Boolean(state.event_ended)
          );
        }
      }

      if (
        message.type === "shop_purchase_popup"
        || message.type === "shop_donation_popup"
      ) {
        enqueueShopBanner(message);
      }
    };

    ws.onclose = () => {
      retryTimer = setTimeout(
        connect,
        1200
      );
    };

    ws.onerror = () => {
      try {
        ws.close();
      } catch (_) {}
    };
  }

  if (typeof ResizeObserver !== "undefined") {
    const tickerObserver = new ResizeObserver(() => {
      if (supporterHtml) {
        scheduleTickerRebuild();
      }
    });

    const ticker = $("supportTicker");
    if (ticker) {
      tickerObserver.observe(ticker);
    }
  }

  connect();
})();
