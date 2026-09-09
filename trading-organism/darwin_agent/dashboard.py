"""Painel de apurações — dashboard web em tempo real lendo o estado do
Macro-organismo (`data/population.json`, escrito por `organism.py`). Não
tem lógica de decisão nenhuma — só lê e mostra (ver CLAUDE.md).

Mostra todo robô que já existiu (vivo ou morto): pico de capital, causa da
morte, tempo de vida, estratégia usada, clones gerados — e o ranking vivo
de estratégias (`leaderboard.py`). Atualiza sozinho via polling (o loop de
trading roda em heartbeats de dezenas de segundos a horas; não precisa de
websocket pra parecer "tempo real").

Uso: iniciado junto com `main.py run_forever` (mesma porta do
`config.dashboard_port`), ou standalone:
    python -c "import asyncio; from darwin_agent.dashboard import run_standalone; asyncio.run(run_standalone())"
"""

import glob
import json
import os

try:
    from aiohttp import web
except ImportError:
    web = None

DEFAULT_STATE_FILE = "data/population.json"
_state_file = DEFAULT_STATE_FILE


def set_state_file(path: str):
    global _state_file
    _state_file = path


def _logs_dir() -> str:
    # data/population.json -> data/logs (mesma raiz de dados)
    return os.path.join(os.path.dirname(_state_file) or "data", "logs")


def _history_file() -> str:
    # data/population.json -> data/history.jsonl (mesma raiz de dados,
    # ver Organism._record_history)
    return os.path.join(os.path.dirname(_state_file) or "data", "history.jsonl")


async def handle_history(req):
    """Série histórica de capital por robô, pra desenhar o gráfico de
    patrimônio no painel. Cada linha de `history.jsonl` é um snapshot no
    tempo (ver `Organism._record_history`); devolve as últimas `limit`
    linhas em ordem cronológica (mais antiga primeiro)."""
    limit = int(req.query.get("limit", "500"))
    path = _history_file()
    if not os.path.exists(path):
        return web.json_response({"history": []})
    try:
        with open(path) as f:
            lines = f.readlines()
    except OSError:
        return web.json_response({"history": []})
    out = []
    for line in lines[-limit:]:
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return web.json_response({"history": out})


async def handle_positions(req):
    """Posições fechadas recentes de toda a população — hora de entrada,
    lado (buy/sell), hora de saída, preços, P&L. Lê os arquivos
    trades_<robot_id>.jsonl (um por robô, ver utils/logger.py). Em
    populações muito grandes isto acaba precisando de índice/banco em vez
    de varrer arquivo por arquivo — suficiente pra esta fase."""
    limit = int(req.query.get("limit", "100"))
    robot_filter = req.query.get("robot") or None
    pattern = os.path.join(_logs_dir(), "trades_*.jsonl")
    records = []
    for path in glob.glob(pattern):
        try:
            with open(path) as f:
                lines = f.readlines()[-300:]  # só as últimas por arquivo, não o journal inteiro
        except OSError:
            continue
        for line in lines:
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if rec.get("type") != "position_closed":
                continue
            if robot_filter and rec.get("robot") != robot_filter:
                continue
            records.append(rec)
    records.sort(key=lambda r: r.get("exit_time") or r.get("ts") or "", reverse=True)
    return web.json_response({"positions": records[:limit]})


async def handle_state(req):
    if not os.path.exists(_state_file):
        return web.json_response({
            "updated_at": None, "population_alive": 0, "population_total": 0,
            "total_capital_alive": 0, "robots": [], "leaderboard_size": 0,
            "leaderboard_capacity": 0, "leaderboard_top": [], "track_records": [],
            "_empty": True,
        })
    try:
        with open(_state_file) as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        # Lido no meio de uma escrita atômica (raro, o Organism escreve via
        # tmp+rename) — devolve o último estado válido seria ideal, mas
        # como não guardamos cache aqui, só reporta vazio nessa rodada; o
        # próximo poll (3s depois) pega o arquivo já consistente.
        return web.json_response({"_empty": True, "_transient_error": True})
    return web.json_response(data)


async def handle_index(req):
    return web.Response(text=HTML, content_type="text/html")


