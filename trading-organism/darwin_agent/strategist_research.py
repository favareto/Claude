"""Estrategista — pesquisa em fonte aberta antes de decidir. Roda como
script SEPARADO (mesmo padrão de `investigator_research.py`): observa
`data/strategy_feed/` (onde o Investigador grava propostas novas), e para
cada proposta ainda não revisada, chama a API da Anthropic com busca web
habilitada pra:
1. Verificar/atualizar a fonte citada pelo Investigador (ela ainda é
   válida? o contexto de mercado mudou desde então?).
2. Decidir: aprovar como está, recusar (com motivo), ou sugerir mudanças
   nos parâmetros da estratégia.

O resultado vira um `StrategyReview`, gravado em
`data/strategy_reviews/<mesmo nome do arquivo da proposta>.json`.
`Organism.poll_strategy_feed` lê esse arquivo (se existir) antes de deixar
a proposta nascer — ver `strategist.py: Strategist.apply_review`.

A pesquisa é OPCIONAL/assíncrona: se a revisão ainda não rodou quando a
proposta chega no Organism, ele segue sem bloquear (a proposta passa pelos
outros critérios do Estrategista normalmente) — revisões atrasadas ainda
valem pra decisões futuras sobre a mesma combinação.

Uso:
    export ANTHROPIC_API_KEY=sk-ant-...
    python -m darwin_agent.strategist_research            # revisa o que estiver pendente
    python -m darwin_agent.strategist_research --loop      # roda pra sempre (cron embutido)
"""

import argparse
import json
import os
import time
from dataclasses import asdict

from darwin_agent.investigator import StrategyProposal
from darwin_agent.strategist import StrategyReview

FEED_DIR = "data/strategy_feed"
REVIEWS_DIR = "data/strategy_reviews"
MODEL = "claude-sonnet-5"

REVIEW_PROMPT_TEMPLATE = """Você é o Estrategista de um sistema de trading autônomo — o gatekeeper \
que decide se uma estratégia proposta pelo Investigador merece nascer como um robô de verdade.

Proposta trazida pelo Investigador:
{proposal_json}

Pesquise na web pra verificar essa proposta: a fonte citada ainda é \
confiável/atual? O contexto de mercado mudou desde que essa fonte foi \
publicada? Existe pesquisa mais recente que sugira parâmetros melhores \
pra essa mesma família de estratégia?

Responda APENAS com um JSON válido, sem texto antes ou depois:

{{
  "verdict": "approve" | "reject" | "revise",
  "reason": "por que aprovou/recusou/revisou, citando o que a pesquisa mostrou",
  "suggested_params": {{"chave": valor, ...}} ou null,
  "source_check": "o que a pesquisa confirmou ou contestou sobre a fonte original"
}}

Use "reject" só se a pesquisa mostrar evidência real contra a estratégia \
(fonte desacreditada, contexto de mercado mudou fundamentalmente). Use \
"revise" quando a pesquisa sugerir parâmetros mais adequados sem invalidar \
a estratégia em si — nesse caso preencha "suggested_params" com as chaves \
que a proposta já usa (ex: ema_fast, ema_slow, rsi_period, atr_stop_mult, \
atr_tp_mult, bb_period, bb_std, lookback — conforme a implementação)."""


def _client():
    import anthropic
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY não configurada no ambiente")
    return anthropic.Anthropic(api_key=api_key)


def parse_review(text: str) -> StrategyReview:
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError(f"Resposta sem JSON reconhecível: {text[:200]!r}")
    data = json.loads(text[start:end + 1])

    verdict = data.get("verdict", "")
    if verdict not in ("approve", "reject", "revise"):
        raise ValueError(f"verdict inválido: {verdict!r} — precisa ser approve/reject/revise")

    return StrategyReview(
        verdict=verdict,
        reason=data.get("reason", ""),
        suggested_params=data.get("suggested_params") or None,
        source_check=data.get("source_check", ""),
    )


def review_one(proposal: StrategyProposal) -> StrategyReview:
    """Uma chamada à API da Anthropic com busca web habilitada -> 1
    review estruturado. Requer ANTHROPIC_API_KEY no ambiente."""
    client = _client()
    prompt = REVIEW_PROMPT_TEMPLATE.format(
        proposal_json=json.dumps(asdict(proposal), indent=2, ensure_ascii=False))
    response = client.messages.create(
        model=MODEL,
        max_tokens=2000,
        tools=[{"type": "web_search_20250305", "name": "web_search"}],
        messages=[{"role": "user", "content": prompt}],
    )
    text = "".join(block.text for block in response.content if getattr(block, "type", None) == "text")
    return parse_review(text)


def save_review(review: StrategyReview, feed_filename: str, reviews_dir: str = REVIEWS_DIR) -> str:
    """Grava com o MESMO nome de arquivo da proposta em feed_dir — é assim
    que Organism.poll_strategy_feed casa review com proposta."""
    os.makedirs(reviews_dir, exist_ok=True)
    path = os.path.join(reviews_dir, feed_filename)
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(asdict(review), f, indent=2, ensure_ascii=False)
    os.replace(tmp, path)
    return path


def run_once(feed_dir: str = FEED_DIR, reviews_dir: str = REVIEWS_DIR) -> int:
    """Revisa toda proposta em `feed_dir` que ainda não tem review em
    `reviews_dir`. Retorna quantas revisou."""
    if not os.path.isdir(feed_dir):
        return 0
    count = 0
    for fname in sorted(os.listdir(feed_dir)):
        if not fname.endswith(".json"):
            continue
        review_path = os.path.join(reviews_dir, fname)
        if os.path.exists(review_path):
            continue
        with open(os.path.join(feed_dir, fname)) as f:
            data = json.load(f)
        try:
            proposal = StrategyProposal(**data)
        except Exception as e:
            print(f"Proposta '{fname}' malformada, pulando: {e}")
            continue
        try:
            review = review_one(proposal)
        except Exception as e:
            print(f"Revisão de '{proposal.name}' falhou: {e}")
            continue
        save_review(review, fname, reviews_dir)
        print(f"Revisou '{proposal.name}': {review.verdict} — {review.reason[:100]}")
        count += 1
    return count


def main():
    parser = argparse.ArgumentParser(description="Estrategista — pesquisa em fonte aberta")
    parser.add_argument("--loop", action="store_true",
                        help="roda pra sempre, revisando pendências a cada --interval segundos")
    parser.add_argument("--interval", type=int, default=300,
                        help="segundos entre rodadas no modo --loop (padrão: 300 = 5min)")
    parser.add_argument("--feed-dir", default=FEED_DIR)
    parser.add_argument("--reviews-dir", default=REVIEWS_DIR)
    args = parser.parse_args()

    if not args.loop:
        n = run_once(args.feed_dir, args.reviews_dir)
        print(f"{n} proposta(s) revisada(s).")
        return

    while True:
        run_once(args.feed_dir, args.reviews_dir)
        time.sleep(args.interval)


if __name__ == "__main__":
    main()
