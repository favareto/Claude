"""Darwin Agent — Entry Point. Run with: python -m darwin_agent [--mode test|live]

Nesta fase o organismo é uma POPULAÇÃO (ver CLAUDE.md e organism.py), não
mais uma linhagem única geracional. Este CLI conecta em uma exchange real
(testnet por padrão) via organism.Organism; para validar o ciclo de vida
sem exchange nenhuma, use `python -m darwin_agent.simulate`.
"""

import asyncio
import argparse
import os
import signal
import sys

from darwin_agent.investigator import bootstrap_feed
from darwin_agent.organism import Organism
from darwin_agent.utils.config import load_config, AgentConfig

BANNER = """
╔═══════════════════════════════════════════════════╗
║  🧬  D A R W I N   A G E N T   v2.3  🧬         ║
║  Organismo de robôs autônomos de trade             ║
║  "Nasce, opera, clona, morre."                     ║
╚═══════════════════════════════════════════════════╝
"""


async def run_forever(config: AgentConfig, symbols: list, roots: int):
    print(BANNER)
    print(f"  Capital por robô: ${config.starting_capital} | Clona em: +{(config.clone_multiplier - 1) * 100:.0f}% | "
          f"Morre em: -{config.health.death_drawdown_pct:.0f}% do pico")
    print(f"  Markets: {', '.join(k for k, v in config.markets.items() if v.enabled)}")
    print(f"  Universo de ativos: {len(symbols)} símbolos")
    print("=" * 55)

    # ── Pre-flight: Run diagnostics before starting ──
    for name, mc in config.markets.items():
        if mc.enabled:
            env = "TESTNET" if mc.testnet else "⚠️ MAINNET"
            print(f"\n  🔍 Running pre-flight diagnostics for {name} ({env})...")

            from darwin_agent.markets.bybit_errors import run_diagnostics
            diag = await run_diagnostics(mc.api_key, mc.api_secret, mc.testnet)

            if not diag.is_ready:
                print(diag.render())
                if not mc.testnet:
                    print("\n  ❌ REFUSING to start MAINNET with failing diagnostics.")
                    print("  Fix the issues above or switch to testnet.")
                    return
                else:
                    print("\n  ⚠️  Testnet diagnostics failed. Attempting anyway...")
            else:
                print(f"  ✅ All {diag.passed_count} checks passed!")

    # heartbeat_by_timeframe=True: cada robô consulta o mercado num ritmo
    # coerente com seu timeframe (1m escaneia a cada 30s; 1w a cada 6h) —
    # não faz sentido um robô semanal ficar batendo na API toda hora.
    organism = Organism(base_config=config, symbols=symbols, heartbeat_by_timeframe=True)

    # Bootstrap dev: fila de estratégias já pesquisadas (ver investigator.py).
    # Em produção o Investigador roda continuamente (~30min) alimentando
    # essa mesma fila via ingest() — aqui é só o ponto de partida.
    investigador = bootstrap_feed()
    proposals = investigador.all_ingested()
    for i in range(roots):
        proposal = proposals[i % len(proposals)]
        symbol = symbols[i % len(symbols)]
        robot_id, reason = await organism.propose_and_spawn(proposal, symbol=symbol)
        if robot_id:
            print(f"  🐣 {robot_id} nasceu especialista em {proposal.implementation}/{proposal.timeframe}/{symbol} com ${config.starting_capital}")
        else:
            print(f"  ⛔ Estrategista recusou '{proposal.name}' em {symbol}: {reason}")

    # Absorve pesquisas novas de investigator_research.py (script separado,
    # cron/GitHub Actions) automaticamente, sem precisar reiniciar o processo.
    feed_task = asyncio.create_task(organism.poll_strategy_feed())

    print(f"\n  População rodando (paper trading). Estado em: {organism.state_file}")
    print(f"  Investigador contínuo: rode `python -m darwin_agent.investigator_research --loop` "
          f"em paralelo (grava em data/strategy_feed/, absorvido automaticamente).")
    print(f"  Estrategista (pesquisa em fonte aberta): rode `python -m darwin_agent.strategist_research --loop` "
          f"em paralelo (grava em data/strategy_reviews/, pode aprovar/recusar/sugerir mudança de parâmetros).")
    print("  Aposta por operação fica ancorada no capital inicial de cada robô — não cresce "
          "com o saldo acumulado. Não há teto de multiplicação — estratégias boas se multiplicam "
          "sem limite; as ruins são eliminadas (ver CLAUDE.md).")
    print("  Ctrl+C para parar.\n")

    try:
        await organism.run_until(lambda org: not org.agents, check_interval=2.0)
    except (asyncio.CancelledError, KeyboardInterrupt):
        pass
    finally:
        feed_task.cancel()
        await organism.shutdown()
    print("\n🏁 População extinta ou encerrada.")


