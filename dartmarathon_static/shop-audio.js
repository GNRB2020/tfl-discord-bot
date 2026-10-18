(() => {
  "use strict";

  const STORAGE_KEY = "dartmarathon_shop_audio_v1";
  const EFFECT_FILES = {
    donation: "/dartmarathon/static/audio/thankyou.mp3",
    purchase: "/dartmarathon/static/audio/laugh.mp3",
  };

  const DEFAULTS = {
    localEnabled: true,
    effectVolume: 0.70,
    speechVolume: 1.00,
    speechRate: 0.95,
    localMessageTts: true,
  };

  const isControlPage = Boolean(
    document.querySelector(".top-actions")
    && document.getElementById("connectionText")
  );

  let settings = loadSettings();
  let audioContext = null;
  let localWs = null;
  let localRetryTimer = null;
  let busy = false;
  let voicesReady = false;
  const queue = [];
  const unavailableFiles = new Set();

  function clamp(value, minimum, maximum) {
    const number = Number(value);
    if (!Number.isFinite(number)) return minimum;
    return Math.min(maximum, Math.max(minimum, number));
  }

  function loadSettings() {
    try {
      const saved = JSON.parse(
        localStorage.getItem(STORAGE_KEY) || "{}"
      );

      return {
        localEnabled:
          saved.localEnabled !== false,
        effectVolume: clamp(
          saved.effectVolume ?? DEFAULTS.effectVolume,
          0,
          1
        ),
        speechVolume: clamp(
          saved.speechVolume ?? DEFAULTS.speechVolume,
          0,
          1
        ),
        speechRate: clamp(
          saved.speechRate ?? DEFAULTS.speechRate,
          0.70,
          1.30
        ),
        localMessageTts:
          saved.localMessageTts !== false,
      };
    } catch (_) {
      return {...DEFAULTS};
    }
  }

  function saveSettings() {
    try {
      localStorage.setItem(
        STORAGE_KEY,
        JSON.stringify(settings)
      );
    } catch (_) {
      // Einstellungen sind optional.
    }

    syncControlPanel();
  }

  function delay(milliseconds) {
    return new Promise((resolve) => {
      setTimeout(resolve, milliseconds);
    });
  }

  function cleanText(value, maximum = 220) {
    return String(value ?? "")
      .replace(/[\u0000-\u001f\u007f]/g, " ")
      .replace(/\s+/g, " ")
      .trim()
      .slice(0, maximum);
  }

  function isAnonymous(name) {
    const normalized = cleanText(
      name,
      50
    ).toLocaleLowerCase("de-DE");

    return (
      !normalized
      || normalized === "anonym"
      || normalized === "anonymous"
    );
  }

  function spokenAmount(value) {
    const amount = Number(
      String(value ?? "0").replace(",", ".")
    );

    if (!Number.isFinite(amount)) {
      return "0 Euro";
    }

    const formatted = amount.toLocaleString(
      "de-DE",
      {
        minimumFractionDigits:
          Number.isInteger(amount) ? 0 : 2,
        maximumFractionDigits: 2,
      }
    );

    return `${formatted} Euro`;
  }

  function currentGermanVoice() {
    if (!("speechSynthesis" in window)) {
      return null;
    }

    const voices = (
      window.speechSynthesis.getVoices()
      || []
    );

    return (
      voices.find(
        (voice) =>
          String(
            voice.lang || ""
          ).toLowerCase() === "de-de"
      )
      || voices.find(
        (voice) =>
          String(
            voice.lang || ""
          ).toLowerCase().startsWith("de")
      )
      || null
    );
  }

  function primeVoices() {
    if (!("speechSynthesis" in window)) {
      return;
    }

    try {
      window.speechSynthesis.getVoices();
      voicesReady = true;
    } catch (_) {
      voicesReady = false;
    }
  }

  function speak(
    text,
    {
      volume = settings.speechVolume,
      rate = settings.speechRate,
      pitch = 1,
    } = {}
  ) {
    const content = cleanText(text, 260);

    if (
      !content
      || !("speechSynthesis" in window)
      || typeof SpeechSynthesisUtterance === "undefined"
    ) {
      return Promise.resolve(false);
    }

    return new Promise((resolve) => {
      const utterance =
        new SpeechSynthesisUtterance(content);

      utterance.lang = "de-DE";
      utterance.volume = clamp(
        volume,
        0,
        1
      );
      utterance.rate = clamp(
        rate,
        0.70,
        1.30
      );
      utterance.pitch = clamp(
        pitch,
        0.50,
        1.50
      );

      const voice = currentGermanVoice();
      if (voice) {
        utterance.voice = voice;
      }

      let finished = false;

      const timeout = setTimeout(
        () => finish(false),
        Math.min(
          30000,
          Math.max(
            7000,
            content.length * 150
          )
        )
      );

      function finish(result) {
        if (finished) return;
        finished = true;
        clearTimeout(timeout);
        resolve(result);
      }

      utterance.onend =
        () => finish(true);
      utterance.onerror =
        () => finish(false);

      try {
        window.speechSynthesis.speak(
          utterance
        );
      } catch (_) {
        finish(false);
      }
    });
  }

  function getAudioContext() {
    if (audioContext) {
      return audioContext;
    }

    const AudioContextClass =
      window.AudioContext
      || window.webkitAudioContext;

    if (!AudioContextClass) {
      return null;
    }

    try {
      audioContext =
        new AudioContextClass();
    } catch (_) {
      audioContext = null;
    }

    return audioContext;
  }

  async function unlock() {
    const context = getAudioContext();

    if (
      context
      && context.state === "suspended"
    ) {
      try {
        await context.resume();
      } catch (_) {
        // Browser kann Audio bis zur nächsten Interaktion blockieren.
      }
    }

    primeVoices();

    return (
      !context
      || context.state === "running"
    );
  }

  async function playAudioFile(
    url,
    volume
  ) {
    if (unavailableFiles.has(url)) {
      return false;
    }

    return new Promise((resolve) => {
      let finished = false;
      const audio = new Audio(url);

      audio.preload = "auto";
      audio.volume = clamp(
        volume,
        0,
        1
      );

      const timeout = setTimeout(
        () => finish(false),
        6500
      );

      function finish(result) {
        if (finished) return;
        finished = true;
        clearTimeout(timeout);
        audio.onended = null;
        audio.onerror = null;
        resolve(result);
      }

      audio.onended =
        () => finish(true);

      audio.onerror = () => {
        unavailableFiles.add(url);
        finish(false);
      };

      try {
        const promise = audio.play();

        if (
          promise
          && typeof promise.catch === "function"
        ) {
          promise.catch(
            () => finish(false)
          );
        }
      } catch (_) {
        finish(false);
      }
    });
  }

  async function playDonationFallback() {
    const context = getAudioContext();

    if (!context) {
      return false;
    }

    if (context.state === "suspended") {
      try {
        await context.resume();
      } catch (_) {
        return false;
      }
    }

    if (context.state !== "running") {
      return false;
    }

    const start =
      context.currentTime + 0.02;

    const notes = [
      [659.25, 0.00],
      [783.99, 0.18],
      [987.77, 0.36],
    ];

    for (
      const [frequency, offset]
      of notes
    ) {
      const oscillator =
        context.createOscillator();
      const gain =
        context.createGain();

      oscillator.type = "sine";
      oscillator.frequency.value =
        frequency;

      gain.gain.setValueAtTime(
        0.0001,
        start + offset
      );

      gain.gain.exponentialRampToValueAtTime(
        Math.max(
          0.0001,
          settings.effectVolume * 0.16
        ),
        start + offset + 0.025
      );

      gain.gain.exponentialRampToValueAtTime(
        0.0001,
        start + offset + 0.38
      );

      oscillator.connect(gain);
      gain.connect(
        context.destination
      );

      oscillator.start(
        start + offset
      );
      oscillator.stop(
        start + offset + 0.42
      );
    }

    await delay(900);
    return true;
  }

  async function playPurchaseFallback() {
    const spoken = await speak(
      "Ha ha ha!",
      {
        volume:
          settings.effectVolume,
        rate: 1.16,
        pitch: 0.58,
      }
    );

    if (spoken) {
      await delay(120);
      return true;
    }

    const context = getAudioContext();

    if (!context) {
      return false;
    }

    if (context.state === "suspended") {
      try {
        await context.resume();
      } catch (_) {
        return false;
      }
    }

    if (context.state !== "running") {
      return false;
    }

    const start =
      context.currentTime + 0.02;

    for (
      let index = 0;
      index < 3;
      index += 1
    ) {
      const oscillator =
        context.createOscillator();
      const gain =
        context.createGain();
      const offset =
        index * 0.24;

      oscillator.type = "sawtooth";

      oscillator.frequency.setValueAtTime(
        180 - index * 18,
        start + offset
      );

      oscillator.frequency.exponentialRampToValueAtTime(
        105,
        start + offset + 0.18
      );

      gain.gain.setValueAtTime(
        0.0001,
        start + offset
      );

      gain.gain.exponentialRampToValueAtTime(
        Math.max(
          0.0001,
          settings.effectVolume * 0.08
        ),
        start + offset + 0.02
      );

      gain.gain.exponentialRampToValueAtTime(
        0.0001,
        start + offset + 0.20
      );

      oscillator.connect(gain);
      gain.connect(
        context.destination
      );

      oscillator.start(
        start + offset
      );
      oscillator.stop(
        start + offset + 0.22
      );
    }

    await delay(950);
    return true;
  }

  async function playEffect(kind) {
    const file = EFFECT_FILES[kind];

    const filePlayed = file
      ? await playAudioFile(
          file,
          settings.effectVolume
        )
      : false;

    if (filePlayed) {
      return true;
    }

    return kind === "donation"
      ? playDonationFallback()
      : playPurchaseFallback();
  }

  function announcementFor(
    message,
    mode
  ) {
    const donation =
      message.type
      === "shop_donation_popup";

    const name = cleanText(
      message.name,
      50
    );

    const actor = isAnonymous(name)
      ? "Jemand"
      : name;

    const amount = spokenAmount(
      message.amount
    );

    if (donation) {
      return {
        kind: "donation",
        intro:
          `${actor} hat ${amount} gespendet.`,
        detail:
          mode === "local"
          && !settings.localMessageTts
            ? ""
            : cleanText(
                message.message,
                180
              ),
      };
    }

    return {
      kind: "purchase",
      intro:
        `${actor} hat für ${amount} im Foltershop zugeschlagen.`,
      detail: cleanText(
        message.stream_text
        || message.item_name
        || "Neue Foltershop-Aufgabe",
        220
      ),
    };
  }

  function streamAudioEnabled() {
    try {
      const params =
        new URLSearchParams(
          window.location.search
        );

      return (
        params.get("shopAudio") !== "0"
        && params.get("shopaudio") !== "0"
      );
    } catch (_) {
      return true;
    }
  }

  async function playQueueEntry(entry) {
    const mode =
      entry.mode || "stream";

    if (
      mode === "local"
      && !settings.localEnabled
      && !entry.force
    ) {
      return;
    }

    if (
      mode === "stream"
      && !streamAudioEnabled()
    ) {
      return;
    }

    const announcement =
      announcementFor(
        entry.message,
        mode
      );

    await playEffect(
      announcement.kind
    );

    await delay(140);

    await speak(
      announcement.intro
    );

    if (
      announcement.detail
    ) {
      await delay(120);

      await speak(
        announcement.detail
      );
    }
  }

  async function drainQueue() {
    if (busy) return;

    busy = true;

    try {
      while (queue.length) {
        const entry =
          queue.shift();

        try {
          await playQueueEntry(
            entry
          );
        } catch (_) {
          // Ein Audiofehler darf weitere Meldungen nicht blockieren.
        }
      }
    } finally {
      busy = false;
    }
  }

  function enqueue(
    message,
    {
      mode = "stream",
      force = false,
    } = {}
  ) {
    if (
      !message
      || ![
        "shop_purchase_popup",
        "shop_donation_popup",
      ].includes(message.type)
    ) {
      return;
    }

    queue.push({
      message: {...message},
      mode,
      force,
    });

    drainQueue();
  }

  function test(
    kind = "donation"
  ) {
    unlock();

    if (kind === "purchase") {
      enqueue(
        {
          type:
            "shop_purchase_popup",
          name: "Audio Test",
          amount: "25.00",
          item_name: "Bobs 27",
          stream_text:
            "Tzmarty und Korsar spielen als Nächstes eine Runde Bobs 27.",
          message: "",
        },
        {
          mode: "local",
          force: true,
        }
      );

      return;
    }

    enqueue(
      {
        type:
          "shop_donation_popup",
        name: "Audio Test",
        amount: "10.00",
        message:
          "Viel Erfolg euch beiden und haltet durch!",
      },
      {
        mode: "local",
        force: true,
      }
    );
  }

  function syncControlPanel() {
    const toggle =
      document.getElementById(
        "dartAudioEnabled"
      );

    const topButton =
      document.getElementById(
        "dartAudioPanelButton"
      );

    const effect =
      document.getElementById(
        "dartAudioEffectVolume"
      );

    const speech =
      document.getElementById(
        "dartAudioSpeechVolume"
      );

    const rate =
      document.getElementById(
        "dartAudioSpeechRate"
      );

    const messages =
      document.getElementById(
        "dartAudioLocalMessages"
      );

    if (toggle) {
      toggle.checked =
        settings.localEnabled;
    }

    if (topButton) {
      topButton.textContent =
        settings.localEnabled
          ? "AUDIO: AN"
          : "AUDIO: AUS";
    }

    if (effect) {
      effect.value =
        Math.round(
          settings.effectVolume
          * 100
        );
    }

    if (speech) {
      speech.value =
        Math.round(
          settings.speechVolume
          * 100
        );
    }

    if (rate) {
      rate.value =
        Math.round(
          settings.speechRate
          * 100
        );
    }

    if (messages) {
      messages.checked =
        settings.localMessageTts;
    }

    const effectValue =
      document.getElementById(
        "dartAudioEffectValue"
      );

    const speechValue =
      document.getElementById(
        "dartAudioSpeechValue"
      );

    const rateValue =
      document.getElementById(
        "dartAudioRateValue"
      );

    if (effectValue) {
      effectValue.textContent =
        `${Math.round(
          settings.effectVolume
          * 100
        )} %`;
    }

    if (speechValue) {
      speechValue.textContent =
        `${Math.round(
          settings.speechVolume
          * 100
        )} %`;
    }

    if (rateValue) {
      rateValue.textContent =
        `${Math.round(
          settings.speechRate
          * 100
        )} %`;
    }
  }

  function mountControlPanel() {
    if (
      !isControlPage
      || document.getElementById(
        "dartAudioPanel"
      )
    ) {
      return;
    }

    const host =
      document.querySelector(
        ".top-actions"
      );

    if (!host) {
      return;
    }

    const style =
      document.createElement(
        "style"
      );

    style.id =
      "dartAudioPanelStyle";

    style.textContent = `
      .dart-audio-panel-button {
        min-width: 104px;
      }

      .dart-audio-panel {
        position: fixed;
        z-index: 5000;
        top: 92px;
        right: 18px;
        width: min(
          360px,
          calc(100vw - 24px)
        );
        padding: 16px;
        border:
          1px solid
          rgba(255,255,255,.16);
        border-radius: 14px;
        background:
          rgba(14,18,24,.97);
        box-shadow:
          0 18px 60px
          rgba(0,0,0,.45);
        color: #fff;
        font-family: inherit;
      }

      .dart-audio-panel.hidden {
        display: none;
      }

      .dart-audio-panel h3 {
        margin: 0 0 12px;
        font-size: 16px;
        letter-spacing: .08em;
      }

      .dart-audio-row {
        display: grid;
        grid-template-columns:
          1fr auto;
        gap: 12px;
        align-items: center;
        margin: 10px 0;
        font-size: 13px;
      }

      .dart-audio-range {
        grid-column: 1 / -1;
        width: 100%;
      }

      .dart-audio-check {
        display: flex;
        gap: 10px;
        align-items: center;
        margin: 10px 0;
        font-size: 13px;
      }

      .dart-audio-tests {
        display: grid;
        grid-template-columns:
          1fr 1fr;
        gap: 8px;
        margin-top: 14px;
      }

      .dart-audio-note {
        margin-top: 10px;
        opacity: .72;
        font-size: 11px;
        line-height: 1.4;
      }
    `;

    document.head.appendChild(
      style
    );

    const button =
      document.createElement(
        "button"
      );

    button.id =
      "dartAudioPanelButton";

    button.className =
      "btn ghost dart-audio-panel-button";

    button.type = "button";

    host.insertBefore(
      button,
      host.firstChild
    );

    const panel =
      document.createElement(
        "div"
      );

    panel.id =
      "dartAudioPanel";

    panel.className =
      "dart-audio-panel hidden";

    panel.innerHTML = `
      <h3>SHOP-AUDIO · VOR ORT</h3>

      <label class="dart-audio-check">
        <input id="dartAudioEnabled" type="checkbox">
        <span>Audio auf diesem Gerät wiedergeben</span>
      </label>

      <div class="dart-audio-row">
        <span>Effektlautstärke</span>
        <b id="dartAudioEffectValue">70 %</b>
        <input id="dartAudioEffectVolume" class="dart-audio-range" type="range" min="0" max="100" step="5">
      </div>

      <div class="dart-audio-row">
        <span>Sprachlautstärke</span>
        <b id="dartAudioSpeechValue">100 %</b>
        <input id="dartAudioSpeechVolume" class="dart-audio-range" type="range" min="0" max="100" step="5">
      </div>

      <div class="dart-audio-row">
        <span>Sprechtempo</span>
        <b id="dartAudioRateValue">95 %</b>
        <input id="dartAudioSpeechRate" class="dart-audio-range" type="range" min="70" max="130" step="5">
      </div>

      <label class="dart-audio-check">
        <input id="dartAudioLocalMessages" type="checkbox">
        <span>Spendernachricht vor Ort vorlesen</span>
      </label>

      <div class="dart-audio-tests">
        <button id="dartAudioTestDonation" class="mini-btn positive" type="button">TEST SPENDE</button>
        <button id="dartAudioTestPurchase" class="mini-btn warning" type="button">TEST FOLTERSHOP</button>
      </div>

      <div class="dart-audio-note">
        Bei echten Zahlungen läuft die Ansage hier zusätzlich zum Stream.
        Die Testbuttons testen nur dieses Gerät.
      </div>
    `;

    document.body.appendChild(
      panel
    );

    button.addEventListener(
      "click",
      async () => {
        await unlock();

        panel.classList.toggle(
          "hidden"
        );
      }
    );

    document.getElementById(
      "dartAudioEnabled"
    ).addEventListener(
      "change",
      (event) => {
        settings.localEnabled =
          Boolean(
            event.target.checked
          );

        saveSettings();
        unlock();
      }
    );

    document.getElementById(
      "dartAudioEffectVolume"
    ).addEventListener(
      "input",
      (event) => {
        settings.effectVolume =
          clamp(
            Number(
              event.target.value
            ) / 100,
            0,
            1
          );

        saveSettings();
      }
    );

    document.getElementById(
      "dartAudioSpeechVolume"
    ).addEventListener(
      "input",
      (event) => {
        settings.speechVolume =
          clamp(
            Number(
              event.target.value
            ) / 100,
            0,
            1
          );

        saveSettings();
      }
    );

    document.getElementById(
      "dartAudioSpeechRate"
    ).addEventListener(
      "input",
      (event) => {
        settings.speechRate =
          clamp(
            Number(
              event.target.value
            ) / 100,
            0.70,
            1.30
          );

        saveSettings();
      }
    );

    document.getElementById(
      "dartAudioLocalMessages"
    ).addEventListener(
      "change",
      (event) => {
        settings.localMessageTts =
          Boolean(
            event.target.checked
          );

        saveSettings();
      }
    );

    document.getElementById(
      "dartAudioTestDonation"
    ).addEventListener(
      "click",
      () => test("donation")
    );

    document.getElementById(
      "dartAudioTestPurchase"
    ).addEventListener(
      "click",
      () => test("purchase")
    );

    document.addEventListener(
      "click",
      (event) => {
        if (
          panel.classList.contains(
            "hidden"
          )
          || panel.contains(
            event.target
          )
          || button.contains(
            event.target
          )
        ) {
          return;
        }

        panel.classList.add(
          "hidden"
        );
      }
    );

    syncControlPanel();
  }

  function connectLocalControlAudio() {
    if (!isControlPage) {
      return;
    }

    clearTimeout(
      localRetryTimer
    );

    const proto =
      location.protocol === "https:"
        ? "wss"
        : "ws";

    localWs = new WebSocket(
      `${proto}://${location.host}/dartmarathon/ws`
    );

    localWs.onmessage = (event) => {
      let message;

      try {
        message =
          JSON.parse(event.data);
      } catch (_) {
        return;
      }

      if (
        message.type
          === "shop_purchase_popup"
        || message.type
          === "shop_donation_popup"
      ) {
        enqueue(
          message,
          {mode: "local"}
        );
      }
    };

    localWs.onclose = () => {
      clearTimeout(
        localRetryTimer
      );

      localRetryTimer = setTimeout(
        connectLocalControlAudio,
        1800
      );
    };

    localWs.onerror = () => {
      try {
        localWs.close();
      } catch (_) {
        // Nächster Reconnect übernimmt.
      }
    };
  }

  window.DartShopAudio = {
    enqueue,
    test,
    unlock,
    getSettings:
      () => ({...settings}),
  };

  primeVoices();

  if (
    "speechSynthesis" in window
  ) {
    window.speechSynthesis.onvoiceschanged =
      () => {
        voicesReady = true;
      };
  }

  if (
    document.readyState
    === "loading"
  ) {
    document.addEventListener(
      "DOMContentLoaded",
      () => {
        mountControlPanel();
        connectLocalControlAudio();
      },
      {once: true}
    );
  } else {
    mountControlPanel();
    connectLocalControlAudio();
  }
})();
