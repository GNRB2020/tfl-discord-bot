(() => {
  let ws = null;
  let retryTimer = null;
  let popupTimer = null;
  let latestState = null;
  let pauseCycleTimer = null;
  let pauseCycleIndex = 0;
  let pauseAdIndex = 0;
  let pauseWasActive = false;

  const PAUSE_ADS = [
    {
      label:"KOALA DARTS",
      image:"/dartmarathon/static/ads/koala.png",
    },
    {
      label:"MALTESER",
      image:"/dartmarathon/static/ads/malteser.png",
    },
    {
      label:"FOLTERSHOP",
      image:"/dartmarathon/static/ads/foltershop.png",
    },
  ];

  const $ = (id) => document.getElementById(id);

  const LAYOUT_TARGETS = {
    tzmarty_score:"ovTzmarty",
    korsar_score:"ovKorsar",
    total_legs:"ovTotalLegs",
    total_specials:"ovSpecials",
    pause:"ovPause",
    event_money:"ovEventMoney",
    stream_time:"ovStream",
    support_ticker:"supportTicker",
    shop_banner:"shopActionPopup",
    pause_center_popup:"pauseCenterCard",
    ad_popup:"adPopupCard",
    recent_matches_popup:"recentPopupCard",
    specials_tzmarty_popup:"tzSpecialCard",
    specials_korsar_popup:"koSpecialCard",
    stats_popup:"statsPopupCard",
    pause_results_popup:"pauseResultsCard",
    pause_specials_popup:"pauseSpecialsCard",
    pause_supporters_popup:"pauseSupportersCard",
    pause_ad_popup:"pauseAdCard",
    event_final:"eventFinalCard",
  };

  function applyOverlayLayout(layout) {
    if (!layout || typeof layout !== "object") return;

    for (const [key, targetId] of Object.entries(LAYOUT_TARGETS)) {
      const element = $(targetId);
      const cfg = layout[key];

      if (!element || !cfg) continue;

      element.style.left = `${Number(cfg.x || 0)}px`;
      element.style.top = `${Number(cfg.y || 0)}px`;
      element.style.width = `${Number(cfg.w || 0)}px`;
      element.style.height = `${Number(cfg.h || 0)}px`;
      element.style.right = "auto";
      element.style.bottom = "auto";
      element.style.fontSize = `${Number(cfg.font || 16)}px`;
      element.style.visibility = cfg.visible === false
        ? "hidden"
        : "visible";

      const align = String(cfg.align || "center");
      const valign = String(cfg.valign || "center");

      element.style.textAlign = align;
      element.style.justifyContent = ({
        left:"flex-start",
        center:"center",
        right:"flex-end",
      })[align] || "center";

      element.style.alignItems = ({
        top:"flex-start",
        center:"center",
        bottom:"flex-end",
      })[valign] || "center";

      if (key === "support_ticker") {
        element.style.display = "flex";
      }

      if (key === "shop_banner") {
        element.style.justifyContent = "center";
        element.style.alignItems = "flex-start";

        const card = element.querySelector(
          ".shop-action-card"
        );

        if (card) {
          card.style.width = "100%";
          card.style.height = "100%";
        }
      }

      if (
        key.endsWith("_popup")
        || key === "event_final"
      ) {
        element.style.position = "absolute";
        element.style.minWidth = "0";
        element.style.maxWidth = "none";
        element.style.minHeight = "0";
        element.style.maxHeight = "none";
        element.style.boxSizing = "border-box";
        element.style.transform = "none";
        element.style.margin = "0";
      }
    }
  }

  function connect() {
    const proto = location.protocol === "https:" ? "wss" : "ws";

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
        render(message.data);
        return;
      }

      if (message.type === "ad_popup") {
        showAd(message);
        return;
      }

      if (message.type === "recent_matches_popup") {
        showRecentMatches(message);
        return;
      }

      if (message.type === "specials_popup") {
        showSpecials(message);
        return;
      }

      if (message.type === "stats_popup") {
        showStats(message);
      }
    };

    ws.onclose = () => {
      clearTimeout(retryTimer);
      retryTimer = setTimeout(connect, 1200);
    };

    ws.onerror = () => {
      try {
        ws.close();
      } catch (_) {
        // nichts zu tun
      }
    };
  }

  function hideAllPopups() {
    for (const id of [
      "adPopup",
      "recentPopup",
      "specialsPopup",
      "statsPopup",
    ]) {
      $(id).classList.add("hidden");
    }

    clearTimeout(popupTimer);
    popupTimer = null;
  }

  function displayPopup(id, durationMs) {
    hideAllPopups();

    $(id).classList.remove("hidden");

    popupTimer = setTimeout(
      () => {
        $(id).classList.add("hidden");
      },
      Number(durationMs) || 20000
    );
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

  function formatNumber(value, digits) {
    return Number(value || 0).toLocaleString(
      "de-DE",
      {
        minimumFractionDigits: digits,
        maximumFractionDigits: digits,
      }
    );
  }

  function matchBalance(state) {
    const tzmarty = Number(
      state.match_wins?.tzmarty || 0
    );
    const korsar = Number(
      state.match_wins?.korsar || 0
    );
    const draws = Number(
      state.match_draws || 0
    );

    return (
      `${tzmarty} : ${korsar}`
      + (draws > 0 ? ` · ${draws} U` : "")
    );
  }

  function renderFinalSpecialList(id, detail) {
    const lines = detailLines(detail);

    $(id).innerHTML = lines.length
      ? lines.map(
          ([label, value]) => (
            '<div class="final-special-row">'
            + `<span>${escapeHtml(label)}</span>`
            + `<strong>${escapeHtml(value)}</strong>`
            + "</div>"
          )
        ).join("")
      : '<div class="final-empty">Keine Specials</div>';
  }

  function renderFinalStats(state) {
    $("endStreamTime").textContent = (
      state.stream_display || "00:00:00"
    );

    $("endMatches").textContent = Number(
      state.match_count || 0
    );

    $("endMatchBalance").textContent = (
      matchBalance(state)
    );

    $("endLegs").textContent = Number(
      state.total_legs || 0
    );

    $("endSpecials").textContent = Number(
      state.total_specials || 0
    );

    $("endPauseUsed").textContent = (
      state.pause_used_display || "00:00:00"
    );

    $("endDonations").textContent = (
      `${(Number(state.shop?.event_total_cents || 0) / 100).toLocaleString(
        "de-DE",
        {
          minimumFractionDigits: 2,
          maximumFractionDigits: 2,
        }
      )} €`
    );

    $("endAvgLegs").textContent = formatNumber(
      state.avg_legs_per_match,
      1
    );

    $("endAvgSpecials").textContent = formatNumber(
      state.avg_specials_per_match,
      1
    );

    $("endSpecialsPerLeg").textContent = formatNumber(
      state.specials_per_leg,
      2
    );

    $("endLegsPerHour").textContent = formatNumber(
      state.legs_per_hour,
      1
    );

    $("endSpecialsPerHour").textContent = formatNumber(
      state.specials_per_hour,
      1
    );

    $("endTzScore").textContent = (
      `${Number(state.legs?.tzmarty || 0)} Legs · `
      + `${Number(state.player_special_totals?.tzmarty || 0)} Specials`
    );

    $("endKoScore").textContent = (
      `${Number(state.legs?.korsar || 0)} Legs · `
      + `${Number(state.player_special_totals?.korsar || 0)} Specials`
    );

    renderFinalSpecialList(
      "endTzSpecialDetail",
      state.special_detail?.tzmarty || {}
    );

    renderFinalSpecialList(
      "endKoSpecialDetail",
      state.special_detail?.korsar || {}
    );
  }

  function pauseMatchRow(match) {
    const mode = String(
      match?.mode_label
      || match?.mode
      || "Match"
    );

    const result = String(
      match?.result_text
      || ""
    );

    const specialTotal = Number(
      match?.special_total || 0
    );

    return (
      '<div class="pause-result-row">'
      + `<span class="pause-result-id">#${Number(match?.id || 0)}</span>`
      + `<span class="pause-result-mode">${escapeHtml(mode)}</span>`
      + `<strong class="pause-result-score">${escapeHtml(result)}</strong>`
      + `<span class="pause-result-specials">${specialTotal} Sp.</span>`
      + "</div>"
    );
  }

  function pauseSpecialRows(detail) {
    const lines = detailLines(detail);

    if (!lines.length) {
      return (
        '<div class="pause-extra-empty">'
        + "Noch keine Specials."
        + "</div>"
      );
    }

    return lines.map(
      ([label, value]) => (
        '<div class="pause-special-row">'
        + `<span>${escapeHtml(label)}</span>`
        + `<strong>${escapeHtml(value)}</strong>`
        + "</div>"
      )
    ).join("");
  }

  function renderPauseResultsAndSpecials(state) {
    const matches = Array.isArray(state?.matches)
      ? [...state.matches].reverse()
      : [];

    $("pauseResultsTrack").innerHTML = matches.length
      ? matches.map(pauseMatchRow).join("")
      : (
          '<div class="pause-extra-empty">'
          + "Noch keine Matches gespeichert."
          + "</div>"
        );

    $("pauseTzSpecialTotal").textContent = Number(
      state?.player_special_totals?.tzmarty || 0
    );

    $("pauseKoSpecialTotal").textContent = Number(
      state?.player_special_totals?.korsar || 0
    );

    $("pauseTzSpecials").innerHTML = pauseSpecialRows(
      state?.special_detail?.tzmarty || {}
    );

    $("pauseKoSpecials").innerHTML = pauseSpecialRows(
      state?.special_detail?.korsar || {}
    );

    requestAnimationFrame(() => {
      const viewport = $("pauseResultsViewport");
      const track = $("pauseResultsTrack");

      track.classList.remove("scrolling");
      track.style.animationDuration = "";

      const overflow = Math.max(
        0,
        track.scrollHeight - viewport.clientHeight
      );

      if (overflow > 8) {
        const duration = Math.max(
          10,
          Math.min(
            34,
            7 + matches.length * 1.05
          )
        );

        track.style.setProperty(
          "--pause-result-distance",
          `${overflow}px`
        );

        track.style.animationDuration =
          `${duration}s`;

        void track.offsetWidth;
        track.classList.add("scrolling");
      }
    });
  }

  function pauseOrderRows(state) {
    const shop = state?.shop || {};
    const orders = Array.isArray(shop.orders)
      ? [...shop.orders].reverse()
      : [];

    const paid = orders.filter(
      (order) => Number(order?.amount_cents || 0) > 0
    );

    const rows = paid.map((order) => {
      const name = String(
        order?.display_name || "Anonym"
      );

      const amount = (
        Number(order?.amount_cents || 0) / 100
      ).toLocaleString(
        "de-DE",
        {
          minimumFractionDigits:2,
          maximumFractionDigits:2,
        }
      ) + " €";

      const action = order?.kind === "item"
        ? String(order?.item_name || "Foltershop")
        : "Spende";

      return {
        name,
        action,
        amount,
      };
    });

    const own = Number(
      state?.own_donations || 0
    );

    if (own > 0) {
      rows.push({
        name:"Tzmarty & Korsar",
        action:"Eigene Spenden",
        amount:own.toLocaleString(
          "de-DE",
          {
            minimumFractionDigits:2,
            maximumFractionDigits:2,
          }
        ) + " €",
      });
    }

    return rows;
  }

  function renderPauseSupporters(state) {
    const rows = pauseOrderRows(state);
    const track = $("pauseSupportersTrack");

    track.innerHTML = rows.length
      ? rows.map(
          (row) => (
            '<div class="pause-credit-row">'
            + `<strong>${escapeHtml(row.name)}</strong>`
            + `<span>${escapeHtml(row.action)}</span>`
            + `<b>${escapeHtml(row.amount)}</b>`
            + "</div>"
          )
        ).join("")
      : (
          '<div class="pause-extra-empty pause-credit-empty">'
          + "Noch keine Käufer oder Spender."
          + "</div>"
        );

    requestAnimationFrame(() => {
      const viewport = $("pauseSupportersViewport");

      track.classList.remove("scrolling");

      const trackHeight = Math.max(
        track.scrollHeight,
        80
      );

      const duration = Math.max(
        12,
        Math.min(
          38,
          8 + rows.length * 1.8
        )
      );

      track.style.setProperty(
        "--pause-credit-start",
        `${viewport.clientHeight}px`
      );

      track.style.setProperty(
        "--pause-credit-end",
        `${trackHeight}px`
      );

      track.style.animationDuration =
        `${duration}s`;

      void track.offsetWidth;
      track.classList.add("scrolling");
    });

    return Math.max(
      12000,
      Math.min(
        38000,
        (8 + rows.length * 1.8) * 1000
      )
    );
  }

  function hidePauseViews() {
    for (const id of [
      "pauseResultsSpecials",
      "pauseSupporters",
      "pauseAd",
    ]) {
      $(id).classList.add("hidden");
    }
  }

  function showPauseAd() {
    const ad = PAUSE_ADS[
      pauseAdIndex % PAUSE_ADS.length
    ];

    pauseAdIndex = (
      pauseAdIndex + 1
    ) % PAUSE_ADS.length;

    $("pauseAdKicker").textContent =
      ad.label;

    $("pauseAdImage").src =
      `${ad.image}?v=6.6.0`;

    $("pauseAdImage").alt =
      ad.label;

    $("pauseAd").classList.remove(
      "hidden"
    );
  }

  function scheduleNextPauseView(
    delayMs
  ) {
    clearTimeout(pauseCycleTimer);

    pauseCycleTimer = setTimeout(
      () => {
        if (
          latestState?.pause_active
          && !latestState?.event_ended
        ) {
          showNextPauseView();
        }
      },
      delayMs
    );
  }

  function showNextPauseView() {
    if (
      !latestState?.pause_active
      || latestState?.event_ended
    ) {
      return;
    }

    hidePauseViews();

    const mode = pauseCycleIndex % 3;
    pauseCycleIndex += 1;

    if (mode === 0) {
      renderPauseResultsAndSpecials(
        latestState
      );

      $("pauseResultsSpecials").classList.remove(
        "hidden"
      );

      const matchCount = Array.isArray(
        latestState?.matches
      )
        ? latestState.matches.length
        : 0;

      scheduleNextPauseView(
        Math.max(
          15000,
          Math.min(
            36000,
            (9 + matchCount * 1.05) * 1000
          )
        )
      );

      return;
    }

    if (mode === 1) {
      const duration = renderPauseSupporters(
        latestState
      );

      $("pauseSupporters").classList.remove(
        "hidden"
      );

      scheduleNextPauseView(
        duration
      );

      return;
    }

    showPauseAd();

    scheduleNextPauseView(
      14000
    );
  }

  function updatePauseExtras(state) {
    latestState = state;

    const active = Boolean(
      state?.pause_active
      && !state?.event_ended
    );

    $("pauseExtras").classList.toggle(
      "hidden",
      !active
    );

    if (!active) {
      clearTimeout(pauseCycleTimer);
      pauseCycleTimer = null;
      pauseWasActive = false;
      pauseCycleIndex = 0;
      hidePauseViews();
      return;
    }

    if (!pauseWasActive) {
      pauseWasActive = true;
      pauseCycleIndex = 0;
      showNextPauseView();
    }
  }

  function render(state) {
    if (!state) return;

    applyOverlayLayout(
      state.overlay_layout
    );

    $("ovTzmarty").textContent = (
      `${Number(state.legs?.tzmarty || 0)}`
      + " / "
      + `${Number(state.player_special_totals?.tzmarty || 0)}`
    );

    $("ovKorsar").textContent = (
      `${Number(state.legs?.korsar || 0)}`
      + " / "
      + `${Number(state.player_special_totals?.korsar || 0)}`
    );

    $("ovTotalLegs").textContent = Number(
      state.total_legs || 0
    );

    $("ovSpecials").textContent = Number(
      state.total_specials || 0
    );

    $("ovPause").textContent = (
      state.pause_display || "15:00"
    );

    $("ovStream").textContent = (
      state.stream_display || "00:00:00"
    );

    $("pauseCenterTime").textContent = (
      state.pause_display || "15:00"
    );

    setPauseColor(
      $("ovPause"),
      Number(state.pause_seconds || 0)
    );

    setPauseColor(
      $("pauseCenterTime"),
      Number(state.pause_seconds || 0)
    );

    $("pauseCenter").classList.toggle(
      "hidden",
      !state.pause_active
      || state.event_ended
    );

    updatePauseExtras(state);

    const supportTicker = $("supportTicker");
    if (supportTicker) {
      supportTicker.classList.toggle(
        "hidden",
        Boolean(state.event_ended)
      );
    }

    renderFinalStats(state);

    $("eventEnded").classList.toggle(
      "hidden",
      !state.event_ended
    );
  }

  function showAd(message) {
    const image = $("adPopupImage");

    image.src = (
      `${message.image}?v=6.0.0&t=${Date.now()}`
    );

    image.alt = (
      message.label
      || "Werbeeinblendung"
    );

    displayPopup(
      "adPopup",
      message.duration_ms
    );
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

  function showRecentMatches(message) {
    const matches = Array.isArray(
      message.matches
    )
      ? message.matches
      : [];

    const container = $("recentMatchesList");

    if (!matches.length) {
      container.innerHTML = (
        '<div class="popup-empty">'
        + "Noch keine Matches gespeichert."
        + "</div>"
      );
    } else {
      container.innerHTML = matches.map(
        (match) => (
          '<div class="recent-row">'
          + `<span class="id">#${Number(match.id)}</span>`
          + `<span class="mode">${escapeHtml(match.mode)}</span>`
          + `<span class="result">${escapeHtml(match.result)}</span>`
          + "</div>"
        )
      ).join("");
    }

    displayPopup(
      "recentPopup",
      message.duration_ms
    );
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

  function detailLines(detail) {
    const safe = detail || {};
    const lines = [];

    if (safe.hf?.length) {
      lines.push([
        "HF",
        compactValueList(safe.hf),
      ]);
    }

    if (safe.bf?.length) {
      lines.push([
        "BF",
        compactValueList(safe.bf),
      ]);
    }

    for (const key of [
      "180",
      "177",
      "174",
      "171",
    ]) {
      if (Number(safe[key] || 0) > 0) {
        lines.push([
          key,
          `× ${Number(safe[key])}`,
        ]);
      }
    }

    if (safe.ld?.length) {
      lines.push([
        "LD",
        compactValueList(safe.ld),
      ]);
    }

    if (Number(safe.legacy || 0) > 0) {
      lines.push([
        "ALT",
        Number(safe.legacy),
      ]);
    }

    return lines;
  }

  function renderSpecialCard(id, detail) {
    const lines = detailLines(detail);

    $(id).innerHTML = lines.length
      ? lines.map(
          ([label, value]) => (
            '<div class="special-popup-row">'
            + `<span>${escapeHtml(label)}</span>`
            + `<strong>${escapeHtml(value)}</strong>`
            + "</div>"
          )
        ).join("")
      : (
          '<div class="popup-empty">'
          + "Noch keine Specials."
          + "</div>"
        );
  }

  function showSpecials(message) {
    const tzmarty = (
      message.players?.tzmarty
      || {}
    );

    const korsar = (
      message.players?.korsar
      || {}
    );

    $("tzSpecialTitle").textContent = (
      `TZMARTY · ${Number(tzmarty.total || 0)}`
    );

    $("koSpecialTitle").textContent = (
      `KORSAR · ${Number(korsar.total || 0)}`
    );

    renderSpecialCard(
      "tzSpecialPopup",
      tzmarty
    );

    renderSpecialCard(
      "koSpecialPopup",
      korsar
    );

    displayPopup(
      "specialsPopup",
      message.duration_ms
    );
  }

  function showStats(message) {
    const stats = (
      message.stats || {}
    );

    $("statsPopupTitle").textContent = (
      message.title
      || "EVENT-KENNZAHLEN"
    );
    $("popMatches").textContent = Number(
      stats.match_count || 0
    );

    const tzmartyWins = Number(
      stats.match_wins?.tzmarty || 0
    );

    const korsarWins = Number(
      stats.match_wins?.korsar || 0
    );

    const draws = Number(
      stats.match_draws || 0
    );

    $("popMatchBalance").textContent = (
      `${tzmartyWins} : ${korsarWins}`
      + (draws > 0 ? ` · ${draws} U` : "")
    );

    $("popAvgLegsMatch").textContent = Number(
      stats.avg_legs_per_match || 0
    ).toLocaleString(
      "de-DE",
      {
        minimumFractionDigits: 1,
        maximumFractionDigits: 1,
      }
    );

    $("popAvgSpecialsMatch").textContent = Number(
      stats.avg_specials_per_match || 0
    ).toLocaleString(
      "de-DE",
      {
        minimumFractionDigits: 1,
        maximumFractionDigits: 1,
      }
    );


    $("popLegs").textContent = Number(
      stats.total_legs || 0
    );

    $("popSpecials").textContent = Number(
      stats.total_specials || 0
    );

    $("popSpecialsPerLeg").textContent = Number(
      stats.specials_per_leg || 0
    ).toLocaleString(
      "de-DE",
      {
        minimumFractionDigits: 2,
        maximumFractionDigits: 2,
      }
    );

    $("popLegsPerHour").textContent = Number(
      stats.legs_per_hour || 0
    ).toLocaleString(
      "de-DE",
      {
        minimumFractionDigits: 1,
        maximumFractionDigits: 1,
      }
    );

    $("popSpecialsPerHour").textContent = Number(
      stats.specials_per_hour || 0
    ).toLocaleString(
      "de-DE",
      {
        minimumFractionDigits: 1,
        maximumFractionDigits: 1,
      }
    );

    $("popPauseUsed").textContent = (
      stats.pause_used_display
      || "00:00:00"
    );

    displayPopup(
      "statsPopup",
      message.duration_ms
    );
  }

  connect();
})();