def show_status(config, state_file: str = "data/population.json"):
    """Lê o estado do Macro-organismo (ver organism.py) — não tem lógica própria."""
    import json
    import os

    if not os.path.exists(state_file):
        print(f"Nenhum estado de população encontrado em {state_file}.")
        return

    with open(state_file) as f:
        data = json.load(f)

    print(f"\n📊 População — atualizado em {data.get('updated_at', '?')}\n")
    print(f"  Vivos: {data.get('population_alive', 0)} | Total já existiu: {data.get('population_total', 0)} | "
          f"Capital vivo: ${data.get('total_capital_alive', 0):.2f}\n")
    print(f"{'id':<11} {'pai':<11} {'ativo':<9} {'estratégia':<20} {'tf':<4} {'status':<6} {'capital':>9} {'clones':>7}")
    print("-" * 80)
    for r in data.get("robots", []):
        print(f"{r['id']:<11} {(r.get('parent_id') or '-'):<11} {r['symbol']:<9} "
              f"{r.get('strategy_name', '-'):<20} {r.get('timeframe', '-'):<4} {r['status']:<6} "
              f"${r['capital']:>7.2f} {r.get('clones_generated', 0):>7}")
        if r["status"] == "dead":
            print(f"             -> {r.get('cause_of_death')}")

    top = data.get("leaderboard_top", [])
    if top:
        print(f"\n📈 Ranking de estratégias ({data.get('leaderboard_size', 0)}/{data.get('leaderboard_capacity', 500)}) — top {len(top)}\n")
        for e in top:
            print(f"  score={e['score']:>5.2f} | {e['name']:<35} | {e['clones']} clones / {e['deaths']} mortes / {e['attempts']} tentativas")


async def run_diagnose(config):
    """Run full connection diagnostics."""
    from darwin_agent.markets.bybit_errors import run_diagnostics
    for name, mc in config.markets.items():
        if not mc.enabled:
            continue
        env = "TESTNET" if mc.testnet else "MAINNET"
        print(f"\n🔍 Running diagnostics: {name} ({env})\n")
        report = await run_diagnostics(mc.api_key, mc.api_secret, mc.testnet)
        print(report.render())


async def run_migrate(config):
    """Run migration readiness check."""
    from darwin_agent.markets.bybit_errors import check_migration_readiness

    crypto = config.markets.get("crypto")
    if not crypto:
        print("No crypto market configured.")
        return

    # For migration, we need both testnet and mainnet keys
    # Testnet keys are current, mainnet keys we ask for
    print("\n🔄 TESTNET → MAINNET MIGRATION CHECK\n")

    if crypto.testnet:
        print("Current mode: TESTNET")
        print("To check mainnet readiness, provide mainnet keys in config.yaml")
        print("(Set a second market entry or use environment variables)\n")

        # Check with current keys (testnet)
        mainnet_key = os.environ.get("BYBIT_MAINNET_KEY", "")
        mainnet_secret = os.environ.get("BYBIT_MAINNET_SECRET", "")

        if not mainnet_key:
            print("Set environment variables for mainnet check:")
            print("  export BYBIT_MAINNET_KEY='your-mainnet-key'")
            print("  export BYBIT_MAINNET_SECRET='your-mainnet-secret'")
            print("Then run: python -m darwin_agent --migrate\n")

            # Still run evolution checks
            mainnet_key = "PLACEHOLDER"
            mainnet_secret = "PLACEHOLDER"

        report = await check_migration_readiness(
            testnet_key=crypto.api_key,
            testnet_secret=crypto.api_secret,
            mainnet_key=mainnet_key,
            mainnet_secret=mainnet_secret,
            dna_path="data/generations",
        )
        print(report.render())
    else:
        print("Already on MAINNET. No migration needed.")


