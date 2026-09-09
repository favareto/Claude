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


async def handle_state(req):
    if not os.path.exists(_state_file):
        return web.json_response({
            "updated_at": None, "population_alive": 0, "population_total": 0,
            "total_capital_alive": 0, "robots": [], "leaderboard_size": 0,
            "leaderboard_capacity": 0, "leaderboard_top": [],
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

<div class="ft">Painel de apurações — só leitura. Fonte: <span class="mono">data/population.json</span>. Atualiza a cada 3s.</div>
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

async function tick(){
  try{
    const r=await fetch('/api/state');
    const d=await r.json();
    document.getElementById('dot').className='dot dot-g';
    document.getElementById('updated').textContent = d.updated_at ? new Date(d.updated_at).toLocaleTimeString() : 'sem dados ainda';
    if(d._empty){
      document.getElementById('pop-body').innerHTML='<tr><td colspan="14" class="empty">Nenhum estado de população encontrado ainda — inicie o Organism (main.py ou simulate.py).</td></tr>';
      document.getElementById('lb-body').innerHTML='<tr><td colspan="8" class="empty">-</td></tr>';
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
  }catch(e){
    document.getElementById('dot').className='dot dot-r';
  }
}
tick(); setInterval(tick, 3000);
</script>
</body>
</html>"""


def create_app():
    if web is None:
        raise ImportError("pip install aiohttp")
    app = web.Application()
    app.router.add_get("/", handle_index)
    app.router.add_get("/api/state", handle_state)
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
