(()=>{'use strict';
function add(){const menu=document.querySelector('#menuView .menu');if(!menu||document.querySelector('#profileStatistics'))return;
const b=document.createElement('button');b.id='profileStatistics';b.className='menucard';b.innerHTML='STATISTIK<small>Spielerprofile · X01 · Training · Turniere</small>';b.onclick=()=>location.href='/dart/statistics/';menu.appendChild(b)}
if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',add);else add();
})();
