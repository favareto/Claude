"""Simulação pura do organismo — valida o ciclo nascer→operar→clonar→morrer
sem depender de nenhuma exchange real (nem chaves de API), usando preços
sintéticos (markets/simulated.py). Sem Investigador/Professor reais ainda —
roadmap do CLAUDE.md, passo 4.

Uso:
    python -m darwin_agent.simulate
    python -m darwin_agent.simulate --robots 4 --seconds 30 --heartbeat 0.01
"""

import argparse
import asyncio

from darwin_agent.markets.simulated import SimulatedMarketAdapter
from darwin_agent.organism import Organism
from darwin_agent.utils.config import AgentConfig, MarketConfig

DEFAULT_SYMBOLS = ["SIM-A", "SIM-B", "SIM-C", "SIM-D"]


def _print_report(organism: Organism):
    organism._sync_alive_records()
    records = sorted(organism.records.values(), key=lambda r: r.born_at)
    print("\n" + "=" * 78)
    print("  RELATÓRIO DA POPULAÇÃO")
    print("=" * 78)
    print(f"{'id':<11} {'pai':<11} {'ativo':<7} {'status':<6} {'capital':>9} "
          f"{'pico':>9} {'dd%':>6} {'trades':>7} {'clones':>7}")
    print("-" * 78)
    for r in records:
        print(f"{r.id:<11} {(r.parent_id or '-'):<11} {r.symbol:<7} {r.status:<6} "
              f"${r.capital:>7.2f} ${r.peak_capital:>7.2f} {r.drawdown_pct:>5.1f}% "
              f"{r.total_trades:>7} {r.clones_generated:>7}")
        if r.status == "dead":
            print(f"             -> morreu: {r.cause_of_death}")
    summary = organism.summary()
    print("-" * 78)
    print(f"  Vivos: {summary['alive']} | Mortos: {summary['dead']} | "
          f"Capital total vivo: ${summary['total_capital_alive']:.2f} | "
          f"Clones gerados: {summary['total_clones']}")
    print("=" * 78)


async def main_async(n_robots: int, seconds: float, heartbeat: float, symbols):
    market = SimulatedMarketAdapter(symbols=symbols, volatility=0.006, drift=0.0002)

    base_config = AgentConfig(
        starting_capital=5.0,
        clone_multiplier=1.7,
        heartbeat_interval=heartbeat,
        log_level="WARNING",  # menos ruído no console durante a simulação
        markets={"crypto": MarketConfig(enabled=True, testnet=True)},
    )
    base_config.health.death_drawdown_pct = 60.0

    organism = Organism(
        base_config=base_config,
        symbols=symbols,
        real_adapter_factory=lambda mc: market,
        state_file="data/population.json",
    )

    for i in range(n_robots):
        robot_id = await organism.spawn_root(symbols[i % len(symbols)])
        print(f"Nasceu {robot_id} especialista em {symbols[i % len(symbols)]} com $5")

    start = asyncio.get_event_loop().time()

    def timed_out(_org):
        return asyncio.get_event_loop().time() - start >= seconds

    await organism.run_until(timed_out, check_interval=0.5)
    await organism.shutdown()
    _print_report(organism)
    print(f"\nEstado completo salvo em: {organism.state_file}")


def main():
    parser = argparse.ArgumentParser(description="Simulação pura do organismo de robôs")
    parser.add_argument("--robots", type=int, default=3, help="robôs raiz iniciais")
    parser.add_argument("--seconds", type=float, default=30.0, help="duração da simulação (segundos reais)")
    parser.add_argument("--heartbeat", type=float, default=0.02, help="intervalo entre ciclos de cada robô (segundos)")
    args = parser.parse_args()

    asyncio.run(main_async(args.robots, args.seconds, args.heartbeat, DEFAULT_SYMBOLS))


if __name__ == "__main__":
    main()
