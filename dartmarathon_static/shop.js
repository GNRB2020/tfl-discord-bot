(() => {
  let ws = null;
  let reconnectTimer = null;
  let latestShop = null;
  let paying = false;

  const $ = (id) => document.getElementById(id);
  const all = (selector) => [...document.querySelectorAll(selector)];

  function escapeHtml(value) {
    return String(value ?? "").replace(/[&<>'"]/g, (char) => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;"
    }[char]));
  }

  function euro(value) {
    return Number(value || 0).toLocaleString("de-DE", {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    }) + " €";
  }

  function duration(seconds) {
    const value = Math.max(0, Number(seconds || 0));
    const minutes = Math.floor(value / 60);
    const secs = Math.floor(value % 60);
    return `${String(minutes).padStart(2, "0")}:${String(secs).padStart(2, "0")}`;
  }

  function targetLabel(target) {
    return ({tzmarty:"Tzmarty", korsar:"Korsar", both:"Beide", general:"Allgemein", on_site:"Vor Ort"})[target] || "Allgemein";
  }

  function isLikelyDirectImage(url) {
    return /^https?:\/\//i.test(String(url || ""))
      && /\.(png|jpe?g|webp|gif|avif)(?:[?#].*)?$/i.test(String(url || ""));
  }

  function toast(text) {
    const el = $("shopToast");
    el.textContent = text;
    el.classList.remove("hidden");
    clearTimeout(el._timer);
    el._timer = setTimeout(() => el.classList.add("hidden"), 3500);
  }

  function render(shop) {
    if (!shop) return;
    latestShop = shop;
    $("shopEventTotal").textContent = euro(Number(shop.event_total_cents || 0) / 100);

    const paypal = $("paypalStatus");
    const testMode = Boolean(shop.test_mode);
    $("shopTestBanner").classList.toggle("hidden", !testMode);

    if (testMode) {
      paypal.textContent = "TESTMODUS · KEIN ECHTES GELD";
      paypal.className = "status-pill test";
    } else if (shop.paypal_configured) {
      paypal.textContent = shop.paypal_mode === "live" ? "PAYPAL LIVE" : "PAYPAL SANDBOX";
      paypal.className = "status-pill ok";
    } else {
      paypal.textContent = "PAYPAL NICHT KONFIGURIERT";
      paypal.className = "status-pill bad";
    }

    const items = Array.isArray(shop.items) ? shop.items : [];
    const container = $("shopItems");
    if (!items.length) {
      container.innerHTML = '<div class="empty-shop">Aktuell sind keine Foltershop-Artikel freigeschaltet. Spenden sind trotzdem möglich.</div>';
      return;
    }

    container.innerHTML = items.map((item) => {
      const meta = [];
      if (item.max_quantity > 0) meta.push(`Noch ${Math.max(0, Number(item.remaining || 0))} verfügbar`);
      else meta.push("Unbegrenzt");
      if (item.cooldown_seconds > 0) meta.push(`Cooldown ${Math.round(item.cooldown_seconds / 60)} Min.`);
      if (item.cooldown_remaining > 0) meta.push(`Wieder in ${duration(item.cooldown_remaining)}`);
      if (item.action_type === "pause_minus") {
        meta.push(`Pausendieb −${Math.round(Number(item.action_value || 0) / 60)} Min.`);
        meta.push("Nur kaufbar, wenn keine Pause läuft");
      }
      if (item.availability_reason && !item.available) meta.push(item.availability_reason);

      const image = isLikelyDirectImage(item.image_url)
        ? `<img class="item-image" src="${escapeHtml(item.image_url)}" alt="">`
        : "";

      return `
        <article class="item-card ${item.available ? "" : "unavailable"}">
          ${image}
          <div class="item-head">
            <div class="item-icon">${escapeHtml(item.icon || "🎯")}</div>
            <span class="target-badge">${escapeHtml(targetLabel(item.target))}</span>
          </div>
          <h3>${escapeHtml(item.name)}</h3>
          <p class="item-description">${escapeHtml(item.description || "")}</p>
          <div class="item-meta">${meta.map((x) => `<span class="meta-pill">${escapeHtml(x)}</span>`).join("")}</div>
          <div class="item-buy-row">
            <div class="item-price">${euro(Number(item.price_cents || 0) / 100)}</div>
            <button type="button" class="buy-button ${testMode ? "test-buy" : ""}" data-buy-item="${Number(item.id)}" ${item.available && (shop.paypal_configured || testMode) ? "" : "disabled"}>
              ${item.available
                ? (testMode ? "TESTKAUF AUSLÖSEN" : "MIT PAYPAL KAUFEN")
                : escapeHtml(item.availability_reason || "NICHT VERFÜGBAR")}
            </button>
          </div>
        </article>`;
    }).join("");

    all("[data-buy-item]").forEach((button) => {
      button.onclick = () => startPayment({kind:"item", item_id:Number(button.dataset.buyItem)});
    });

    all("[data-donate]").forEach((button) => {
      const amount = button.dataset.donate;
      button.textContent = testMode
        ? `${amount} € TEST`
        : `${amount} €`;
    });

    $("customDonateButton").textContent = testMode
      ? "TESTSPENDE AUSLÖSEN"
      : "MIT PAYPAL SPENDEN";
    $("customDonateButton").classList.toggle(
      "test-buy",
      testMode
    );
  }

  function connect() {
    clearTimeout(reconnectTimer);
    const proto = location.protocol === "https:" ? "wss" : "ws";
    ws = new WebSocket(`${proto}://${location.host}/dartmarathon/ws`);
    ws.onmessage = (event) => {
      let message;
      try { message = JSON.parse(event.data); } catch (_) { return; }
      if (message.type === "state") render(message.data?.shop);
    };
    ws.onclose = () => {
      reconnectTimer = setTimeout(connect, 1800);
    };
    ws.onerror = () => { try { ws.close(); } catch (_) {} };
  }

  async function startPayment(payload) {
    if (paying) return;
    const testMode = Boolean(latestShop?.test_mode);
    if (!testMode && !latestShop?.paypal_configured) {
      return toast("PayPal ist aktuell noch nicht konfiguriert.");
    }
    paying = true;
    try {
      const body = {
        ...payload,
        display_name: $("buyerName").value.trim(),
        message: $("buyerMessage").value.trim(),
      };
      const response = await fetch("/dartmarathon/shop/api/create-order", {
        method: "POST",
        headers: {"Content-Type":"application/json"},
        body: JSON.stringify(body),
      });
      const data = await response.json();
      if (!response.ok || !data.ok) {
        throw new Error(
          data.error
          || (testMode
            ? "Testkauf konnte nicht ausgelöst werden."
            : "PayPal-Zahlung konnte nicht gestartet werden.")
        );
      }

      if (data.test_completed) {
        toast(
          payload.kind === "item"
            ? "Testkauf erfolgreich simuliert."
            : "Testspende erfolgreich simuliert."
        );
        paying = false;
        return;
      }

      if (!data.approval_url) {
        throw new Error("PayPal-Zahlung konnte nicht gestartet werden.");
      }

      location.href = data.approval_url;
    } catch (error) {
      toast(error.message || "Zahlung konnte nicht gestartet werden.");
      paying = false;
    }
  }

  all("[data-donate]").forEach((button) => {
    button.onclick = () => startPayment({kind:"donation", amount:Number(button.dataset.donate)});
  });

  $("customDonateButton").onclick = () => {
    const amount = Number(String($("customDonation").value || "").replace(",", "."));
    if (!Number.isFinite(amount) || amount < 1) return toast("Bitte mindestens 1 € eingeben.");
    startPayment({kind:"donation", amount});
  };

  const params = new URLSearchParams(location.search);
  const payment = params.get("payment");
  if (payment) {
    const notice = $("paymentNotice");
    notice.classList.remove("hidden");
    if (payment === "success") {
      notice.className = "payment-notice success";
      notice.textContent = "Zahlung erfolgreich. Vielen Dank – die Aktion ist bereits im Stream und Control Center angekommen.";
    } else if (payment === "cancelled") {
      notice.className = "payment-notice warning";
      notice.textContent = "Die PayPal-Zahlung wurde abgebrochen.";
    } else if (payment === "pending") {
      notice.className = "payment-notice warning";
      notice.textContent = "PayPal verarbeitet die Zahlung noch. Sobald sie bestätigt ist, wird sie automatisch übernommen.";
    } else {
      notice.className = "payment-notice error";
      notice.textContent = "Die Zahlung konnte nicht abgeschlossen werden. Es wurde keine Shop-Aktion ausgelöst.";
    }
    history.replaceState({}, "", location.pathname);
  }

  connect();
})();
