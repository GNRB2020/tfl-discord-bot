(() => {
  let ws;
  let retry;
  const $ = (id) => document.getElementById(id);
  function connect(){
    const proto = location.protocol === "https:" ? "wss" : "ws";
    ws = new WebSocket(`${proto}://${location.host}/dartmarathon/ws`);
    ws.onmessage = e => {
      const msg = JSON.parse(e.data);
      if(msg.type === "state") render(msg.data);
    };
    ws.onclose = () => { clearTimeout(retry); retry = setTimeout(connect, 1200); };
    ws.onerror = () => ws.close();
  }
  function render(s){
    $("ovTzmarty").textContent = s.legs.tzmarty;
    $("ovKorsar").textContent = s.legs.korsar;
    $("ovTotalLegs").textContent = s.total_legs;
    $("ovSpecials").textContent = s.total_specials;
    $("ovPause").textContent = s.pause_display;
    $("ovStream").textContent = s.stream_display;
    $("pauseCenterTime").textContent = s.pause_display;
    $("pauseCenter").classList.toggle("hidden", !s.pause_active || s.event_ended);
    $("eventEnded").classList.toggle("hidden", !s.event_ended);
  }
  connect();
})();
