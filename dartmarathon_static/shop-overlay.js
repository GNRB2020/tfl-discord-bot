(() => {
  let ws = null;
  let retryTimer = null;
  let popupTimer = null;
  let supporterSignature = "";

  const $ = (id) => document.getElementById(id);

  function escapeHtml(value) {
    return String(value ?? "").replace(/[&<>'"]/g, (char) => ({
      "&":"&amp;", "<":"&lt;", ">":"&gt;", "'":"&#39;", '"':"&quot;"
    }[char]));
  }

  function euro(cents) {
    return (Number(cents || 0) / 100).toLocaleString("de-DE", {
      minimumFractionDigits:2,
      maximumFractionDigits:2,
    }) + " €";
  }

  function renderSupporters(shop) {
    $("ovEventMoney").textContent = euro(shop?.event_total_cents || 0);
    const supporters = Array.isArray(shop?.supporters) ? shop.supporters : [];
    const signature = supporters.map((s) => `${s.name}:${s.amount_cents}`).join("|");
    if (signature === supporterSignature) return;
    supporterSignature = signature;
    const setHtml = supporters.length
      ? supporters.map((supporter) => `<span class="support-entry">${escapeHtml(supporter.name)} <b>${euro(supporter.amount_cents)}</b></span>`).join("")
      : '<span class="support-empty">FOLTERSHOP & SPENDENTOPF · NOCH KEINE UNTERSTÜTZER</span>';
    $("supportTrack").innerHTML = `<div class="support-set">${setHtml}</div><div class="support-set" aria-hidden="true">${setHtml}</div>`;
    $("supportTrack").style.animation = "none";
    void $("supportTrack").offsetWidth;
    $("supportTrack").style.animation = "";
  }

  function showShopPopup(message) {
    clearTimeout(popupTimer);
    const donation = message.type === "shop_donation_popup";
    $("shopActionKicker").textContent = donation ? "SPENDE" : "FOLTERSHOP-KAUF";
    $("shopActionAmount").textContent = `${Number(message.amount || 0).toLocaleString("de-DE", {minimumFractionDigits:2, maximumFractionDigits:2})} €`;
    $("shopActionTitle").textContent = donation ? "VIELEN DANK!" : (message.item_name || "FOLTERSHOP");
    $("shopActionText").textContent = donation
      ? "Unterstützung für den Dartmarathon-Spendentopf"
      : (message.stream_text || message.item_name || "Neue Foltershop-Aufgabe");
    $("shopActionBuyer").textContent = `von ${message.name || "Anonym"}`;
    const messageBox = $("shopActionMessage");
    if (message.message) {
      messageBox.textContent = `„${message.message}“`;
      messageBox.classList.remove("hidden");
    } else {
      messageBox.textContent = "";
      messageBox.classList.add("hidden");
    }
    $("shopActionPopup").classList.remove("hidden");
    popupTimer = setTimeout(() => $("shopActionPopup").classList.add("hidden"), Number(message.duration_ms) || 20000);
  }

  function connect() {
    clearTimeout(retryTimer);
    const proto = location.protocol === "https:" ? "wss" : "ws";
    ws = new WebSocket(`${proto}://${location.host}/dartmarathon/ws`);
    ws.onmessage = (event) => {
      let message;
      try { message = JSON.parse(event.data); } catch (_) { return; }
      if (message.type === "state") renderSupporters(message.data?.shop || {});
      if (message.type === "shop_purchase_popup" || message.type === "shop_donation_popup") showShopPopup(message);
    };
    ws.onclose = () => { retryTimer = setTimeout(connect, 1200); };
    ws.onerror = () => { try { ws.close(); } catch (_) {} };
  }

  connect();
})();
