const $ = id => document.getElementById(id);
const money = n => n == null ? '—' : new Intl.NumberFormat('en-US', {style:'currency',currency:'USD',maximumFractionDigits:2}).format(n);
const num = n => new Intl.NumberFormat('ru-RU', {maximumFractionDigits:0}).format(n || 0);
const esc = s => String(s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
let data;
const today = new Date();
$('end').value = today.toISOString().slice(0,10);
$('start').value = new Date(today.getTime()-29*86400000).toISOString().slice(0,10);
async function api(path, options={}) {
  const response = await fetch(path, options);
  let body;
  try { body = await response.json(); } catch { throw new Error('Сервер недоступен. Повторите запрос.'); }
  if (!response.ok) throw new Error(typeof body.detail === 'string' ? body.detail : 'Проверьте параметры запроса.');
  return body;
}
function notice(message) { $('notice').textContent = message; $('notice').hidden = !message; }
function empty(text='Данные пока не загружены') { return `<div class="empty">${esc(text)}</div>`; }
function renderCreatives() {
  if (!data) return;
  const sort = $('sort').value;
  const rows = [...data.creatives].sort((a,b)=>sort==='cpi' ? (a.cpi??Infinity)-(b.cpi??Infinity) : (b[sort]??-1)-(a[sort]??-1));
  $('creative-count').textContent=rows.length;
  $('creative-rows').innerHTML = rows.length ? rows.map((r,i)=>`<tr><td title="${esc(r.creative)}"><span class="rank">${String(i+1).padStart(2,'0')}</span>${esc(r.creative)}</td><td>${money(r.spend)}</td><td>${num(r.installs)}</td><td>${money(r.cpi)}</td><td>${num(r.clicks)}</td><td>${num(r.deposits)}</td><td>${money(r.cpa)}</td><td><span class="matched ${r.matched_days===r.days?'':'unmatched'}">${r.matched_days}/${r.days} ключей</span></td></tr>`).join('') : '<tr><td colspan="8">'+empty('Загрузите данные Unity и CSV Keitaro, чтобы увидеть рейтинг.')+'</td></tr>';
}
function chart(rows) {
  if (!rows.length) return empty('Здесь появится динамика после первого импорта');
  const from = new Date(data.start+'T00:00:00Z'), to = new Date(data.end+'T00:00:00Z');
  const index = Object.fromEntries(rows.map(r=>[r.day,r.spend]));
  const points=[];
  for (let day=new Date(from);day<=to;day.setUTCDate(day.getUTCDate()+1)) points.push({day:day.toISOString().slice(0,10),value:index[day.toISOString().slice(0,10)]||0});
  const max=Math.max(...points.map(r=>r.value),1), w=720,h=165;
  const coords=points.map((r,i)=>[48+i*(w-60)/Math.max(points.length-1,1),12+(h-35)*(1-r.value/max)]);
  const line=coords.map(p=>p.join(',')).join(' ');
  return `<svg viewBox="0 0 720 200" role="img" aria-label="Расходы Unity за выбранный период"><defs><linearGradient id="fill" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stop-color="#008b76" stop-opacity=".18"/><stop offset="100%" stop-color="#008b76" stop-opacity=".01"/></linearGradient></defs>${[0,.5,1].map(f=>`<line x1="48" y1="${12+f*(h-35)}" x2="708" y2="${12+f*(h-35)}" stroke="#edf1f3" stroke-dasharray="3 4"/><text x="0" y="${16+f*(h-35)}" fill="#9aa8b0" font-size="10">$${num(max*(1-f))}</text>`).join('')}<polygon points="48,${h-23} ${line} ${coords.at(-1)[0]},${h-23}" fill="url(#fill)"/><polyline points="${line}" fill="none" stroke="#008b76" stroke-width="2.5" stroke-linejoin="round"/>${coords.map((p,i)=>`<circle cx="${p[0]}" cy="${p[1]}" r="3" fill="#008b76"><title>${points[i].day}: ${money(points[i].value)}</title></circle>`).join('')}<text x="48" y="190" fill="#9aa8b0" font-size="10">${data.start}</text><text x="708" y="190" text-anchor="end" fill="#9aa8b0" font-size="10">${data.end}</text></svg>`;
}
async function load() {
  $('apply').disabled=true;
  try {
    const params=new URLSearchParams({start:$('start').value,end:$('end').value,geo:$('geo-filter').value,search:$('search').value});
    data=await api('/api/dashboard?'+params);
    notice('');
    const selected=$('geo-filter').value;
    $('geo-filter').innerHTML='<option value="">Все GEO</option>'+data.geos.map(g=>`<option value="${esc(g)}">${esc(g)}</option>`).join('');
    $('geo-filter').value=selected;
    const t=data.total || {spend:0,installs:0,deposits:0,clicks:0,cpi:null,cpa:null};
    $('metrics').innerHTML=[['Общие расходы',money(t.spend),'Unity Ads · USD','↗'],['Установки',num(t.installs),'CPI <strong>'+money(t.cpi)+'</strong>','↓'],['Депозиты',num(t.deposits),'Keitaro · количество событий','◈'],['Клики',num(t.clicks),'CPA, прокси <strong>'+money(t.cpa)+'</strong>','↗']].map(([label,value,sub,icon])=>`<article class="metric"><div class="metric-label">${label}<span>${icon}</span></div><div class="metric-value">${value}</div><div class="metric-sub">${sub}</div></article>`).join('');
    $('chart').innerHTML=chart(data.daily);
    const countries=[...data.countries].sort((a,b)=>b.spend-a.spend).slice(0,5);
    $('countries').innerHTML=countries.length ? countries.map(r=>`<div class="country"><div class="country-head"><strong>${esc(r.geo)}</strong><span>${money(r.spend)} · ${num(r.installs)} уст.</span></div><div class="bar"><i style="width:${t.spend?100*r.spend/t.spend:0}%"></i></div></div>`).join('') : empty();
    renderCreatives();
    const geos=[...new Set(data.matrix.map(r=>r.geo))].sort();
    const creatives=[...data.creatives].sort((a,b)=>b.spend-a.spend).slice(0,50);
    const cells=new Map(data.matrix.map(r=>[JSON.stringify([r.creative,r.geo]),r]));
    $('matrix').innerHTML=creatives.length?`<table><thead><tr><th>КРЕАТИВ · ТОП 50 ПО РАСХОДУ</th>${geos.map(g=>`<th>${esc(g)}</th>`).join('')}</tr></thead><tbody>${creatives.map(r=>`<tr><td>${esc(r.creative)}</td>${geos.map(g=>{const c=cells.get(JSON.stringify([r.creative,g]));const rate=c?.deposit_rate;return `<td title="${c?`${num(c.installs)} установок / ${num(c.deposits)} депозитов`:'Нет данных'}"><span class="matrix-cell ${rate>=5?'high':rate>=2?'medium':''}">${rate==null?'—':rate.toFixed(1)}</span></td>`;}).join('')}</tr>`).join('')}</tbody></table>`:empty('Матрица появится после загрузки данных');
    $('offer-rows').innerHTML=data.offers.length?data.offers.map(r=>`<tr><td>${esc(r.offer)}</td><td>${num(r.clicks)}</td><td>${num(r.deposits)}</td></tr>`).join(''):'<tr><td colspan="3">'+empty()+'</td></tr>';
  } catch(e) { notice(e.message); }
  finally { $('apply').disabled=false; }
}
async function status() {
  try {
    const s=await api('/api/status');
    $('unity-status').textContent=s.sync?.error || (s.unity_configured ? (s.sync?.last_success ? 'Обновлено: '+new Date(s.sync.last_success).toLocaleString('ru-RU',{timeZone:'UTC'})+' UTC' : 'Настроено · ожидает первого импорта') : 'Нужны Organization ID и API key');
    $('history').innerHTML=s.imports.length?s.imports.map(i=>`<div class="history-row"><span>${esc(i.source)} · ${num(i.rows)} строк</span><span>${esc(new Date(i.created_at).toLocaleString('ru-RU',{timeZone:'UTC'}))} UTC</span></div>`).join(''):'<p class="muted">Импортов пока нет</p>';
  } catch(e) {notice(e.message);}
}
$('apply').addEventListener('click',load);
$('search').addEventListener('keydown',e=>{if(e.key==='Enter')load();});
$('sort').addEventListener('change',renderCreatives);
$('sync').addEventListener('click',async()=>{
  $('sync').disabled=true;notice('Загружаем отчёт Unity…');
  try {const r=await api('/api/sync',{method:'POST'});await load();notice(r.busy?'Синхронизация уже выполняется.':'Unity: обновлено '+r.rows+' строк.');}
  catch(e){notice(e.message);}finally{$('sync').disabled=false;await status();}
});
$('csv').addEventListener('change',async()=>{
  const file=$('csv').files[0];if(!file)return;
  if(file.size>10000000){$('import-result').textContent='Максимальный размер CSV — 10 MB';return;}
  const form=new FormData();form.append('file',file);$('csv').disabled=true;
  $('import-result').textContent='Проверяем и импортируем…';
  try {const r=await api('/api/import',{method:'POST',body:form});$('import-result').textContent=r.duplicate?'Этот файл уже загружен. Данные не изменены.':'Обновлено строк: '+r.rows;await load();await status();}
  catch(e){$('import-result').textContent=e.message;}finally{$('csv').disabled=false;$('csv').value='';}
});
document.querySelectorAll('nav a').forEach(a=>a.addEventListener('click',()=>{document.querySelectorAll('nav a').forEach(n=>n.classList.remove('active'));a.classList.add('active');}));
load();status();