def main():
    parser = argparse.ArgumentParser(description="Darwin Agent v2.3 — Organismo")
    parser.add_argument("--symbols", default=None,
                        help="Ativos específicos, separados por vírgula (ignora --universe se dado)")
    parser.add_argument("--universe", type=int, default=None,
                        help="Busca até N ativos reais negociáveis na Bybit (spot+linear USDT), "
                             "ex: --universe 1000. Cai num fallback curado se a rede falhar.")
    parser.add_argument("--roots", type=int, default=1,
                        help="Quantos robôs raiz nascem no início (um por proposta/ativo, ciclando)")
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--status", action="store_true",
                        help="Mostra o estado atual da população")
    parser.add_argument("--diagnose", action="store_true",
                        help="Run Bybit connection diagnostics")
    parser.add_argument("--migrate", action="store_true",
                        help="Check testnet → mainnet migration readiness")
    args = parser.parse_args()

    try:
        config = load_config(args.config)
    except ValueError as e:
        print(f"\n❌ Configuration error: {e}")
        print("   Fix config file and try again.")
        sys.exit(1)

    if args.status:
        show_status(config)
        return

    if args.diagnose:
        asyncio.run(run_diagnose(config))
        return

    if args.migrate:
        asyncio.run(run_migrate(config))
        return

    # Validate config before running
    try:
        config.validate()
    except ValueError as e:
        print(f"\n❌ Configuration error: {e}")
        print("   Edit config.yaml and try again.")
        sys.exit(1)

    # Warn if no API keys
    for name, mc in config.markets.items():
        if mc.enabled and (not mc.api_key or mc.api_key.startswith("YOUR")):
            print(f"\n⚠️  Warning: Market '{name}' enabled but API key not set.")
            print(f"   Edit config.yaml with valid Bybit API keys.")
            if not mc.testnet:
                print("   REFUSING to start in MAINNET mode without valid keys.")
                sys.exit(1)

    # Nesta fase é sempre paper trading (ver CLAUDE.md) — mainnet só fornece
    # preços reais, nunca executa ordens reais.
    for name, mc in config.markets.items():
        if mc.enabled and not mc.testnet:
            print(f"\n⚠️  Market '{name}' está em MAINNET — só será usado como fonte de "
                  f"preços; a execução continua sempre em paper trading.")

    if args.symbols:
        symbols = [s.strip() for s in args.symbols.split(",") if s.strip()]
    elif args.universe:
        from darwin_agent.markets.symbol_universe import fetch_symbol_universe
        print(f"\n  🌐 Buscando até {args.universe} ativos negociáveis na Bybit...")
        symbols = asyncio.run(fetch_symbol_universe(target_size=args.universe))
        print(f"  📋 Universo: {len(symbols)} ativos")
    else:
        symbols = ["BTCUSDT"]

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    _shutdown_triggered = False

    def shutdown(sig, frame):
        nonlocal _shutdown_triggered
        if _shutdown_triggered:
            return
        _shutdown_triggered = True
        print(f"\n⚡ Signal {sig} received. Shutting down gracefully...")
        for task in asyncio.all_tasks(loop):
            task.cancel()

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    try:
        loop.run_until_complete(run_forever(config, symbols, args.roots))
    except (asyncio.CancelledError, KeyboardInterrupt):
        print("\n👋 Shutdown complete.")
    finally:
        pending = asyncio.all_tasks(loop)
        for task in pending:
            task.cancel()
        if pending:
            loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
        loop.close()


if __name__ == "__main__":
    main()
