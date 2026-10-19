/* Phase 6: isolated game IDs, rounds target, red Sau, final summary. */
(() => {
  'use strict';
  const gameKey = 'stingrays_current_game';
  let lastReportId = '';
  const oldApi = api;
  api = async function(path, data) {
    // All state and mutation requests carry a tab-specific game identifier.
    const gameId = sessionStorage.getItem(gameKey) || '';
    const isGame = ['state','throw','next-sau','new','undo'].includes(path);
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


  // A bull finish is possible only if final dart is double bull (50),
  // with exactly the selected number of darts and legal prior hits.
  const bullHits = [...new Set([
    ...Array.from({length:20},(_,i)=>i+1),25,50,
    ...Array.from({length:20},(_,i)=>2*(i+1)),
    ...Array.from({length:20},(_,i)=>3*(i+1))
  ])];
  function canFinishOnBull(rest,darts) {
    if(darts === 1) return rest === 50;
    if(darts === 2) return bullHits.includes(rest-50);
    if(darts === 3) return bullHits.some(n=>bullHits.includes(rest-50-n));
    return false;
  }
  // Only ask for missed doubles when the entered visit leaves <=50 points.
  // The server still decides whether the visit or a checkout is valid.
  const previousBook = book;
  book = function(isSau) {
    if (isSau || !S || S.kind !== 'x01' || S.done) return previousBook(isSau);
    const raw = entry;
    if (raw === '') return;
    const points = Number(raw);
    if (!Number.isInteger(points) || points < 0 || points > 180) return previousBook(isSau);
    const remaining = S.remaining[S.current];
    if (points === remaining) return previousBook(isSau);
    if (remaining - points > 50) {
      void send(points);
      return;
    }
    return previousBook(isSau);
  };

  // X01: Ziffern 1, 2, 3 kurz antippen => Eingabe, lange halten => direkter Checkout.
  // Touch und Maus; nach Long-Press wird das nachfolgende click unterdrückt.
  const holdPanel=document.getElementById('hold');
  holdPanel.classList.add('hide');
  const cssHold=document.createElement('style');
  cssHold.textContent='#hold{display:none!important} #pad button:nth-child(-n+3){touch-action:none} #pad button.checkout-ready{background:#087e47!important;border:2px solid #6affae!important;color:#fff!important;box-shadow:inset 0 0 0 1px #14633c}';
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
        if (canFinishOnBull(rest,darts)) {
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
    [1,2,3].forEach((d,i)=>padButtons[i]?.classList.toggle('checkout-ready',
      S?.kind==='x01' && !S.done && !!S.can_checkout?.includes(d)));
    if(S?.kind==='x01' && S.can_checkout?.length) document.getElementById('last').textContent='Grüne 1 / 2 / 3 halten (0,7 Sek.) = Checkout';
  };

  // Revoke exactly the latest successful scoring action, independently for each game ID.
  const undoStyle=document.createElement('style');
  undoStyle.textContent='#undoX01,#undoSau,#undoFinished{background:#37495f;border:1px solid #c7a86a;color:#fff;font-weight:800;min-height:38px}';
  document.head.appendChild(undoStyle);
  function addUndoButton(parent,id){
    let b=document.getElementById(id);
    if(!b){b=document.createElement('button');b.id=id;b.type='button';b.textContent='↶ LETZTE AUFNAHME ZURÜCK';parent.appendChild(b)}
    b.disabled=!S?.can_undo;
    b.onclick=async()=>{
      if(busy || !S?.can_undo)return;
      if(!confirm('Letzte Aufnahme zurücknehmen? Auch Checkout, Legwechsel und Statistiken werden korrigiert.'))return;
      busy=true;
      try{S=await api('undo',{});entry='';sauEntry='';closeModal();lastReportId='';if(S.kind==='sau')showSau();else showMatch()}
      catch(e){err(e.message)}finally{busy=false}
    };
  }
  const renderMatchWithUndo=showMatch;
  showMatch=function(){
    renderMatchWithUndo();
    const panel=document.querySelector('#scorerView .columns .box');
    if(panel) addUndoButton(panel,'undoX01');
    if(S?.done){const footer=document.querySelector('#modalContent .actions');if(footer)addUndoButton(footer,'undoFinished')}
  };
  const renderSauWithUndo=showSau;
  showSau=function(){
    renderSauWithUndo();
    const panel=document.querySelector('#sauView .sau .panel');
    if(panel)addUndoButton(panel,'undoSau');
    if(S?.finished){const footer=document.querySelector('#modalContent .actions');if(footer)addUndoButton(footer,'undoFinished')}
  };

  // Reload restores the current browser tab's match without affecting other devices.
  if (sessionStorage.getItem(gameKey)) {
    api('state').then(s=>{S=s;if(s.kind==='sau')showSau();else if(s.kind==='x01')showMatch()}).catch(()=>{});
  }
})();
