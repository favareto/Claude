"""Investigador — pesquisa CONTÍNUA de verdade. Roda como script SEPARADO
(cron a cada ~30min, ou GitHub Actions agendado) — não depende de sessão
interativa do Claude Code (ver CLAUDE.md). Chama a API da Anthropic com a
ferramenta de busca web habilitada, pede uma estratégia de trading
atualmente relevante, estrutura a resposta em `StrategyProposal` e grava
em `data/strategy_feed/` como um arquivo JSON.

O processo principal (organism.py: `Organism.poll_strategy_feed`) observa
esse diretório e injeta cada proposta nova na população — é assim que os
dois processos ficam desacoplados: pesquisa é lenta e externa, o loop de
trading roda o tempo todo.

Uso:
    export ANTHROPIC_API_KEY=sk-ant-...
    python -m darwin_agent.investigator_research            # uma rodada
    python -m darwin_agent.investigator_research --loop      # roda pra sempre (cron embutido)
    python -m darwin_agent.investigator_research --loop --interval 1800
"""

import argparse
import json
import os
import time
import uuid
from dataclasses import asdict
from typing import Optional

from darwin_agent.investigator import StrategyProposal
from darwin_agent.strategies.base import STRATEGY_REGISTRY

FEED_DIR = "data/strategy_feed"
MODEL = "claude-sonnet-5"

RESEARCH_PROMPT = """Pesquise na web UMA estratégia de trading (crypto ou mercados em geral) \
que esteja com resultados bons e atuais — GitHub, arXiv q-fin.TR, listas como \
awesome-systematic-trading, repositórios do Freqtrade, ou artigos de backtest \
confiáveis com números concretos (win rate, profit factor, drawdown).

Responda APENAS com um JSON válido, sem nenhum texto antes ou depois, com \
exatamente estes campos:

{
  "name": "nome curto e descritivo da estratégia",
  "indicators": ["indicador 1", "indicador 2"],
  "entry_rule": "regra de entrada em texto claro",
  "exit_rule": "regra de saída em texto claro",
  "risk_management": "como a estratégia gerencia risco",
  "source": "URL ou citação da fonte, com algum número de performance se houver",
  "implementation": "momentum | mean_reversion | scalping | breakout",
  "timeframe": "1m | 5m | 15m | 1h | 4h | 1d | 1w",
  "asset_hint": "SYMBOLUSDT ou null se não houver preferência"
}

"implementation" TEM que ser exatamente uma destas 4 (as únicas já \
codificadas no sistema): momentum, mean_reversion, scalping, breakout — \
escolha a que mais se parece com a lógica real da estratégia encontrada, \
mesmo que o nome dela na fonte seja diferente."""


def _client():
    import anthropic
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY não configurada no ambiente")
    return anthropic.Anthropic(api_key=api_key)


def parse_proposal(text: str) -> StrategyProposal:
    """Extrai o JSON da resposta do modelo (tolera texto ao redor, já que
    LLMs às vezes adicionam preâmbulo mesmo quando instruídos a não fazer)
    e monta a StrategyProposal. Levanta ValueError se o JSON for inválido
    ou faltar campo obrigatório — quem chama decide o que fazer (descartar
    a rodada, tentar de novo na próxima)."""
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError(f"Resposta sem JSON reconhecível: {text[:200]!r}")
    data = json.loads(text[start:end + 1])

    implementation = data.get("implementation", "")
    if implementation not in STRATEGY_REGISTRY:
        raise ValueError(
            f"implementation inválida: {implementation!r} — precisa ser uma de {list(STRATEGY_REGISTRY)}")

    for field in ("name", "entry_rule", "exit_rule", "risk_management", "source"):
        if not data.get(field):
            raise ValueError(f"Campo obrigatório ausente/vazio na resposta: {field!r}")

    return StrategyProposal(
        name=data["name"],
        indicators=list(data.get("indicators", [])),
        entry_rule=data["entry_rule"],
        exit_rule=data["exit_rule"],
        risk_management=data["risk_management"],
        source=data["source"],
        implementation=implementation,
        timeframe=data.get("timeframe") or "15m",
        asset_hint=data.get("asset_hint") or None,
    )


def research_one() -> StrategyProposal:
    """Uma chamada à API da Anthropic com busca web habilitada -> 1
    proposta estruturada. Requer ANTHROPIC_API_KEY no ambiente."""
    client = _client()
    response = client.messages.create(
        model=MODEL,
        max_tokens=2000,
        tools=[{"type": "web_search_20250305", "name": "web_search"}],
        messages=[{"role": "user", "content": RESEARCH_PROMPT}],
    )
    text = "".join(block.text for block in response.content if getattr(block, "type", None) == "text")
    return parse_proposal(text)


def save_proposal(proposal: StrategyProposal, feed_dir: str = FEED_DIR) -> str:
    """Grava a proposta como JSON em `feed_dir`, atomicamente (write+rename)
    pra Organism.poll_strategy_feed nunca ler um arquivo pela metade."""
    os.makedirs(feed_dir, exist_ok=True)
    fname = f"{int(time.time())}_{uuid.uuid4().hex[:8]}.json"
    path = os.path.join(feed_dir, fname)
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(asdict(proposal), f, indent=2, ensure_ascii=False)
    os.replace(tmp, path)
    return path


def run_once(feed_dir: str = FEED_DIR) -> Optional[str]:
    try:
        proposal = research_one()
    except Exception as e:
        print(f"Rodada de pesquisa falhou: {e}")
        return None
    path = save_proposal(proposal, feed_dir)
    print(f"Pesquisou: {proposal.name} ({proposal.implementation}/{proposal.timeframe}) -> {path}")
    return path


def main():
    parser = argparse.ArgumentParser(description="Investigador — pesquisa contínua de estratégias")
    parser.add_argument("--loop", action="store_true",
                        help="roda pra sempre, uma rodada a cada --interval segundos "
                             "(alternativa a agendar via cron/GitHub Actions)")
    parser.add_argument("--interval", type=int, default=1800,
                        help="segundos entre rodadas no modo --loop (padrão: 1800 = 30min)")
    parser.add_argument("--feed-dir", default=FEED_DIR)
    args = parser.parse_args()

    if not args.loop:
        run_once(args.feed_dir)
        return

    while True:
        run_once(args.feed_dir)
        time.sleep(args.interval)


if __name__ == "__main__":
    main()