HTML = """<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1">
<title>Painel de Apurações — Organismo de Trade</title>
<style>
:root{--bg:#0a0e14;--s:#131920;--b:#1e2530;--t:#d4d8de;--d:#6b7280;--g:#22c55e;--r:#ef4444;--y:#eab308;--bl:#3b82f6;--p:#8b5cf6}
*{margin:0;padding:0;box-sizing:border-box}
body{background:var(--bg);color:var(--t);font-family:-apple-system,system-ui,sans-serif;font-size:14px;-webkit-font-smoothing:antialiased}
.c{max-width:1200px;margin:0 auto;padding:12px}
.hdr{display:flex;align-items:center;justify-content:space-between;padding:12px 0;border-bottom:1px solid var(--b);margin-bottom:12px;flex-wrap:wrap;gap:8px}
.hdr h1{font-size:16px;color:var(--bl);letter-spacing:1px}
.hdr .tag{font-size:11px;padding:3px 8px;border-radius:4px;background:#1e293b;color:var(--d)}
.stats{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin-bottom:14px}
@media(max-width:700px){.stats{grid-template-columns:repeat(2,1fr)}}
.stat{background:var(--s);border:1px solid var(--b);border-radius:8px;padding:12px;text-align:center}
.stat .n{font-size:22px;font-weight:700}
.stat .l{font-size:11px;color:var(--d);text-transform:uppercase;letter-spacing:.5px;margin-top:2px}
.card{background:var(--s);border:1px solid var(--b);border-radius:8px;padding:14px;margin-bottom:14px}
.card h2{font-size:12px;color:var(--d);text-transform:uppercase;letter-spacing:1px;margin-bottom:10px;display:flex;justify-content:space-between}
.g{color:var(--g)}.r{color:var(--r)}.y{color:var(--y)}.bl{color:var(--bl)}
table{width:100%;border-collapse:collapse;font-size:12px}
th{text-align:left;color:var(--d);padding:6px 8px;border-bottom:1px solid var(--b);font-size:11px;white-space:nowrap;cursor:default}
td{padding:6px 8px;border-bottom:1px solid #1a1f28;white-space:nowrap}
tbody tr:hover{background:#161c26}
.tblwrap{overflow-x:auto}
.badge{display:inline-block;padding:2px 7px;border-radius:3px;font-size:10px;font-weight:600}
.bg{background:#14532d;color:var(--g)}.br{background:#450a0a;color:var(--r)}.by{background:#422006;color:var(--y)}.bb{background:#172554;color:var(--bl)}
.mono{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:11px;color:var(--d)}
.ft{text-align:center;padding:8px;color:var(--d);font-size:11px}
.dot{width:6px;height:6px;border-radius:50%;display:inline-block;margin-right:4px;animation:pulse 2s infinite}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:.3}}
.dot-g{background:var(--g)}.dot-r{background:var(--r)}
.death{font-size:11px;color:var(--r);max-width:220px;overflow:hidden;text-overflow:ellipsis}
.empty{color:var(--d);text-align:center;padding:16px;font-size:12px}
.bar{height:6px;background:var(--b);border-radius:3px;overflow:hidden;width:80px;display:inline-block;vertical-align:middle}
.bar .f{height:100%;background:var(--bl)}
.robot-cards{display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:10px}
.robot-card{background:#0f1520;border:1px solid var(--b);border-radius:8px;padding:12px}
.robot-card .rc-hdr{display:flex;justify-content:space-between;align-items:center;margin-bottom:6px}
.robot-card .rc-id{font-family:ui-monospace,monospace;font-size:11px;color:var(--d)}
.robot-card .rc-title{font-size:13px;font-weight:700;margin-bottom:2px}
.robot-card .rc-sub{font-size:11px;color:var(--d);margin-bottom:8px}
.robot-card .rc-row{font-size:11px;margin:4px 0;line-height:1.4}
.robot-card .rc-row b{color:var(--d);font-weight:600}
.chip{display:inline-block;background:#172554;color:var(--bl);border-radius:10px;padding:1px 7px;font-size:10px;margin:1px 2px 1px 0}
.trackbox{margin-top:8px;padding:6px 8px;background:#131a24;border-radius:6px;font-size:11px}
.trackbox .tr-title{color:var(--d);font-size:9px;text-transform:uppercase;letter-spacing:.5px;margin-bottom:3px}
.more-note{grid-column:1/-1;text-align:center;color:var(--d);font-size:11px;padding:6px}
.eq-controls{display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin-bottom:10px}
.eq-controls select{background:#0f1520;color:var(--t);border:1px solid var(--b);border-radius:6px;padding:5px 8px;font-size:11px}
.eq-controls label.chk{display:flex;align-items:center;gap:4px;font-size:11px;color:var(--d);cursor:pointer;background:#0f1520;border:1px solid var(--b);border-radius:6px;padding:5px 8px}
.eq-controls label.chk input{margin:0}
.eq-layout{display:grid;grid-template-columns:200px 1fr;gap:12px}
@media(max-width:700px){.eq-layout{grid-template-columns:1fr}}
.eq-picker{max-height:280px;overflow-y:auto;background:#0f1520;border:1px solid var(--b);border-radius:6px;padding:6px}
.eq-picker label{display:flex;align-items:center;gap:6px;font-size:11px;padding:3px 4px;border-radius:4px;cursor:pointer}
.eq-picker label:hover{background:#161c26}
.eq-picker input{margin:0}
.eq-swatch{width:8px;height:8px;border-radius:50%;display:inline-block;flex:none}
.eq-chartwrap{background:#0f1520;border:1px solid var(--b);border-radius:6px;padding:8px}
#eq-svg{width:100%;height:260px;display:block}
.eq-legend{display:flex;flex-wrap:wrap;gap:10px;margin-top:8px;font-size:11px;color:var(--d)}
.eq-legend .li{display:flex;align-items:center;gap:5px}
.eq-empty-list{color:var(--d);font-size:11px;padding:6px;text-align:center}
.risk-caps{display:grid;grid-template-columns:1fr 1fr;gap:14px;margin-bottom:14px}
@media(max-width:700px){.risk-caps{grid-template-columns:1fr}}
.risk-cap-box .rc-label{display:flex;justify-content:space-between;font-size:11px;color:var(--d);margin-bottom:4px}
.risk-cap-box .rc-bar{height:10px;background:var(--b);border-radius:5px;overflow:hidden}
.risk-cap-box .rc-fill{height:100%;background:var(--bl);transition:width .3s}
.risk-cap-box .rc-fill.warn{background:var(--y)}
.risk-cap-box .rc-fill.full{background:var(--r)}
.risk-pending{margin-bottom:10px;font-size:11px;color:var(--y)}
.risk-tables{display:grid;grid-template-columns:1fr 1fr;gap:14px}
@media(max-width:700px){.risk-tables{grid-template-columns:1fr}}
</style>
</head>
<body>
<div class="c">
<div class="hdr">
<h1>🧬 PAINEL DE APURAÇÕES</h1>
<div><span class="tag" id="updated"></span> <span class="dot dot-g" id="dot"></span></div>
</div>

<div class="stats">
<div class="stat"><div class="n g" id="st-alive">-</div><div class="l">Vivos</div></div>
<div class="stat"><div class="n" id="st-total">-</div><div class="l">Já existiram</div></div>
<div class="stat"><div class="n bl" id="st-capital">-</div><div class="l">Capital vivo</div></div>
<div class="stat"><div class="n y" id="st-lb">-</div><div class="l">Estratégias no ranking</div></div>
</div>

<div class="card">
<h2><span>Sala de Risco (Estrategista) — tetos de concentração</span><span class="mono" id="risk-updated"></span></h2>
<div class="risk-caps">
  <div class="risk-cap-box">
    <div class="rc-label"><span>População viva</span><span id="risk-pop-label">-</span></div>
    <div class="rc-bar"><div class="rc-fill" id="risk-pop-fill"></div></div>
  </div>
  <div class="risk-cap-box">
    <div class="rc-label"><span>Nichos no limite (estratégia+ativo)</span><span id="risk-niche-label">-</span></div>
    <div class="rc-bar"><div class="rc-fill" id="risk-niche-fill"></div></div>
  </div>
</div>
<div class="risk-pending" id="risk-pending"></div>
<div class="risk-tables">
  <div>
    <div class="mono" style="color:var(--d);font-size:11px;margin-bottom:6px">CONCENTRAÇÃO POR NICHO (estratégia+ativo)</div>
    <div class="tblwrap"><table>
      <thead><tr><th>Estratégia</th><th>Ativo</th><th>Vivos</th><th>Capital</th></tr></thead>
      <tbody id="risk-niche-body"></tbody>
    </table></div>
  </div>
  <div>
    <div class="mono" style="color:var(--d);font-size:11px;margin-bottom:6px">CONCENTRAÇÃO POR ATIVO</div>
    <div class="tblwrap"><table>
      <thead><tr><th>Ativo</th><th>Robôs vivos</th><th>Capital</th></tr></thead>
      <tbody id="risk-asset-body"></tbody>
    </table></div>
  </div>
</div>
</div>

<div class="card">
<h2><span>Ranking de estratégias (Estrategista)</span><span class="mono" id="lb-cap"></span></h2>
<div class="tblwrap"><table>
<thead><tr><th>Score</th><th>Estratégia</th><th>Motor</th><th>TF</th><th>Clones</th><th>Mortes</th><th>Tentativas</th><th>Fonte</th></tr></thead>
<tbody id="lb-body"></tbody>
</table></div>
</div>

<div class="card">
<h2><span>População — todo robô que já existiu</span><span class="mono" id="pop-count"></span></h2>
<div class="tblwrap"><table>
<thead><tr><th>ID</th><th>Pai</th><th>Ativo</th><th>Estratégia</th><th>TF</th><th>Status</th><th>Capital</th><th>Pico</th><th>DD%</th><th>Trades</th><th>WR</th><th>Clones</th><th>Tempo de vida</th><th>Causa da morte</th></tr></thead>
<tbody id="pop-body"></tbody>
</table></div>
</div>

<div class="card">
<h2><span>Como cada robô opera — estratégia e histórico do Estrategista</span><span class="mono" id="ops-count"></span></h2>
<div id="ops-grid" class="robot-cards"></div>
</div>

<div class="card">
<h2><span>Patrimônio — evolução do capital ao longo do tempo</span><span class="mono" id="eq-count"></span></h2>
<div class="eq-controls">
  <select id="eq-f-strategy"><option value="">Todas estratégias</option></select>
  <select id="eq-f-symbol"><option value="">Todos ativos</option></select>
  <select id="eq-f-status"><option value="">Vivos e mortos</option><option value="alive">Só vivos</option><option value="dead">Só mortos</option></select>
  <label class="chk"><input type="checkbox" id="eq-global"> Global (capital vivo total)</label>
  <label class="chk"><input type="checkbox" id="eq-merge"> Mesclar selecionados numa linha</label>
</div>
<div class="eq-layout">
  <div class="eq-picker" id="eq-picker"></div>
  <div class="eq-chartwrap">
    <svg id="eq-svg" viewBox="0 0 900 260" preserveAspectRatio="none"></svg>
    <div class="eq-legend" id="eq-legend"></div>
  </div>
</div>
</div>

<div class="card">
<h2><span>Posições — entrada e saída de cada operação</span><span class="mono" id="pos-count"></span></h2>
<div class="tblwrap"><table>
<thead><tr><th>Robô</th><th>Ativo</th><th>Lado</th><th>Entrada</th><th>Preço entrada</th><th>Saída</th><th>Preço saída</th><th>Duração</th><th>P&L</th></tr></thead>
<tbody id="pos-body"></tbody>
</table></div>
</div>

<div class="ft">Painel de apurações — só leitura. Fonte: <span class="mono">data/population.json</span> + <span class="mono">data/logs/trades_*.jsonl</span>. Atualiza a cada 3s.</div>
</div>

<script>
function esc(v){return String(v??'').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;')}
function money(v){return '$'+(Number(v)||0).toFixed(2)}
function fmtDuration(startIso, endIso){
  const start=new Date(startIso).getTime();
  const end=endIso?new Date(endIso).getTime():Date.now();
  let s=Math.max(0,Math.floor((end-start)/1000));
  const d=Math.floor(s/86400); s-=d*86400;
  const h=Math.floor(s/3600); s-=h*3600;
  const m=Math.floor(s/60);
  if(d>0) return d+'d '+h+'h';
  if(h>0) return h+'h '+m+'m';
  return m+'m';
}
function statusBadge(status){
  return status==='alive' ? '<span class="badge bg">vivo</span>' : '<span class="badge br">morto</span>';
}
function fmtTime(iso){
  if(!iso) return '-';
  const dt=new Date(iso);
  return dt.toLocaleDateString()+' '+dt.toLocaleTimeString();
}
function fmtDurationSec(s){
  if(s==null) return '-';
  s=Math.max(0,Math.floor(s));
  const h=Math.floor(s/3600); s-=h*3600;
  const m=Math.floor(s/60); s-=m*60;
  if(h>0) return h+'h '+m+'m';
  if(m>0) return m+'m '+s+'s';
  return s+'s';
}

function renderRiskRoom(rr){
  if(!rr){
    document.getElementById('risk-pop-label').textContent='-';
    document.getElementById('risk-niche-label').textContent='-';
    document.getElementById('risk-pending').textContent='';
    document.getElementById('risk-niche-body').innerHTML='<tr><td colspan="4" class="empty">-</td></tr>';
    document.getElementById('risk-asset-body').innerHTML='<tr><td colspan="3" class="empty">-</td></tr>';
    return;
  }
  const popPct = rr.population_cap ? Math.min(100, rr.population_alive/rr.population_cap*100) : 0;
  document.getElementById('risk-pop-label').textContent = rr.population_alive+' / '+rr.population_cap;
  const popFill = document.getElementById('risk-pop-fill');
  popFill.style.width = popPct+'%';
  popFill.className = 'rc-fill' + (popPct>=100?' full':popPct>=80?' warn':'');

  const nichesTotal = (rr.by_niche||[]).length || 1;
  const nichePct = Math.min(100, rr.niches_at_cap / nichesTotal * 100);
  document.getElementById('risk-niche-label').textContent = rr.niches_at_cap+' de '+(rr.by_niche||[]).length+' nicho(s) ativo(s) (teto '+rr.niche_cap+'/nicho)';
  const nicheFill = document.getElementById('risk-niche-fill');
  nicheFill.style.width = nichePct+'%';
  nicheFill.className = 'rc-fill' + (nichePct>=100?' full':nichePct>=50?' warn':'');

  document.getElementById('risk-pending').textContent = rr.pending_count>0
    ? `⏳ ${rr.pending_count} pedido(s) de clonagem/otimização esperando vaga (teto atingido)` : '';

  const niches = rr.by_niche||[];
  document.getElementById('risk-niche-body').innerHTML = niches.length ? niches.map(n=>`
    <tr>
      <td>${esc(n.strategy_name)}${n.strategy_id && n.strategy_id.includes('~opt')?' <span class="badge bb">otimização</span>':''}</td>
      <td>${esc(n.symbol)}</td>
      <td class="${n.count>=rr.niche_cap?'r':''}">${n.count}/${rr.niche_cap}</td>
      <td>${money(n.capital)}</td>
    </tr>`).join('') : '<tr><td colspan="4" class="empty">Nenhum robô vivo ainda</td></tr>';

  const assets = rr.by_asset||[];
  document.getElementById('risk-asset-body').innerHTML = assets.length ? assets.map(a=>`
    <tr><td>${esc(a.symbol)}</td><td>${a.count}</td><td>${money(a.capital)}</td></tr>`).join('')
    : '<tr><td colspan="3" class="empty">Nenhum robô vivo ainda</td></tr>';
}

let robotMeta = {};       // id -> {symbol, strategy_name, status, capital}
let historyData = [];     // snapshots [{ts, total_capital_alive, robots:[{id,symbol,strategy_name,capital}]}], asc por tempo
let selectedIds = new Set();
const EQ_PALETTE = ['#3b82f6','#22c55e','#ef4444','#8b5cf6','#eab308','#06b6d4','#f97316','#ec4899'];

function colorFor(id){
  let h = 0;
  for(let i=0;i<id.length;i++) h = (h*31 + id.charCodeAt(i)) >>> 0;
  return EQ_PALETTE[h % EQ_PALETTE.length];
}

function updateSelectOptions(selectEl, values){
  const existing = new Set(Array.from(selectEl.options).map(o=>o.value));
  values.forEach(v=>{
    if(v && !existing.has(v)){
      const opt = document.createElement('option');
      opt.value = v; opt.textContent = v;
      selectEl.appendChild(opt);
    }
  });
}

function renderPicker(){
  const fStrategy = document.getElementById('eq-f-strategy').value;
  const fSymbol = document.getElementById('eq-f-symbol').value;
  const fStatus = document.getElementById('eq-f-status').value;
  const ids = Object.keys(robotMeta).filter(id=>{
    const m = robotMeta[id];
    if(fStrategy && m.strategy_name!==fStrategy) return false;
    if(fSymbol && m.symbol!==fSymbol) return false;
    if(fStatus && m.status!==fStatus) return false;
    return true;
  }).sort((a,b)=> (robotMeta[b].capital||0)-(robotMeta[a].capital||0));
  const picker = document.getElementById('eq-picker');
  if(!ids.length){
    picker.innerHTML = '<div class="eq-empty-list">Nenhum robô com esse filtro</div>';
    return;
  }
  picker.innerHTML = ids.map(id=>{
    const m = robotMeta[id];
    const checked = selectedIds.has(id) ? 'checked' : '';
    return `<label><input type="checkbox" class="eq-robot-check" value="${esc(id)}" ${checked}>
      <span class="eq-swatch" style="background:${colorFor(id)}"></span>
      <span>${m.status==='dead'?'💀 ':''}${esc(m.symbol)} · ${esc(m.strategy_name)} <span class="mono">${esc(id.slice(2,8))}</span></span></label>`;
  }).join('');
  picker.querySelectorAll('.eq-robot-check').forEach(cb=>{
    cb.addEventListener('change', ()=>{
      if(cb.checked) selectedIds.add(cb.value); else selectedIds.delete(cb.value);
      renderChart();
    });
  });
}

function buildSeries(){
  const merge = document.getElementById('eq-merge').checked;
  const global = document.getElementById('eq-global').checked;
  const series = [];
  if(global){
    series.push({
      label: 'Global (capital vivo total)', color: '#eab308',
      points: historyData.map(h=>({t: new Date(h.ts).getTime(), v: h.total_capital_alive}))
    });
  }
  const ids = Array.from(selectedIds).filter(id=>robotMeta[id]);
  if(ids.length){
    const maps = historyData.map(h=>{ const m={}; for(const r of h.robots) m[r.id]=r.capital; return m; });
    if(merge){
      const points = historyData.map((h,i)=>{
        let sum = 0, any = false;
        for(const id of ids){ if(maps[i][id]!=null){ sum += maps[i][id]; any = true; } }
        return {t: new Date(h.ts).getTime(), v: any ? sum : null};
      });
      series.push({label: 'Selecionados — soma ('+ids.length+')', color: '#3b82f6', points});
    } else {
      ids.forEach(id=>{
        const m = robotMeta[id] || {};
        const points = historyData.map((h,i)=>({t: new Date(h.ts).getTime(), v: maps[i][id]!=null ? maps[i][id] : null}));
        series.push({label: (m.symbol||'?')+' · '+(m.strategy_name||'?')+' · '+id.slice(2,8), color: colorFor(id), points});
      });
    }
  }
  return series;
}

function renderChart(){
  const svg = document.getElementById('eq-svg');
  const legend = document.getElementById('eq-legend');
  const series = buildSeries().filter(s=>s.points.some(p=>p.v!=null));
  if(!series.length){
    svg.innerHTML = '<text x="450" y="130" fill="#6b7280" font-size="12" text-anchor="middle">Marque um robô, ou "Global", pra ver o gráfico</text>';
    legend.innerHTML = '';
    return;
  }
  const W=900, H=260, ML=54, MR=10, MT=14, MB=22;
  const plotW=W-ML-MR, plotH=H-MT-MB;
  let tmin=Infinity, tmax=-Infinity, vmin=Infinity, vmax=-Infinity;
  for(const s of series) for(const p of s.points){
    if(p.v==null) continue;
    if(p.t<tmin) tmin=p.t;
    if(p.t>tmax) tmax=p.t;
    if(p.v<vmin) vmin=p.v;
    if(p.v>vmax) vmax=p.v;
  }
  if(tmin===tmax){ tmin-=60000; tmax+=60000; }
  if(vmin===vmax){ const pad0=Math.max(1,Math.abs(vmin)*0.1); vmin-=pad0; vmax+=pad0; }
  const pad = (vmax-vmin)*0.08;
  vmin -= pad; vmax += pad;
  const X = t => ML + (t-tmin)/(tmax-tmin) * plotW;
  const Y = v => MT + (1-(v-vmin)/(vmax-vmin)) * plotH;

  let svgHtml = '';
  const GRID_N = 4;
  for(let i=0;i<=GRID_N;i++){
    const v = vmin + (vmax-vmin)*i/GRID_N;
    const y = Y(v);
    svgHtml += `<line x1="${ML}" y1="${y.toFixed(1)}" x2="${W-MR}" y2="${y.toFixed(1)}" stroke="#1e2530" stroke-width="1"/>`;
    svgHtml += `<text x="${ML-6}" y="${(y+3).toFixed(1)}" fill="#6b7280" font-size="9" text-anchor="end">$${v.toFixed(0)}</text>`;
  }
  svgHtml += `<text x="${ML}" y="${H-6}" fill="#6b7280" font-size="9">${esc(new Date(tmin).toLocaleString())}</text>`;
  svgHtml += `<text x="${W-MR}" y="${H-6}" fill="#6b7280" font-size="9" text-anchor="end">${esc(new Date(tmax).toLocaleString())}</text>`;

  for(const s of series){
    let d = '', started = false;
    for(const p of s.points){
      if(p.v==null){ started=false; continue; }
      const x=X(p.t), y=Y(p.v);
      d += (started ? ' L ' : ' M ')+x.toFixed(1)+' '+y.toFixed(1);
      started = true;
    }
    if(d) svgHtml += `<path d="${d}" fill="none" stroke="${s.color}" stroke-width="2"/>`;
  }
  svg.innerHTML = svgHtml;
  legend.innerHTML = series.map(s=>`<span class="li"><span class="eq-swatch" style="background:${s.color}"></span>${esc(s.label)}</span>`).join('');
}

async function tickHistory(){
  try{
    const r = await fetch('/api/history?limit=500');
    const d = await r.json();
    historyData = d.history || [];
    document.getElementById('eq-count').textContent = historyData.length+' pontos';
    renderChart();
  }catch(e){
    // silencioso — mesmo padrão do resto do painel
  }
}

async function tickPositions(){
  try{
    const r=await fetch('/api/positions?limit=60');
    const d=await r.json();
    const positions=d.positions||[];
    document.getElementById('pos-count').textContent = positions.length+' recentes';
    document.getElementById('pos-body').innerHTML = positions.length ? positions.map(p=>`
      <tr>
        <td class="mono">${esc(p.robot)}</td>
        <td>${esc(p.symbol)}</td>
        <td><span class="badge ${p.side==='buy'?'bg':'br'}">${esc((p.side||'').toUpperCase())}</span></td>
        <td>${fmtTime(p.entry_time)}</td>
        <td>$${(p.entry_price||0).toFixed(4)}</td>
        <td>${fmtTime(p.exit_time)}</td>
        <td>$${(p.exit_price||0).toFixed(4)}</td>
        <td>${fmtDurationSec(p.duration_seconds)}</td>
        <td class="${p.pnl>=0?'g':'r'}">${p.pnl>=0?'+':''}$${(p.pnl||0).toFixed(2)} (${p.pnl_pct>=0?'+':''}${(p.pnl_pct||0).toFixed(2)}%)</td>
      </tr>`).join('') : '<tr><td colspan="9" class="empty">Nenhuma posição fechada ainda</td></tr>';
  }catch(e){
    // silencioso — a tabela de população já mostra o status de conexão
  }
}

async function tick(){
  try{
    const r=await fetch('/api/state');
    const d=await r.json();
    document.getElementById('dot').className='dot dot-g';
    document.getElementById('updated').textContent = d.updated_at ? new Date(d.updated_at).toLocaleTimeString() : 'sem dados ainda';
    if(d._empty){
      document.getElementById('pop-body').innerHTML='<tr><td colspan="14" class="empty">Nenhum estado de população encontrado ainda — inicie o Organism (main.py ou simulate.py).</td></tr>';
      document.getElementById('lb-body').innerHTML='<tr><td colspan="8" class="empty">-</td></tr>';
      document.getElementById('ops-grid').innerHTML='<div class="empty">-</div>';
      document.getElementById('eq-picker').innerHTML='<div class="eq-empty-list">-</div>';
      renderRiskRoom(null);
      return;
    }

    document.getElementById('st-alive').textContent = d.population_alive ?? 0;
    document.getElementById('st-total').textContent = d.population_total ?? 0;
    document.getElementById('st-capital').textContent = money(d.total_capital_alive);
    document.getElementById('st-lb').textContent = d.leaderboard_size ?? 0;
    document.getElementById('lb-cap').textContent = (d.leaderboard_size ?? 0)+' / '+(d.leaderboard_capacity ?? 500);
    document.getElementById('pop-count').textContent = (d.population_alive ?? 0)+' vivos / '+(d.population_total ?? 0)+' total';

    const lb = (d.leaderboard_top||[]).slice().sort((a,b)=>b.score-a.score);
    document.getElementById('lb-body').innerHTML = lb.length ? lb.map(e=>`
      <tr>
        <td class="${e.score>1?'g':e.score<1?'r':''}">${e.score.toFixed(2)}</td>
        <td>${esc(e.name)}</td>
        <td><span class="badge bb">${esc(e.implementation)}</span></td>
        <td>${esc(e.timeframe)}</td>
        <td class="g">${e.clones}</td>
        <td class="r">${e.deaths}</td>
        <td>${e.attempts}</td>
        <td class="mono" style="max-width:260px;overflow:hidden;text-overflow:ellipsis">${esc(e.source)}</td>
      </tr>`).join('') : '<tr><td colspan="8" class="empty">Nenhuma estratégia no ranking ainda</td></tr>';

    const robots = (d.robots||[]).slice().sort((a,b)=> new Date(b.born_at) - new Date(a.born_at));
    document.getElementById('pop-body').innerHTML = robots.length ? robots.map(rb=>`
      <tr>
        <td class="mono">${esc(rb.id)}</td>
        <td class="mono">${esc(rb.parent_id||'—')}</td>
        <td>${esc(rb.symbol)}</td>
        <td>${esc(rb.strategy_name)}</td>
        <td>${esc(rb.timeframe)}</td>
        <td>${statusBadge(rb.status)}</td>
        <td>${money(rb.capital)}</td>
        <td>${money(rb.peak_capital)}</td>
        <td class="${rb.drawdown_pct>30?'r':rb.drawdown_pct>10?'y':''}">${(rb.drawdown_pct||0).toFixed(1)}%</td>
        <td>${rb.total_trades||0}</td>
        <td class="${(rb.win_rate||0)>0.5?'g':''}">${((rb.win_rate||0)*100).toFixed(0)}%</td>
        <td class="${rb.clones_generated>0?'g':''}">${rb.clones_generated||0}</td>
        <td>${fmtDuration(rb.born_at, rb.died_at)}</td>
        <td class="death">${rb.status==='dead' ? esc(rb.cause_of_death||'-') : ''}</td>
      </tr>`).join('') : '<tr><td colspan="14" class="empty">Nenhum robô nasceu ainda</td></tr>';

    renderRiskRoom(d.risk_room);

    robotMeta = {};
    for(const rb of robots){
      robotMeta[rb.id] = {symbol: rb.symbol, strategy_name: rb.strategy_name, status: rb.status, capital: rb.capital};
    }
    updateSelectOptions(document.getElementById('eq-f-strategy'), robots.map(r=>r.strategy_name));
    updateSelectOptions(document.getElementById('eq-f-symbol'), robots.map(r=>r.symbol));
    renderPicker();
    renderChart();

    const trByKey = {};
    for(const t of (d.track_records||[])) trByKey[t.strategy_name+'|'+t.symbol] = t;
    const liveFirst = robots.slice().sort((a,b)=>{
      if(a.status!==b.status) return a.status==='alive'?-1:1;
      return new Date(b.born_at)-new Date(a.born_at);
    });
    const MAX_CARDS = 40;
    const shown = liveFirst.slice(0, MAX_CARDS);
    document.getElementById('ops-count').textContent = robots.length+(robots.length>MAX_CARDS?(' (mostrando '+MAX_CARDS+')'):'');
    document.getElementById('ops-grid').innerHTML = shown.length ? shown.map(rb=>{
      const t = trByKey[rb.strategy_name+'|'+rb.symbol];
      const chips = (rb.strategy_indicators||[]).map(i=>`<span class="chip">${esc(i)}</span>`).join('');
      const trackHtml = t ? `
        <div class="trackbox">
          <div class="tr-title">Histórico do Estrategista — ${esc(rb.strategy_name)} em ${esc(rb.symbol)}</div>
          ${t.attempts} tentativa(s) · <span class="g">${t.clones} clone(s)</span> · <span class="r">${t.deaths} morte(s)</span>
          · mortalidade <span class="${t.death_rate>=0.5?'r':''}">${(t.death_rate*100).toFixed(0)}%</span>
        </div>` : '';
      return `
      <div class="robot-card">
        <div class="rc-hdr"><span class="rc-id">${esc(rb.id)}</span>${statusBadge(rb.status)}</div>
        <div class="rc-title">${esc(rb.symbol)} · ${esc(rb.strategy_name)} · ${esc(rb.timeframe)}</div>
        <div class="rc-sub">${money(rb.capital)} (pico ${money(rb.peak_capital)}) · ${rb.total_trades||0} trades · ${rb.clones_generated||0} clones</div>
        ${chips ? `<div style="margin-bottom:6px">${chips}</div>` : ''}
        <div class="rc-row"><b>Entrada:</b> ${esc(rb.strategy_entry_rule || '—')}</div>
        <div class="rc-row"><b>Saída:</b> ${esc(rb.strategy_exit_rule || '—')}</div>
        <div class="rc-row"><b>Risco:</b> ${esc(rb.strategy_risk_management || '—')}</div>
        ${trackHtml}
      </div>`;
    }).join('') + (robots.length>MAX_CARDS ? `<div class="more-note">+ ${robots.length-MAX_CARDS} robô(s) a mais — veja a tabela População acima</div>` : '')
      : '<div class="empty">Nenhum robô nasceu ainda</div>';
  }catch(e){
    document.getElementById('dot').className='dot dot-r';
  }
}
document.getElementById('eq-f-strategy').addEventListener('change', renderPicker);
document.getElementById('eq-f-symbol').addEventListener('change', renderPicker);
document.getElementById('eq-f-status').addEventListener('change', renderPicker);
document.getElementById('eq-global').addEventListener('change', renderChart);
document.getElementById('eq-merge').addEventListener('change', renderChart);

tick(); setInterval(tick, 3000);
tickPositions(); setInterval(tickPositions, 3000);
tickHistory(); setInterval(tickHistory, 5000);
</script>
</body>
</html>"""


def create_app():
    if web is None:
        raise ImportError("pip install aiohttp")
    app = web.Application()
    app.router.add_get("/", handle_index)
    app.router.add_get("/api/state", handle_state)
    app.router.add_get("/api/positions", handle_positions)
    app.router.add_get("/api/history", handle_history)
    return app


async def start_dashboard(port=8080, state_file: str = DEFAULT_STATE_FILE):
    """Inicia o painel como task de longa duração (roda até ser cancelada)."""
    set_state_file(state_file)
    app = create_app()
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    print(f"  📊 Painel de apurações em http://0.0.0.0:{port}")
    try:
        import asyncio
        while True:
            await asyncio.sleep(3600)
    except Exception:
        pass
    finally:
        await runner.cleanup()


async def run_standalone(port=8080, state_file: str = DEFAULT_STATE_FILE):
    await start_dashboard(port, state_file)
