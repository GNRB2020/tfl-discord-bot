(() => {
  let ws = null;
  let reconnectTimer = null;
  let latestShop = null;
  let paying = false;
  let lastItemsSignature = "";
  let shopFilter = "all";
  let shopSearch = "";
  const failedImages = new Set();

  const $ = (id) => document.getElementById(id);
  const all = (selector) => [...document.querySelectorAll(selector)];

  function escapeHtml(value) {
    return String(value ?? "").replace(/[&<>'"]/g, (char) => ({
      "&": "&amp;",
      "<": "&lt;",
      ">": "&gt;",
      "'": "&#39;",
      '"': "&quot;",
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
    return ({
      tzmarty:"Tzmarty",
      korsar:"Korsar",
      both:"Beide",
      general:"Allgemein",
      on_site:"Vor Ort",
    })[target] || "Allgemein";
  }

  function toast(text) {
    const el = $("shopToast");
    el.textContent = text;
    el.classList.remove("hidden");
    clearTimeout(el._timer);
    el._timer = setTimeout(
      () => el.classList.add("hidden"),
      3500
    );
  }

  function imageKey(item) {
    return [
      Number(item.id),
      String(item.updated_at || ""),
      String(item.image_url || ""),
    ].join(":");
  }

  function structuralItemsSignature(items, testMode, paypalConfigured) {
    return JSON.stringify(
      (Array.isArray(items) ? items : []).map((item) => ({
        id:Number(item.id),
        name:String(item.name || ""),
        description:String(item.description || ""),
        price_cents:Number(item.price_cents || 0),
        max_quantity:Number(item.max_quantity || 0),
        sold_count:Number(item.sold_count || 0),
        remaining:item.remaining === null ? null : Number(item.remaining || 0),
        cooldown_seconds:Number(item.cooldown_seconds || 0),
        target:String(item.target || ""),
        icon:String(item.icon || ""),
        image_url:String(item.image_url || ""),
        updated_at:String(item.updated_at || ""),
        action_type:String(item.action_type || ""),
        action_value:Number(item.action_value || 0),
        available:Boolean(item.available),
        availability_reason:String(item.availability_reason || ""),
        testMode:Boolean(testMode),
        paypalConfigured:Boolean(paypalConfigured),
      }))
    );
  }

  function bindItemImages() {
    all("[data-shop-image]").forEach((image) => {
      const key = image.dataset.shopImage || "";

      image.addEventListener("load", () => {
        const media = image.closest(".item-media");
        if (media) {
          media.classList.add("image-loaded");
          media.classList.remove("image-failed");
        }
      }, {once:true});

      image.addEventListener("error", () => {
        if (key) failedImages.add(key);
        const media = image.closest(".item-media");
        if (media) {
          media.classList.add("image-failed");
          media.classList.remove("image-loaded");
        }
        image.remove();
      }, {once:true});
    });
  }

  function updateDynamicItemValues(items) {
    for (const item of (Array.isArray(items) ? items : [])) {
      const cooldown = document.querySelector(
        `[data-cooldown-item="${Number(item.id)}"]`
      );
      if (!cooldown) continue;

      const remaining = Number(item.cooldown_remaining || 0);
      cooldown.textContent = remaining > 0
        ? `Wieder in ${duration(remaining)}`
        : "";
      cooldown.classList.toggle("hidden", remaining <= 0);
    }
  }

  function visibleItems(items) {
    const term = shopSearch.trim().toLocaleLowerCase("de-DE");

    return (Array.isArray(items) ? items : []).filter((item) => {
      if (shopFilter === "available" && !item.available) {
        return false;
      }

      if (
        shopFilter === "pause"
        && item.action_type !== "pause_minus"
      ) {
        return false;
      }

      if (!term) {
        return true;
      }

      const haystack = [
        item.name,
        item.description,
        targetLabel(item.target),
        item.action_type === "pause_minus" ? "Pausendieb" : "",
      ]
        .join(" ")
        .toLocaleLowerCase("de-DE");

      return haystack.includes(term);
    });
  }

  function updateResultCount(visible, total) {
    const el = $("shopResultCount");
    if (!el) return;

    el.textContent = visible === total
      ? `${total} Artikel`
      : `${visible} von ${total}`;
  }

  function renderItems(shop, testMode) {
    const allItems = Array.isArray(shop.items) ? shop.items : [];
    const items = visibleItems(allItems);
    const container = $("shopItems");

    updateResultCount(items.length, allItems.length);

    if (!items.length) {
      const emptySignature = `EMPTY:${shopFilter}:${shopSearch}:${allItems.length}`;

      if (lastItemsSignature !== emptySignature) {
        container.innerHTML = allItems.length
          ? '<div class="empty-shop compact-empty-shop">Keine Artikel passen zum aktuellen Filter.</div>'
          : '<div class="empty-shop compact-empty-shop">Aktuell sind keine Foltershop-Artikel freigeschaltet. Spenden sind trotzdem möglich.</div>';

        lastItemsSignature = emptySignature;
      }

      return;
    }

    const signature = [
      structuralItemsSignature(
        items,
        testMode,
        shop.paypal_configured
      ),
      shopFilter,
      shopSearch,
    ].join("|");

    if (signature === lastItemsSignature) {
      updateDynamicItemValues(items);
      return;
    }

    lastItemsSignature = signature;

    container.innerHTML = items.map((item) => {
      const meta = [];

      if (item.max_quantity > 0) {
        meta.push(
          `Noch ${Math.max(0, Number(item.remaining || 0))} verfügbar`
        );
      } else {
        meta.push("Unbegrenzt");
      }

      if (item.cooldown_seconds > 0) {
        meta.push(
          `Cooldown ${Math.round(Number(item.cooldown_seconds) / 60)} Min.`
        );
      }

      if (item.action_type === "pause_minus") {
        meta.push(
          `−${Math.round(Number(item.action_value || 0) / 60)} Min. Pause`
        );
      }

      if (item.availability_reason && !item.available) {
        meta.push(item.availability_reason);
      }

      const key = imageKey(item);
      const tryImage = Boolean(item.image_url) && !failedImages.has(key);

      const imageHtml = tryImage
        ? (
            `<img class="item-media-image" `
            + `loading="lazy" decoding="async" `
            + `data-shop-image="${escapeHtml(key)}" `
            + `src="/dartmarathon/shop/image/${Number(item.id)}?v=${encodeURIComponent(String(item.updated_at || item.id))}" `
            + `alt="${escapeHtml(item.name)}">`
          )
        : "";

      return `
        <article class="item-card ${item.available ? "" : "unavailable"}" data-item-id="${Number(item.id)}">
          <div class="item-media ${tryImage ? "has-image-source" : "image-failed"}">
            <div class="item-media-fallback">
              <span>${escapeHtml(item.icon || "🎯")}</span>
            </div>
            ${imageHtml}
            <span class="item-media-target">${escapeHtml(targetLabel(item.target))}</span>
          </div>

          <div class="item-card-body">
            <h3>${escapeHtml(item.name)}</h3>
            <p class="item-description">${escapeHtml(item.description || "")}</p>

            <div class="item-meta">
              ${meta.map(
                (entry) => `<span class="meta-pill">${escapeHtml(entry)}</span>`
              ).join("")}
              <span
                class="meta-pill ${Number(item.cooldown_remaining || 0) > 0 ? "" : "hidden"}"
                data-cooldown-item="${Number(item.id)}"
              >${Number(item.cooldown_remaining || 0) > 0 ? escapeHtml(`Wieder in ${duration(item.cooldown_remaining)}`) : ""}</span>
            </div>
          </div>

          <div class="item-buy-row">
            <div class="item-price">${euro(Number(item.price_cents || 0) / 100)}</div>
            <button
              type="button"
              class="buy-button ${testMode ? "test-buy" : ""}"
              data-buy-item="${Number(item.id)}"
              ${item.available && (shop.paypal_configured || testMode) ? "" : "disabled"}
            >${
              item.available
                ? (testMode ? "TESTKAUF" : "KAUFEN")
                : escapeHtml(item.availability_reason || "NICHT VERFÜGBAR")
            }</button>
          </div>
        </article>`;
    }).join("");

    bindItemImages();

    all("[data-buy-item]").forEach((button) => {
      button.onclick = () => startPayment({
        kind:"item",
        item_id:Number(button.dataset.buyItem),
      });
    });

    updateDynamicItemValues(items);
  }

  function render(shop) {
    if (!shop) return;
    latestShop = shop;

    $("shopEventTotal").textContent = euro(
      Number(shop.event_total_cents || 0) / 100
    );

    const paypal = $("paypalStatus");
    const testMode = Boolean(shop.test_mode);

    $("shopTestBanner").classList.toggle(
      "hidden",
      !testMode
    );

    if (testMode) {
      paypal.textContent = "TESTMODUS · KEIN ECHTES GELD";
      paypal.className = "status-pill test";
    } else if (shop.paypal_configured) {
      paypal.textContent = shop.paypal_mode === "live"
        ? "PAYPAL LIVE"
        : "PAYPAL SANDBOX";
      paypal.className = "status-pill ok";
    } else {
      paypal.textContent = "PAYPAL NICHT KONFIGURIERT";
      paypal.className = "status-pill bad";
    }

    renderItems(shop, testMode);

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

    const proto = location.protocol === "https:"
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
        render(message.data?.shop);
      }
    };

    ws.onclose = () => {
      reconnectTimer = setTimeout(
        connect,
        1800
      );
    };

    ws.onerror = () => {
      try {
        ws.close();
      } catch (_) {}
    };
  }

  async function startPayment(payload) {
    if (paying) return;

    const testMode = Boolean(
      latestShop?.test_mode
    );

    if (
      !testMode
      && !latestShop?.paypal_configured
    ) {
      return toast(
        "PayPal ist aktuell noch nicht konfiguriert."
      );
    }

    paying = true;

    try {
      const body = {
        ...payload,
        display_name:$("buyerName").value.trim(),
        message:$("buyerMessage").value.trim(),
      };

      const response = await fetch(
        "/dartmarathon/shop/api/create-order",
        {
          method:"POST",
          headers:{
            "Content-Type":"application/json",
          },
          body:JSON.stringify(body),
        }
      );

      const data = await response.json();

      if (!response.ok || !data.ok) {
        throw new Error(
          data.error
          || (
            testMode
              ? "Testkauf konnte nicht ausgelöst werden."
              : "PayPal-Zahlung konnte nicht gestartet werden."
          )
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
        throw new Error(
          "PayPal-Zahlung konnte nicht gestartet werden."
        );
      }

      location.href = data.approval_url;

    } catch (error) {
      toast(
        error.message
        || "Zahlung konnte nicht gestartet werden."
      );
      paying = false;
    }
  }

  all("[data-donate]").forEach((button) => {
    button.onclick = () => startPayment({
      kind:"donation",
      amount:Number(button.dataset.donate),
    });
  });

  $("customDonateButton").onclick = () => {
    const amount = Number(
      String(
        $("customDonation").value || ""
      ).replace(",", ".")
    );

    if (
      !Number.isFinite(amount)
      || amount < 1
    ) {
      return toast(
        "Bitte mindestens 1 € eingeben."
      );
    }

    startPayment({
      kind:"donation",
      amount,
    });
  };

  const searchInput = $("shopSearch");

  if (searchInput) {
    searchInput.addEventListener("input", () => {
      shopSearch = searchInput.value || "";
      lastItemsSignature = "";
      if (latestShop) {
        renderItems(
          latestShop,
          Boolean(latestShop.test_mode)
        );
      }
    });
  }

  all("[data-shop-filter]").forEach((button) => {
    button.onclick = () => {
      shopFilter = button.dataset.shopFilter || "all";

      all("[data-shop-filter]").forEach((entry) => {
        entry.classList.toggle(
          "active",
          entry === button
        );
      });

      lastItemsSignature = "";

      if (latestShop) {
        renderItems(
          latestShop,
          Boolean(latestShop.test_mode)
        );
      }
    };
  });

  const params = new URLSearchParams(
    location.search
  );

  const payment = params.get("payment");

  if (payment) {
    const notice = $("paymentNotice");
    notice.classList.remove("hidden");

    if (payment === "success") {
      notice.className =
        "payment-notice success";
      notice.textContent =
        "Zahlung erfolgreich. Vielen Dank – die Aktion ist bereits im Stream und Control Center angekommen.";
    } else if (payment === "cancelled") {
      notice.className =
        "payment-notice warning";
      notice.textContent =
        "Die PayPal-Zahlung wurde abgebrochen.";
    } else if (payment === "pending") {
      notice.className =
        "payment-notice warning";
      notice.textContent =
        "PayPal verarbeitet die Zahlung noch. Sobald sie bestätigt ist, wird sie automatisch übernommen.";
    } else {
      notice.className =
        "payment-notice error";
      notice.textContent =
        "Die Zahlung konnte nicht abgeschlossen werden. Es wurde keine Shop-Aktion ausgelöst.";
    }

    history.replaceState(
      {},
      "",
      location.pathname
    );
  }

  connect();
})();
