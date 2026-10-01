(() => {
  const WIDTH = 1920;
  const HEIGHT = 1080;
  const SNAP = 10;

  const META = {
    tzmarty_score:{label:"Tzmarty – Legs / Specials",sample:"12 / 5",tone:"red"},
    korsar_score:{label:"Korsar – Legs / Specials",sample:"10 / 7",tone:"blue"},
    total_legs:{label:"Legs gesamt",sample:"22",tone:"gold"},
    total_specials:{label:"Specials gesamt",sample:"12",tone:"gold"},
    pause:{label:"Pausenuhr",sample:"15:00",tone:"green"},
    event_money:{label:"Event-Spendentopf",sample:"1.234,50 €",tone:"gold"},
    stream_time:{label:"Streamlaufzeit",sample:"12:34:56",tone:"blue"},
    support_ticker:{label:"Unterstützer-Laufband",sample:"GNRB 25,00 € • RobG92 10,00 €",tone:"gold"},
    shop_banner:{label:"Shop-/Spendenbanner",sample:"FOLTERSHOP · Darts tauschen · 5,00 €",tone:"purple"},
    pause_center_popup:{label:"Pause – Hauptfenster",sample:"PAUSE · 15:00",tone:"green"},
    ad_popup:{label:"Werbung – normale Einblendung",sample:"WERBUNG · KOALA / MALTESER / FOLTERSHOP",tone:"purple"},
    recent_matches_popup:{label:"Popup – letzte 5 Spiele",sample:"LETZTE 5 SPIELE",tone:"gold"},
    specials_tzmarty_popup:{label:"Popup – Specials Tzmarty",sample:"TZMARTY · SPECIALS",tone:"red"},
    specials_korsar_popup:{label:"Popup – Specials Korsar",sample:"KORSAR · SPECIALS",tone:"blue"},
    stats_popup:{label:"Popup – Event-Kennzahlen",sample:"EVENT-KENNZAHLEN",tone:"gold"},
    pause_results_popup:{label:"Pause – alle Ergebnisse",sample:"ALLE ERGEBNISSE",tone:"gold"},
    pause_specials_popup:{label:"Pause – alle Specials",sample:"ALLE SPECIALS",tone:"purple"},
    pause_supporters_popup:{label:"Pause – Käufer & Spender",sample:"KÄUFER & SPENDER",tone:"green"},
    pause_ad_popup:{label:"Pause – Werbung",sample:"PAUSEN-WERBUNG",tone:"purple"},
    event_final:{label:"Eventende – Abschlussstatistik",sample:"DIE EVENT-STATISTIK",tone:"red"},
  };

  let ws = null;
  let retryTimer = null;
  let defaults = null;
  let draft = null;
  let selectedKey = "tzmarty_score";
  let dirty = false;
  let scale = 1;
  let pointerState = null;

  const $ = (id) => document.getElementById(id);
  const all = (selector) => [...document.querySelectorAll(selector)];

  function clone(value) {
    return JSON.parse(JSON.stringify(value));
  }

  function toast(text, type = "") {
    const el = $("toast");
    if (!el) return;
    el.textContent = text;
    el.className = `toast ${type}`.trim();
    el.classList.remove("hidden");
    clearTimeout(el._overlayEditorTimer);
    el._overlayEditorTimer = setTimeout(
      () => el.classList.add("hidden"),
      3200
    );
  }

  function send(payload) {
    if (!ws || ws.readyState !== WebSocket.OPEN) {
      toast("Keine Verbindung zum Server.", "error");
      return false;
    }
    ws.send(JSON.stringify(payload));
    return true;
  }

  function setStatus(text, changed = false) {
    const el = $("overlayEditorStatus");
    el.textContent = text;
    el.classList.toggle("dirty", changed);
  }

  function markDirty() {
    dirty = true;
    setStatus(
      "Ungespeicherte Vorschau – OBS noch unverändert",
      true
    );
  }

  function normalizeElement(cfg) {
    const w = Math.max(40, Math.min(WIDTH, Math.round(Number(cfg.w || 100))));
    const h = Math.max(20, Math.min(HEIGHT, Math.round(Number(cfg.h || 40))));
    const x = Math.max(0, Math.min(WIDTH - w, Math.round(Number(cfg.x || 0))));
    const y = Math.max(0, Math.min(HEIGHT - h, Math.round(Number(cfg.y || 0))));

    return {
      x,
      y,
      w,
      h,
      font:Math.max(8, Math.min(160, Math.round(Number(cfg.font || 16)))),
      align:["left","center","right"].includes(cfg.align) ? cfg.align : "center",
      valign:["top","center","bottom"].includes(cfg.valign) ? cfg.valign : "center",
      visible:cfg.visible !== false,
    };
  }

  function normalizeLayout(layout) {
    const source = layout?.elements && typeof layout.elements === "object"
      ? layout.elements
      : layout;

    const result = {};

    for (const key of Object.keys(META)) {
      const fallback = defaults?.[key] || {
        x:0,y:0,w:200,h:60,font:24,
        align:"center",valign:"center",visible:true,
      };

      result[key] = normalizeElement({
        ...fallback,
        ...(source?.[key] || {}),
      });
    }

    return result;
  }

  function buildSelect() {
    $("overlayElementSelect").innerHTML = Object.entries(META)
      .map(([key, meta]) => `<option value="${key}">${meta.label}</option>`)
      .join("");
    $("overlayElementSelect").value = selectedKey;
  }

  function updateCanvasScale() {
    const viewport = $("overlayEditorViewport");
    const canvas = $("overlayEditorCanvas");
    if (!viewport || !canvas) return;

    const rect = viewport.getBoundingClientRect();
    scale = Math.min(rect.width / WIDTH, rect.height / HEIGHT);
    canvas.style.transform = `scale(${scale})`;
  }

  function horizontal(align) {
    return ({left:"flex-start",center:"center",right:"flex-end"})[align] || "center";
  }

  function vertical(valign) {
    return ({top:"flex-start",center:"center",bottom:"flex-end"})[valign] || "center";
  }

  function renderCanvas() {
    if (!draft) return;
    const canvas = $("overlayEditorCanvas");

    for (const [key, meta] of Object.entries(META)) {
      let item = canvas.querySelector(`[data-overlay-key="${key}"]`);

      if (!item) {
        item = document.createElement("div");
        item.dataset.overlayKey = key;
        item.className = `overlay-editor-item tone-${meta.tone}`;
        item.innerHTML = `
          <div class="overlay-editor-item-label">${meta.label}</div>
          <div class="overlay-editor-item-value">${meta.sample}</div>
          <div class="overlay-resize-handle" title="Größe ändern"></div>
        `;
        canvas.appendChild(item);
      }

      const cfg = draft[key];
      item.style.left = `${cfg.x}px`;
      item.style.top = `${cfg.y}px`;
      item.style.width = `${cfg.w}px`;
      item.style.height = `${cfg.h}px`;
      item.style.fontSize = `${cfg.font}px`;
      item.style.textAlign = cfg.align;
      item.style.justifyContent = horizontal(cfg.align);
      item.style.alignItems = vertical(cfg.valign);
      item.classList.toggle("selected", key === selectedKey);
      item.classList.toggle("layout-hidden", !cfg.visible);
    }

    updateCanvasScale();
  }

  function updateInspector() {
    if (!draft?.[selectedKey]) return;
    const cfg = draft[selectedKey];

    $("overlayElementSelect").value = selectedKey;
    $("overlayX").value = cfg.x;
    $("overlayY").value = cfg.y;
    $("overlayW").value = cfg.w;
    $("overlayH").value = cfg.h;
    $("overlayFont").value = cfg.font;
    $("overlayAlign").value = cfg.align;
    $("overlayValign").value = cfg.valign;
    $("overlayVisible").checked = cfg.visible;
  }

  function selectElement(key) {
    if (!META[key] || !draft?.[key]) return;
    selectedKey = key;
    renderCanvas();
    updateInspector();
  }

  function snapValue(value) {
    return $("overlaySnap").checked
      ? Math.round(value / SNAP) * SNAP
      : Math.round(value);
  }

  function applyInspector() {
    if (!draft?.[selectedKey]) return;
    const cfg = draft[selectedKey];

    cfg.w = Math.max(40, Math.min(WIDTH, Number($("overlayW").value || cfg.w)));
    cfg.h = Math.max(20, Math.min(HEIGHT, Number($("overlayH").value || cfg.h)));
    cfg.x = Math.max(0, Math.min(WIDTH - cfg.w, Number($("overlayX").value || 0)));
    cfg.y = Math.max(0, Math.min(HEIGHT - cfg.h, Number($("overlayY").value || 0)));
    cfg.font = Math.max(8, Math.min(160, Number($("overlayFont").value || cfg.font)));
    cfg.align = $("overlayAlign").value;
    cfg.valign = $("overlayValign").value;
    cfg.visible = $("overlayVisible").checked;

    draft[selectedKey] = normalizeElement(cfg);
    markDirty();
    renderCanvas();
    updateInspector();
  }

  function nudge(dx, dy) {
    if (!draft?.[selectedKey]) return;
    const cfg = draft[selectedKey];

    cfg.x = Math.max(0, Math.min(WIDTH - cfg.w, cfg.x + dx));
    cfg.y = Math.max(0, Math.min(HEIGHT - cfg.h, cfg.y + dy));

    markDirty();
    renderCanvas();
    updateInspector();
  }

  function beginPointer(event) {
    const item = event.target.closest("[data-overlay-key]");
    if (!item || !draft) return;

    event.preventDefault();
    const key = item.dataset.overlayKey;
    selectElement(key);

    pointerState = {
      pointerId:event.pointerId,
      key,
      resizing:Boolean(event.target.closest(".overlay-resize-handle")),
      startClientX:event.clientX,
      startClientY:event.clientY,
      start:clone(draft[key]),
    };

    item.setPointerCapture?.(event.pointerId);
  }

  function movePointer(event) {
    if (!pointerState || event.pointerId !== pointerState.pointerId) return;
    event.preventDefault();

    const cfg = draft[pointerState.key];
    const start = pointerState.start;
    const dx = (event.clientX - pointerState.startClientX) / scale;
    const dy = (event.clientY - pointerState.startClientY) / scale;

    if (pointerState.resizing) {
      cfg.w = Math.max(40, Math.min(WIDTH - start.x, snapValue(start.w + dx)));
      cfg.h = Math.max(20, Math.min(HEIGHT - start.y, snapValue(start.h + dy)));
    } else {
      cfg.x = Math.max(0, Math.min(WIDTH - cfg.w, snapValue(start.x + dx)));
      cfg.y = Math.max(0, Math.min(HEIGHT - cfg.h, snapValue(start.y + dy)));
    }

    markDirty();
    renderCanvas();
    updateInspector();
  }

  function endPointer(event) {
    if (pointerState && event.pointerId === pointerState.pointerId) {
      pointerState = null;
    }
  }

  function saveLive() {
    if (!draft) return;

    if (send({
      type:"overlay_layout_save",
      layout:draft,
    })) {
      dirty = false;
      setStatus("Wird live übernommen…");
    }
  }

  function resetSelected() {
    if (!defaults?.[selectedKey]) return;
    draft[selectedKey] = clone(defaults[selectedKey]);
    markDirty();
    renderCanvas();
    updateInspector();
  }

  function resetAll() {
    if (!defaults) return;

    if (!confirm("Alle Overlay-Elemente in der Vorschau auf Standard zurücksetzen?")) {
      return;
    }

    draft = clone(defaults);
    markDirty();
    renderCanvas();
    updateInspector();
  }

  function exportLayout() {
    if (!draft) return;

    const blob = new Blob(
      [JSON.stringify({version:1,elements:draft}, null, 2)],
      {type:"application/json"}
    );

    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = "dartmarathon-overlay-layout.json";
    document.body.appendChild(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }

  async function importLayout(file) {
    try {
      draft = normalizeLayout(JSON.parse(await file.text()));
      markDirty();
      renderCanvas();
      updateInspector();
      toast("Layout importiert. Noch nicht live übernommen.", "success");
    } catch (_) {
      toast("Die JSON-Datei ist kein gültiges Overlay-Layout.", "error");
    }
  }

  function handleState(message) {
    const data = message?.data;
    if (!data) return;

    if (data.overlay_layout_defaults && !defaults) {
      defaults = normalizeLayout(data.overlay_layout_defaults);
    }

    if (data.overlay_layout && (!draft || !dirty)) {
      draft = normalizeLayout(data.overlay_layout);
      dirty = false;
      setStatus("Live-Layout geladen");
      renderCanvas();
      updateInspector();
    }
  }

  function connect() {
    clearTimeout(retryTimer);
    const proto = location.protocol === "https:" ? "wss" : "ws";
    ws = new WebSocket(`${proto}://${location.host}/dartmarathon/ws`);

    ws.onmessage = (event) => {
      let message;
      try {
        message = JSON.parse(event.data);
      } catch (_) {
        return;
      }

      if (message.type === "state") {
        handleState(message);
        return;
      }

      if (message.type === "overlay_layout_saved") {
        dirty = false;
        setStatus("Live übernommen · OBS aktualisiert");
        toast("Overlay-Layout live übernommen.", "success");
        return;
      }

      if (message.type === "error") {
        toast(message.message || "Overlay-Aktion fehlgeschlagen.", "error");
      }
    };

    ws.onclose = () => {
      retryTimer = setTimeout(connect, 1600);
    };

    ws.onerror = () => {
      try {
        ws.close();
      } catch (_) {}
    };
  }

  function updateOverlayMode() {
    const overlayTab = document.querySelector('.tab[data-tab="overlay"]');
    const active = Boolean(overlayTab?.classList.contains("active"));

    document.body.classList.toggle("overlay-editor-active", active);

    if (active) {
      requestAnimationFrame(updateCanvasScale);
    }
  }

  buildSelect();

  $("overlayElementSelect").onchange = () => {
    selectElement($("overlayElementSelect").value);
  };

  for (const id of [
    "overlayX","overlayY","overlayW","overlayH",
    "overlayFont","overlayAlign","overlayValign","overlayVisible",
  ]) {
    $(id).addEventListener("change", applyInspector);
  }

  $("overlayGrid").onchange = () => {
    $("overlayEditorViewport").classList.toggle(
      "show-grid",
      $("overlayGrid").checked
    );
  };

  all("[data-nudge-x],[data-nudge-y]").forEach((button) => {
    button.onclick = () => {
      nudge(
        Number(button.dataset.nudgeX || 0),
        Number(button.dataset.nudgeY || 0)
      );
    };
  });

  $("overlaySaveLive").onclick = saveLive;
  $("overlayResetSelected").onclick = resetSelected;
  $("overlayResetAll").onclick = resetAll;
  $("overlayExport").onclick = exportLayout;
  $("overlayImport").onclick = () => $("overlayImportFile").click();

  $("overlayImportFile").onchange = async () => {
    const file = $("overlayImportFile").files?.[0];
    if (file) await importLayout(file);
    $("overlayImportFile").value = "";
  };

  $("overlayEditorCanvas").addEventListener("pointerdown", beginPointer);
  window.addEventListener("pointermove", movePointer);
  window.addEventListener("pointerup", endPointer);
  window.addEventListener("pointercancel", endPointer);
  window.addEventListener("resize", updateCanvasScale);

  all(".tab").forEach((button) => {
    button.addEventListener(
      "click",
      () => requestAnimationFrame(updateOverlayMode)
    );
  });

  if (typeof ResizeObserver !== "undefined") {
    const resizeObserver = new ResizeObserver(updateCanvasScale);
    resizeObserver.observe($("overlayEditorViewport"));
  }

  updateOverlayMode();
  connect();
})();
