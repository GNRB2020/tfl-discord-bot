(() => {
  let ws = null;
  let reconnectTimer = null;
  let shopState = null;
  let editingItemId = null;
  let lastOpenCount = null;
  let importFile = null;

  const $ = (id) => document.getElementById(id);
  const all = (selector) => [...document.querySelectorAll(selector)];

  function escapeHtml(value) {
    return String(value ?? "").replace(/[&<>'"]/g, (char) => ({
      "&":"&amp;", "<":"&lt;", ">":"&gt;", "'":"&#39;", '"':"&quot;"
    }[char]));
  }

  function euroFromCents(cents) {
    return (Number(cents || 0) / 100).toLocaleString("de-DE", {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    }) + " €";
  }

  function targetLabel(target) {
    return ({tzmarty:"Tzmarty", korsar:"Korsar", both:"Beide", general:"Allgemein", on_site:"Vor Ort"})[target] || "Allgemein";
  }

  function toast(text) {
    const el = $("toast");
    if (!el) return;
    el.textContent = text;
    el.classList.remove("hidden");
    clearTimeout(el._timer);
    el._timer = setTimeout(() => el.classList.add("hidden"), 3600);
  }

  function send(payload) {
    if (!ws || ws.readyState !== WebSocket.OPEN) {
      toast("Keine Verbindung zum Server.");
      return false;
    }
    ws.send(JSON.stringify(payload));
    return true;
  }

  function openShopTab() {
    const button = document.querySelector('.tab[data-tab="shop"]');
    if (button) button.click();
  }

  function renderTasks(tasks) {
    const container = $("shopOpenTasks");
    const safe = Array.isArray(tasks) ? tasks : [];
    $("shopOpenHint").textContent = `${safe.length} offen`;
    if (!safe.length) {
      container.innerHTML = '<div class="shop-empty">Keine offenen Foltershop-Aufgaben.</div>';
      return;
    }
    container.innerHTML = safe.map((task) => `
      <div class="shop-task-row ${task.task_status === "in_progress" ? "running" : ""}">
        <div class="shop-task-main">
          <strong>#${Number(task.id)} · ${escapeHtml(task.item_name)}</strong>
          <span>${escapeHtml(targetLabel(task.target))} · ${escapeHtml(task.display_name || "Anonym")} · ${euroFromCents(task.amount_cents)}</span>
          ${task.message ? `<em>${escapeHtml(task.message)}</em>` : ""}
        </div>
        <div class="shop-task-actions">
          ${task.task_status === "in_progress"
            ? '<span class="task-live">LÄUFT</span>'
            : `<button type="button" class="mini-btn warning" data-task-start="${Number(task.id)}">STARTEN</button>`}
          <button type="button" class="mini-btn positive" data-task-done="${Number(task.id)}">ERLEDIGT</button>
        </div>
      </div>`).join("");

    all("[data-task-start]").forEach((button) => {
      button.onclick = () => send({type:"shop_task_status", order_id:Number(button.dataset.taskStart), status:"in_progress"});
    });
    all("[data-task-done]").forEach((button) => {
      button.onclick = () => send({type:"shop_task_status", order_id:Number(button.dataset.taskDone), status:"done"});
    });
  }

  function renderItems(items) {
    const container = $("shopItemList");
    const safe = Array.isArray(items) ? items : [];
    if (!safe.length) {
      container.innerHTML = '<div class="shop-empty">Noch keine Artikel angelegt.</div>';
      return;
    }
    container.innerHTML = safe.map((item) => {
      const limit = Number(item.max_quantity || 0) > 0
        ? `${Number(item.sold_count || 0)}/${Number(item.max_quantity)}`
        : `${Number(item.sold_count || 0)}/∞`;
      const cooldown = Number(item.cooldown_seconds || 0) > 0
        ? `${Math.round(Number(item.cooldown_seconds) / 60)} Min.`
        : "kein Cooldown";
      const action = item.action_type === "pause_minus"
        ? ` · Pausendieb -${Number(item.action_value || 0)}s`
        : "";
      return `
        <div class="shop-item-row ${item.active ? "" : "inactive"}">
          <div class="shop-item-icon">${escapeHtml(item.icon || "🎯")}</div>
          <div class="shop-item-main">
            <strong>${escapeHtml(item.name)}</strong>
            <span>${euroFromCents(item.price_cents)} · ${escapeHtml(targetLabel(item.target))} · ${limit} · ${cooldown}${escapeHtml(action)}</span>
          </div>
          <div class="shop-item-actions">
            <button type="button" class="mini-btn ghost" data-shop-edit="${Number(item.id)}">BEARBEITEN</button>
            <button type="button" class="mini-btn ${item.active ? "neutral" : "positive"}" data-shop-toggle="${Number(item.id)}">${item.active ? "PAUSIEREN" : "AKTIVIEREN"}</button>
            <button type="button" class="mini-btn danger" data-shop-delete="${Number(item.id)}">LÖSCHEN</button>
          </div>
        </div>`;
    }).join("");

    all("[data-shop-edit]").forEach((button) => button.onclick = () => editItem(Number(button.dataset.shopEdit)));
    all("[data-shop-toggle]").forEach((button) => button.onclick = () => send({type:"shop_item_toggle", id:Number(button.dataset.shopToggle)}));
    all("[data-shop-delete]").forEach((button) => button.onclick = () => {
      const id = Number(button.dataset.shopDelete);
      if (confirm("Artikel wirklich löschen? Bereits verwendete Artikel können aus Sicherheitsgründen nur deaktiviert werden.")) {
        send({type:"shop_item_delete", id});
      }
    });
  }

  function renderPayments(orders) {
    const container = $("shopPaymentHistory");
    const safe = Array.isArray(orders) ? orders.slice(0, 30) : [];
    if (!safe.length) {
      container.innerHTML = '<div class="shop-empty">Noch keine bezahlten Käufe oder Spenden.</div>';
      return;
    }
    container.innerHTML = safe.map((order) => {
      const title = order.kind === "item" ? order.item_name : "Spende";
      const task = order.kind === "item"
        ? `<span class="payment-task ${escapeHtml(order.task_status)}">${escapeHtml(order.task_status === "done" ? "ERLEDIGT" : order.task_status === "in_progress" ? "LÄUFT" : "OFFEN")}</span>`
        : "";
      return `
        <div class="shop-payment-row">
          <div>
            <strong>#${Number(order.id)} · ${escapeHtml(title)} ${order.is_test ? '<span class="test-order-badge">TEST</span>' : ""}</strong>
            <span>${escapeHtml(order.display_name || "Anonym")} · ${euroFromCents(order.amount_cents)} · ${escapeHtml(order.paid_at || "")}</span>
          </div>
          ${task}
        </div>`;
    }).join("");
  }

  function render(shop) {
    if (!shop) return;
    shopState = shop;
    const openCount = Number(shop.open_task_count || 0);
    $("shopTaskBadge").textContent = openCount;
    $("shopAlertButton").textContent = `SHOP: ${openCount} OFFEN`;
    $("shopAlertButton").classList.toggle("has-open", openCount > 0);

    if (lastOpenCount !== null && openCount > lastOpenCount) {
      $("shopAlertButton").classList.add("shop-pulse");
      setTimeout(() => $("shopAlertButton").classList.remove("shop-pulse"), 5000);
      toast(`Neuer Foltershop-Kauf · ${openCount} offene Aufgabe${openCount === 1 ? "" : "n"}.`);
    }
    lastOpenCount = openCount;

    $("shopPurchaseTotal").textContent = euroFromCents(shop.summary?.purchase_cents);
    $("shopDonationTotal").textContent = euroFromCents(shop.summary?.donation_cents);
    $("shopOwnDonations").textContent = euroFromCents(shop.own_donations_cents);
    $("shopEventTotal").textContent = euroFromCents(shop.event_total_cents);

    const testMode = Boolean(shop.test_mode);
    const testStatus = $("shopTestStatus");
    testStatus.textContent = testMode
      ? "TESTMODUS AKTIV"
      : "TESTMODUS AUS";
    testStatus.className = testMode
      ? "shop-config-pill test"
      : "shop-config-pill";

    $("shopTestToggle").textContent = testMode
      ? "TESTMODUS BEENDEN"
      : "TESTMODUS STARTEN";
    $("shopTestToggle").className = testMode
      ? "mini-btn neutral"
      : "mini-btn warning";
    $("shopTestReset").classList.toggle(
      "hidden",
      !testMode
    );

    const config = $("shopPaypalConfig");
    if (testMode) {
      config.textContent = "PAYPAL WIRD UMGANGEN";
      config.className = "shop-config-pill test";
    } else if (shop.paypal_configured) {
      config.textContent = shop.paypal_mode === "live" ? "PAYPAL LIVE" : "PAYPAL SANDBOX";
      config.className = "shop-config-pill ok";
    } else {
      config.textContent = "PAYPAL FEHLT";
      config.className = "shop-config-pill bad";
    }

    renderTasks(shop.open_tasks);
    renderItems(shop.items_admin);
    renderPayments(shop.orders);
  }

  function clearEditor() {
    editingItemId = null;
    $("shopEditorTitle").textContent = "NEUER ARTIKEL";
    $("shopItemName").value = "";
    $("shopItemIcon").value = "🎯";
    $("shopItemPrice").value = "";
    $("shopItemMax").value = 0;
    $("shopItemCooldown").value = 0;
    $("shopItemTarget").value = "general";
    $("shopItemSort").value = "";
    $("shopItemActionType").value = "";
    $("shopItemActionValue").value = 0;
    $("shopItemImageUrl").value = "";
    $("shopItemDescription").value = "";
    $("shopItemStreamText").value = "";
    $("shopItemActive").checked = true;
  }

  function showEditor() {
    $("shopEditor").classList.remove("hidden");
    openShopTab();
  }

  function editItem(id) {
    const item = shopState?.items_admin?.find((entry) => Number(entry.id) === Number(id));
    if (!item) return;
    editingItemId = id;
    $("shopEditorTitle").textContent = `ARTIKEL #${id} BEARBEITEN`;
    $("shopItemName").value = item.name || "";
    $("shopItemIcon").value = item.icon || "🎯";
    $("shopItemPrice").value = (Number(item.price_cents || 0) / 100).toFixed(2);
    $("shopItemMax").value = Number(item.max_quantity || 0);
    $("shopItemCooldown").value = Math.round(Number(item.cooldown_seconds || 0) / 60);
    $("shopItemTarget").value = item.target || "general";
    $("shopItemSort").value = Number(item.sort_order || id * 10);
    $("shopItemActionType").value = item.action_type || "";
    $("shopItemActionValue").value = Number(item.action_value || 0);
    $("shopItemImageUrl").value = item.image_url || "";
    $("shopItemDescription").value = item.description || "";
    $("shopItemStreamText").value = item.stream_text || "";
    $("shopItemActive").checked = Boolean(item.active);
    showEditor();
  }

  function saveItem() {
    const payload = {
      type:"shop_item_save",
      id:editingItemId,
      name:$("shopItemName").value.trim(),
      icon:$("shopItemIcon").value.trim(),
      price:$("shopItemPrice").value,
      max_quantity:Number($("shopItemMax").value || 0),
      cooldown_minutes:Number($("shopItemCooldown").value || 0),
      target:$("shopItemTarget").value,
      sort_order:Number($("shopItemSort").value || 0),
      action_type:$("shopItemActionType").value,
      action_value:Number($("shopItemActionValue").value || 0),
      image_url:$("shopItemImageUrl").value.trim(),
      description:$("shopItemDescription").value.trim(),
      stream_text:$("shopItemStreamText").value.trim(),
      active:$("shopItemActive").checked,
    };
    if (!payload.name) return toast("Bitte einen Artikelnamen eingeben.");
    if (!Number(payload.price) || Number(payload.price) < 0.5) return toast("Bitte einen gültigen Preis ab 0,50 € eingeben.");
    if (send(payload)) {
      $("shopEditor").classList.add("hidden");
      clearEditor();
    }
  }

  function showImportPanel() {
    $("shopImportPanel").classList.remove("hidden");
    $("shopEditor").classList.add("hidden");
    openShopTab();
  }

  function clearImportPanel() {
    $("shopImportSummary").innerHTML = "";
    $("shopImportWarnings").innerHTML = "";
    $("shopImportErrors").innerHTML = "";
    $("shopImportRows").innerHTML = "";
    $("shopImportApply").classList.add("hidden");
  }

  function renderImportResult(data) {
    showImportPanel();
    clearImportPanel();

    if (!data?.ok) {
      const errors = Array.isArray(data?.errors) ? data.errors : ["Import konnte nicht geprüft werden."];
      $("shopImportErrors").innerHTML = errors
        .map((entry) => `<div>${escapeHtml(entry)}</div>`)
        .join("");
      return;
    }

    const preview = data.preview || {};
    $("shopImportSummary").innerHTML = `
      <strong>${escapeHtml(data.filename || "Datei")}</strong>
      <span>${Number(preview.total || 0)} Zeilen · ${Number(preview.new || 0)} neu · ${Number(preview.updated || 0)} aktualisiert · ${Number(preview.unchanged || 0)} unverändert · ${Number(preview.deactivated || 0)} deaktiviert</span>
    `;

    const warnings = Array.isArray(data.warnings) ? data.warnings : [];
    if (warnings.length) {
      $("shopImportWarnings").innerHTML = warnings
        .map((entry) => `<div>${escapeHtml(entry)}</div>`)
        .join("");
    }

    const rows = Array.isArray(preview.rows) ? preview.rows : [];
    $("shopImportRows").innerHTML = rows.map((row) => {
      const action = row.action_type === "pause_minus"
        ? ` · Pausendieb -${Number(row.action_value || 0)}s`
        : "";
      return `
        <div class="shop-import-row">
          <strong>#${Number(row.id)} · ${escapeHtml(row.name)}</strong>
          <span>${escapeHtml(row.status)} · ${euroFromCents(row.price_cents)} · ${row.active ? "AKTIV" : "INAKTIV"}${escapeHtml(action)}</span>
        </div>`;
    }).join("");

    if (data.action === "preview" && importFile) {
      $("shopImportApply").classList.remove("hidden");
    }

    if (data.action === "apply") {
      $("shopImportApply").classList.add("hidden");
      toast("Artikelimport erfolgreich übernommen.");
    }
  }

  async function uploadImport(action) {
    if (!importFile) {
      return toast("Bitte zuerst eine Excel- oder CSV-Datei auswählen.");
    }

    const formData = new FormData();
    formData.append("action", action);
    formData.append("file", importFile, importFile.name);

    try {
      const response = await fetch(
        "/dartmarathon/shop/api/import-items",
        {
          method:"POST",
          body:formData,
          credentials:"same-origin",
        }
      );
      let data;
      try {
        data = await response.json();
      } catch (_) {
        data = {
          ok:false,
          errors:[`Serverfehler (${response.status}).`],
        };
      }
      renderImportResult(data);
    } catch (error) {
      renderImportResult({
        ok:false,
        errors:[error.message || "Import konnte nicht hochgeladen werden."],
      });
    }
  }

  function connect() {
    clearTimeout(reconnectTimer);
    const proto = location.protocol === "https:" ? "wss" : "ws";
    ws = new WebSocket(`${proto}://${location.host}/dartmarathon/ws`);
    ws.onmessage = (event) => {
      let message;
      try { message = JSON.parse(event.data); } catch (_) { return; }
      if (message.type === "state") render(message.data?.shop);
      if (message.type === "error") toast(message.message || "Shop-Aktion fehlgeschlagen.");
    };
    ws.onclose = () => { reconnectTimer = setTimeout(connect, 1500); };
    ws.onerror = () => { try { ws.close(); } catch (_) {} };
  }

  $("shopAlertButton").onclick = openShopTab;
  $("shopNewItem").onclick = () => { clearEditor(); showEditor(); };
  $("shopCancelItem").onclick = () => { $("shopEditor").classList.add("hidden"); clearEditor(); };
  $("shopSaveItem").onclick = saveItem;

  $("shopImportButton").onclick = () => {
    $("shopImportFile").click();
  };

  $("shopImportFile").onchange = () => {
    const file = $("shopImportFile").files?.[0] || null;
    if (!file) return;
    importFile = file;
    uploadImport("preview");
  };

  $("shopImportApply").onclick = () => {
    if (!importFile) return;
    if (confirm(
      "Import übernehmen? Gleiche IDs werden aktualisiert. Fehlende IDs werden NICHT gelöscht."
    )) {
      uploadImport("apply");
    }
  };

  $("shopImportClose").onclick = () => {
    $("shopImportPanel").classList.add("hidden");
    clearImportPanel();
    importFile = null;
    $("shopImportFile").value = "";
  };

  $("shopTestToggle").onclick = () => {
    const enabled = !Boolean(shopState?.test_mode);
    const text = enabled
      ? "Testmodus starten? Käufe und Spenden werden dann OHNE PayPal sofort simuliert."
      : "Testmodus beenden? Testkäufe zählen danach nicht mehr in Summen, Limits oder offene Aufgaben.";
    if (confirm(text)) {
      send({
        type:"shop_test_mode",
        enabled,
      });
    }
  };

  $("shopTestReset").onclick = () => {
    if (confirm(
      "Alle TESTKÄUFE und TESTSPENDEN löschen? Die Artikelkonfiguration bleibt vollständig erhalten."
    )) {
      send({type:"shop_test_reset"});
    }
  };

  clearEditor();
  connect();
})();
