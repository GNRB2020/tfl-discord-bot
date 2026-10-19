/* Phase 6: isolated game IDs, rounds target, red Sau, final summary. */
(() => {
  'use strict';
  const gameKey = 'stingrays_current_game';
  let lastReportId = '';
  const oldApi = api;
  api = async function(path, data) {
    // All state and mutation requests carry a tab-specific game identifier.
    const gameId = sessionStorage.getItem(gameKey) || '';
    const isGame = ['state','throw','next-sau','new'].includes(path);
    if (!isGame) {
      const result = await oldApi(path,data);
      if (path === 'logout') sessionStorage.removeItem(gameKey);
      return result;
    }
    const response = await fetch('/dart/api/' + path, {
      method:data === undefined ? 'GET' : 'POST',
      credentials:'same-origin', cache:'no-store',
      headers:{'Content-Type':'application/json', 'X-Dart-Game-ID':gameId},
      body:data === undefined ? undefined : JSON.stringify(data),
    });
    const result = await response.json().catch(() => ({}));
    if (!response.ok) throw Error(result.error || 'HTTP ' + response.status);
    if (path === 'new' && result.game_id) {
      sessionStorage.setItem(gameKey,result.game_id);
      lastReportId = '';
    }
    return result;
  };

  const css = document.createElement('style');
  css.textContent = `
    #sauView .sau .panel:last-child{border:2px solid #69343d}
    #sauView #marks span:first-child {background:#9e1725;color:white;font-size:clamp(15px,2.4vh,22px);font-weight:900;grid-column:span 2;border:2px solid #ff6c76;box-shadow:0 0 0 1px #4d1920}
    #sauWarning {background:linear-gradient(110deg,#7e1422,#ba2331);border:2px solid #f26a77;border-radius:12px;padding:clamp(8px,1.5vh,16px);font-size:clamp(21px,4vh,36px);font-weight:950;text-align:center;color:white;margin:6px 0}
    #sauRoundsInfo {color:#e0e7ed;font-size:clamp(11px,1.6vh,15px);text-align:center}
    #sauView .sau .panel:last-child h3{color:#ff8f99}
    .sauReportTable{width:100%;border-collapse:collapse;margin:12px 0}
    .sauReportTable td,.sauReportTable th{padding:7px 12px;border-bottom:1px solid #405065;text-align:left}
    .sauReportTable td:last-child,.sauReportTable th:last-child{text-align:right}
    .sauReportTotal{background:#7c1927;border-radius:10px;padding:15px;text-align:center;color:#fff;font-weight:900;font-size:22px}
    @media(max-height:550px){#sauWarning{padding:5px;margin:1px 0}}
  `;
  document.head.appendChild(css);

  const baseShowSau = showSau;
  showSau = function() {
    baseShowSau();
    if (!S || S.kind !== 'sau') return;
    let banner = document.getElementById('sauWarning');
    if (!banner) {
      banner=document.createElement('div');banner.id='sauWarning';
      document.getElementById('marks').before(banner);
    }
    banner.textContent='DIE SAU  '+S.marks.sau+' / '+(S.sau_target||10);
    let info=document.getElementById('sauRoundsInfo');
    if (!info) {info=document.createElement('div');info.id='sauRoundsInfo';banner.after(info)}
    info.textContent='Abgeschlossene Runden: '+S.completed_rounds+' / Mindestzahl '+S.rounds_target;
    document.getElementById('nextsau').classList.toggle('hide',!S.done||S.finished);
    if (S.finished && S.result && lastReportId !== S.game_id) {
      lastReportId=S.game_id;
      sauFinalReport(S.result);
    }
  };

  function sauFinalReport(r) {
    const rows = Array.from({length:9},(_,i)=>i+4)
      .map(n=>`<tr><td>${n} Darts</td><td>${Number(r.checkout_counts[String(n)]||0)}</td></tr>`).join('');
    modal(`<h2>Gegen die Sau – beendet</h2>
      <div class="sauReportTotal">DIE SAU: ${r.sau} / 10</div>
      <p><b>${escapeHtml(r.player)}</b> · ${r.rounds} Durchgänge gespielt · ${r.checkouts} erfolgreiche Checkouts</p>
      <table class="sauReportTable"><thead><tr><th>Checkout mit</th><th>Anzahl</th></tr></thead><tbody>${rows}</tbody></table>
      <div class="actions"><button id="closeSauFinal">SCHLIESSEN</button><button class="green" id="restartSauFinal">NEUES TRAINING</button></div>`);
    document.getElementById('closeSauFinal').onclick=closeModal;
    document.getElementById('restartSauFinal').onclick=()=>{closeModal();screen('menuView');document.getElementById('sau').click()};
  }
  function escapeHtml(v) {const d=document.createElement('div');d.textContent=String(v);return d.innerHTML}

  document.getElementById('sau').onclick = () => {
    modal(`<h2>Gegen die Sau</h2>
      <label>Spielername<input id="sauName" maxlength="45" value="Spieler 1"></label>
      <label>Rundenzahl (Mindestzahl)<input id="sauRounds" type="number" min="1" max="10000" value="10"></label>
      <p class="hint">Das Training endet nach mindestens dieser Rundenzahl, sobald die Sau 10 Striche hat. Eigene Checkouts sind unbegrenzt.</p>
      <div class="actions"><button id="cancelSauStart">ABBRECHEN</button><button id="goSauStart" class="green">STARTEN</button></div>`);
    document.getElementById('cancelSauStart').onclick=closeModal;
    document.getElementById('goSauStart').onclick=async()=>{
      const name=document.getElementById('sauName').value;
      const rounds=Number(document.getElementById('sauRounds').value);
      if (!Number.isInteger(rounds)||rounds<1||rounds>10000){err('Rundenzahl 1 bis 10000 eingeben');return}
      try {S=await api('new',{kind:'sau',a:name,rounds});closeModal();showSau()}
      catch(e){err(e.message)}
    };
  };

  // Phase 7: In der Sau keine Bull-Abfrage; Wahl der Dartzahl bleibt erhalten.
  const originalCheckoutDialog = checkoutDialog;
  checkoutDialog = function(isSau, selected) {
    if (!isSau) return originalCheckoutDialog(isSau, selected);
    const rest = S.remaining;
    const choices = possible(rest);
    if (!choices.length) return err('Kein Checkout möglich');
    let picked = choices.includes(selected) ? selected : choices[0];
    modal(`<h2>Checkout · ${rest} Rest</h2><p>Mit wie vielen Darts gecheckt?</p>
      <div class="actions" id="sauDartChoices"></div>
      <div class="actions"><button id="cancelSauCheck">ABBRECHEN</button>
      <button id="confirmSauCheck" class="green">CHECK BUCHEN</button></div>`);
    const container=document.getElementById('sauDartChoices');
    function draw() {
      container.replaceChildren();
      choices.forEach(n=>{const b=document.createElement('button'); b.textContent=n+' Dart'+(n===1?'':'s');
        b.className=n===picked?'green':''; b.onclick=()=>{picked=n;draw()};container.appendChild(b)});
    }
    draw();
    document.getElementById('cancelSauCheck').onclick=closeModal;
    document.getElementById('confirmSauCheck').onclick=()=>{closeModal();send(rest,{checkout:true,darts:picked,checkout_attempts:1,bullfinish:false})};
  };

  // X01: Ziffern 1, 2, 3 kurz antippen => Eingabe, lange halten => direkter Checkout.
  // Touch und Maus; nach Long-Press wird das nachfolgende click unterdrückt.
  const holdPanel=document.getElementById('hold');
  holdPanel.classList.add('hide');
  const cssHold=document.createElement('style');
  cssHold.textContent='#hold{display:none!important} #pad button:nth-child(-n+3){touch-action:none}';
  document.head.appendChild(cssHold);
  const padButtons=Array.from(document.querySelectorAll('#pad button'));
  [1,2,3].forEach((darts,index)=>{
    const button=padButtons[index];
    if (!button) return;
    let timer=null, longPressed=false, suppressClick=false;
    button.addEventListener('pointerdown',ev=>{
      if (!S || S.kind!=='x01' || S.done || !S.can_checkout?.includes(darts)) return;
      if (ev.button!==0 || busy) return;
      longPressed=false;
      timer=setTimeout(()=>{
        timer=null;longPressed=true;suppressClick=true;
        const rest=S.remaining[S.current];
        const finish=()=>send(rest,{checkout:true,darts,checkout_attempts:1,bullfinish:false});
        if (rest>=50) {
          modal(`<h2>Bullfinish?</h2><p>Wurde das Checkout über Bullseye beendet?</p>
            <div class="actions"><button id="bullNo">NEIN</button><button class="green" id="bullYes">JA</button></div>
            <div class="actions"><button id="bullCancel">ABBRECHEN</button></div>`);
          document.getElementById('bullNo').onclick=()=>{closeModal();finish()};
          document.getElementById('bullYes').onclick=()=>{closeModal();send(rest,{checkout:true,darts,checkout_attempts:1,bullfinish:true})};
          document.getElementById('bullCancel').onclick=closeModal;
        } else finish();
      },700);
    });
    const clear=()=>{if(timer!==null){clearTimeout(timer);timer=null}};
    for(const name of ['pointerup','pointercancel','pointerleave']) button.addEventListener(name,clear);
    button.addEventListener('click',ev=>{
      if(!suppressClick)return;
      ev.preventDefault();ev.stopImmediatePropagation();suppressClick=false;
    },true);
  });
  const prevShowMatch=showMatch;
  showMatch=function(){prevShowMatch();holdPanel.classList.add('hide');
    if(S?.kind==='x01' && S.can_checkout?.length) document.getElementById('last').textContent='1 / 2 / 3 halten (0,7 Sek.) = Checkout';
  };

  // Reload restores the current browser tab's match without affecting other devices.
  if (sessionStorage.getItem(gameKey)) {
    api('state').then(s=>{S=s;if(s.kind==='sau')showSau();else if(s.kind==='x01')showMatch()}).catch(()=>{});
  }
})();
