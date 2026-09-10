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
from typing import Optional

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


async def run_forever(config: AgentConfig, symbols: list, roots: int, asset_classes: Optional[dict] = None):
    print(BANNER)
    print(f"  Capital por robô: ${config.starting_capital} | Clona em: +{(config.clone_multiplier - 1) * 100:.0f}% | "
          f"Morre em: -{config.health.death_drawdown_pct:.0f}% do pico")
    print(f"  Markets: {', '.join(k for k, v in config.markets.items() if v.enabled)}")
    print(f"  Universo de ativos: {len(symbols)} símbolos")
    print("=" * 55)

    # ── Pre-flight: Run diagnostics before starting ──
    # "stocks" (Yahoo Finance) não passa por aqui: o diagnóstico é
    # específico da Bybit (assinatura HMAC, endpoints da API) e não faz
    # sentido rodar contra um mercado sem chave/autenticação nenhuma.
    for name, mc in config.markets.items():
        if mc.enabled and name != "stocks":
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
    # asset_classes (symbol -> "crypto"/"stocks") deixa o universo misturar
    # classes de ativo diferentes — cada robô só liga no adapter certo pro
    # SEU símbolo (ver Organism._new_config).
    organism = Organism(base_config=config, symbols=symbols, heartbeat_by_timeframe=True,
                        asset_classes=asset_classes)

    # Painel de apurações — só leitura, lê data/population.json (ver
    # dashboard.py). Sobe junto, sempre, é seguro (não decide nada).
    from darwin_agent.dashboard import start_dashboard
    dashboard_task = asyncio.create_task(start_dashboard(config.dashboard_port, organism.state_file, organism=organism))

    # Retomada: se o processo já rodou antes e foi desligado (Ctrl+C,
    # reinício do computador), os robôs vivos voltam de onde pararam
    # (capital, cérebro aprendido) em vez de nascer tudo de novo — ver
    # Organism.resume_from_state / CLAUDE.md.
    resumed = await organism.resume_from_state()
    if resumed and organism.agents:
        print(f"\n  ♻️  Retomado: {len(organism.agents)} robô(s) vivo(s) continuando de onde pararam "
              f"({organism.full_state_file}).")
    else:
        if resumed:
            print("\n  ⚠️  Havia estado salvo mas a população estava extinta — começando uma população nova.")
        # Bootstrap: preenche a mesa (até MAX_ROOT_SEATS cadeiras) com
        # estratégias já pesquisadas (ver investigator.py) — cada uma
        # aprovada em toda a análise automática vai pra fila de aprovação
        # SUA, não nasce sozinha (ver Organism.propose_and_spawn/painel
        # "Aprovações pendentes"). Em produção o Investigador roda
        # continuamente (~30min) alimentando a mesma fila via ingest().
        investigador = bootstrap_feed()
        proposals = investigador.all_ingested()
        for i in range(roots):
            proposal = proposals[i % len(proposals)]
            symbol = symbols[i % len(symbols)]
            robot_id, reason = await organism.propose_and_spawn(proposal, symbol=symbol,
                                                                 bypass_root_cooldown=True)
            if robot_id:
                print(f"  🐣 {robot_id} nasceu especialista em {proposal.implementation}/{proposal.timeframe}/{symbol} com ${config.starting_capital}")
            elif "aguardando você na mesa" in reason:
                print(f"  🪑 '{proposal.name}' em {symbol} passou em toda a análise — aguardando sua aprovação no painel")
            else:
                print(f"  ⛔ Estrategista recusou '{proposal.name}' em {symbol}: {reason}")

    # Absorve pesquisas novas de investigator_research.py (script separado,
    # cron/GitHub Actions) automaticamente, sem precisar reiniciar o processo.
    feed_task = asyncio.create_task(organism.poll_strategy_feed())

    print(f"\n  População rodando (paper trading). Estado em: {organism.state_file}")
    print(f"  Painel de apurações: http://0.0.0.0:{config.dashboard_port}")
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
        dashboard_task.cancel()
        # Último save ANTES de cancelar as tasks dos robôs (run_until já
        # salva periodicamente, mas Ctrl+C pode interromper no meio do
        # intervalo — sem isso, retomar depois perderia até
        # save_interval_ticks de progresso).
        organism.save_full_state()
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
    parser.add_argument("--assets", default=None,
                        help="Classes de ativo a ligar nesta execução, separadas por vírgula "
                             "(ex: --assets crypto,stocks). Sobrescreve o habilitado em config.yaml. "
                             "'stocks' = ações/índices/commodities/futuros via Yahoo Finance "
                             "(grátis, sem chave — ver markets/yahoo.py). Sem esta flag, usa o que "
                             "já está habilitado em config.yaml (crypto por padrão).")
    parser.add_argument("--roots", type=int, default=10,
                        help="Quantas propostas raiz são submetidas no início pra preencher a mesa "
                             "(uma por proposta/ativo, ciclando) — padrão 10, as cadeiras da mesa "
                             "(Strategist.MAX_ROOT_SEATS). Cada uma só nasce depois de você aprovar "
                             "no painel.")
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

    if args.assets:
        wanted = {a.strip() for a in args.assets.split(",") if a.strip()}
        unknown = wanted - set(config.markets.keys())
        if unknown:
            print(f"\n❌ --assets desconhecido(s): {', '.join(sorted(unknown))}. "
                  f"Disponíveis: {', '.join(sorted(config.markets.keys()))}")
            sys.exit(1)
        for name, mc in config.markets.items():
            mc.enabled = name in wanted

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

    # Warn if no API keys — não se aplica a "stocks" (Yahoo Finance é dado
    # público, sem chave nenhuma, ver markets/yahoo.py).
    for name, mc in config.markets.items():
        if name == "stocks":
            continue
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

    # Universo pode misturar mais de uma classe de ativo (cripto via Bybit +
    # ações/índices/commodities/futuros via Yahoo Finance) — asset_classes
    # mapeia cada símbolo pro nome do mercado em config.markets que ele usa
    # (ver Organism._new_config, que só liga o adapter certo por robô).
    symbols = []
    asset_classes = {}

    crypto_enabled = config.markets.get("crypto") and config.markets["crypto"].enabled
    stocks_enabled = config.markets.get("stocks") and config.markets["stocks"].enabled

    if crypto_enabled:
        if args.symbols:
            crypto_symbols = [s.strip() for s in args.symbols.split(",") if s.strip()]
        elif args.universe:
            from darwin_agent.markets.symbol_universe import fetch_symbol_universe
            print(f"\n  🌐 Buscando até {args.universe} ativos negociáveis na Bybit...")
            crypto_symbols = asyncio.run(fetch_symbol_universe(target_size=args.universe))
            print(f"  📋 Universo cripto: {len(crypto_symbols)} ativos")
        else:
            crypto_symbols = ["BTCUSDT"]
        symbols.extend(crypto_symbols)
        asset_classes.update({s: "crypto" for s in crypto_symbols})
    elif args.symbols or args.universe:
        print("\n⚠️  --symbols/--universe ignorados: mercado 'crypto' não está habilitado "
              "(veja --assets/config.yaml).")

    if stocks_enabled:
        from darwin_agent.markets.multi_asset_universe import get_multi_asset_universe
        stock_symbols = get_multi_asset_universe()
        print(f"  📋 Universo multi-asset (Yahoo Finance): {len(stock_symbols)} ativos "
              f"(índices, commodities/futuros, ações US/BR)")
        symbols.extend(stock_symbols)
        asset_classes.update({s: "stocks" for s in stock_symbols})

    if not symbols:
        print("\n❌ Nenhum ativo pra operar — nenhuma classe de mercado habilitada.")
        sys.exit(1)

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
        loop.run_until_complete(run_forever(config, symbols, args.roots, asset_classes))
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
