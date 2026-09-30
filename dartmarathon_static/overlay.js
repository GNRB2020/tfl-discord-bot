(() => {
  let ws = null;
  let retryTimer = null;
  let popupTimer = null;

  const $ = (id) => document.getElementById(id);

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
      `${Number(state.own_donations || 0).toLocaleString(
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

  function render(state) {
    if (!state) return;

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

    renderFinalStats(state);

    $("eventEnded").classList.toggle(
      "hidden",
      !state.event_ended
    );
  }

  function showAd(message) {
    const image = $("adPopupImage");

    image.src = (
      `${message.image}?v=5.3.0&t=${Date.now()}`
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
