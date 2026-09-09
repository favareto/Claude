"""Agente-robô — nasce com capital fixo, opera um único ativo (especialista),
clona quando o capital multiplica (config.clone_multiplier) e morre quando
o drawdown desde o pico atinge config.health.death_drawdown_pct.

Toda entrada passa pelo Estrategista (strategist.py) antes de executar.
Reaproveita a camada de decisão do Darwin Agent (ml/brain.py, ml/selector.py,
strategies/base.py) e a execução em papel (markets/crypto.py
PaperTradingAdapter) — só a gestão de vida/população é nova.
"""

import asyncio
import uuid
from datetime import datetime, timezone, timedelta
from enum import Enum
from typing import Callable, Dict, List, Optional

from darwin_agent.core.health import HealthSystem, HealthStatus
from darwin_agent.markets.base import MarketAdapter, TimeFrame, OrderSide, OrderType
from darwin_agent.markets.crypto import BybitAdapter, PaperTradingAdapter
from darwin_agent.strategies.base import STRATEGY_CLASSES, STRATEGY_REGISTRY
from darwin_agent.strategist import Strategist
from darwin_agent.ml.brain import SingleStrategyBrain
from darwin_agent.ml.features import N_FEATURES
from darwin_agent.ml.selector import AdaptiveSelector
from darwin_agent.utils.config import AgentConfig
from darwin_agent.utils.logger import DarwinLogger


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class AgentPhase(Enum):
    LIVE = "live"
    DEAD = "dead"


class DarwinAgentV2:
    def __init__(self, config: AgentConfig, strategy_name: str,
                 robot_id: Optional[str] = None,
                 strategist: Optional[Strategist] = None,
                 parent_id: Optional[str] = None,
                 strategy_params: Optional[dict] = None,
                 on_clone: Optional[Callable] = None,
                 on_death: Optional[Callable] = None,
                 real_adapter_factory: Optional[Callable[[dict], MarketAdapter]] = None):
        if not config.symbol:
            raise ValueError("AgentConfig.symbol é obrigatório — cada robô opera um único ativo")
        if strategy_name not in STRATEGY_REGISTRY:
            raise ValueError(f"Estratégia desconhecida: {strategy_name}")

        self.config = config
        self.robot_id = robot_id or f"r-{uuid.uuid4().hex[:8]}"
        self.parent_id = parent_id
        self.symbol = config.symbol
        self.strategy_name = strategy_name
        # Currículo do Professor (professor.py) — parâmetros do robô
        # ajustados pro ativo específico. Vazio = defaults da estratégia.
        self.strategy_params = strategy_params or {}
        self.strategist = strategist or Strategist(config.risk)
        self.on_clone = on_clone
        self.on_death = on_death
        self._real_adapter_factory = real_adapter_factory

        self.logger = DarwinLogger(self.robot_id, config.log_level)
        self.health = HealthSystem(
            peak_capital=config.starting_capital,
            current_capital=config.starting_capital,
            death_drawdown_pct=config.health.death_drawdown_pct,
        )

        # ML — decisão de posicionamento (tamanho/confiança/entrar-ou-não)
        # dentro da ÚNICA estratégia validada pra este robô (ver CLAUDE.md:
        # "opera uma estratégia validada"). Herdado do pai em clonagem via
        # inherit_brain_from — sempre a mesma strategy_name, então os pesos
        # têm o mesmo formato.
        self.brain = SingleStrategyBrain(strategy_name, n_features=N_FEATURES, epsilon=0.3)
        self.selector = AdaptiveSelector(self.brain)
        if self.strategy_params:
            # Substitui a instância genérica pela parametrizada (currículo
            # do Professor) — só a entrada da estratégia deste robô, já que
            # o SingleStrategyBrain nunca escolhe outra.
            self.selector.strategies[strategy_name] = STRATEGY_CLASSES[strategy_name](params=self.strategy_params)

        self.markets: Dict[str, MarketAdapter] = {}
        self.phase = AgentPhase.LIVE
        self.born_at = _utcnow()
        self.cycle_count = 0
        self.cooldown_until: Optional[datetime] = None
        self.clones_generated = 0

        # Marco de capital usado pra disparar a próxima clonagem: clona
        # quando current_capital >= _clone_milestone * clone_multiplier.
        self._clone_milestone = config.starting_capital

        self._last_candles: Dict[str, list] = {}
        self._symbol_errors: Dict[str, int] = {}
        self._max_symbol_errors = 5
        self._death_reported = False

        self._cooldown_outcomes: List[Dict] = []
        self._learned_cooldown_mult = 5.0

        self._scan_timeframe = self._resolve_timeframe(config.scan_timeframe)
        self._aggression_level = max(0.5, min(3.0, float(config.aggression_level)))
        self._candle_lookback = 120 if self._scan_timeframe == TimeFrame.M1 else 100

    def _resolve_timeframe(self, timeframe_value: str) -> TimeFrame:
        mapping = {
            "1m": TimeFrame.M1, "5m": TimeFrame.M5, "15m": TimeFrame.M15,
            "1h": TimeFrame.H1, "4h": TimeFrame.H4, "1d": TimeFrame.D1,
            "1w": TimeFrame.W1,
        }
        return mapping.get((timeframe_value or "15m").lower(), TimeFrame.M15)

    def inherit_brain_from(self, parent: "DarwinAgentV2"):
        """Clone literal do cérebro do pai — a multiplicação IS a otimização
        (ver CLAUDE.md: 'não há ajuste de parâmetro por fora' da clonagem)."""
        self.selector.import_from_dna(parent.selector.export_for_dna(), mutation_rate=0.0)

    async def _init_markets(self):
        for name, mc in self.config.markets.items():
            if not mc.enabled:
                continue
            try:
                if self._real_adapter_factory:
                    real = self._real_adapter_factory(mc)
                else:
                    real = BybitAdapter({
                        "api_key": mc.api_key, "api_secret": mc.api_secret, "testnet": mc.testnet,
                    })
                # Sempre paper trading nesta fase — nada de dinheiro real (ver CLAUDE.md).
                adapter = PaperTradingAdapter(real, self.config.starting_capital)
                if await adapter.connect():
                    self.markets[name] = adapter
                    self.logger.info(f"[{self.robot_id}] Connected: {name} [PAPER] symbol={self.symbol}")
                else:
                    self.logger.error(f"Market connect failed: {name}")
            except Exception as e:
                self.logger.error(f"Market init error: {e}")

    async def _check_market_health(self) -> bool:
        if not self.markets:
            return False
        adapter = list(self.markets.values())[0]
        try:
            price = await adapter.get_current_price(self.symbol)
            if price > 0:
                return True
        except Exception:
            pass
        self.logger.warning("Market connection lost. Reconnecting...")
        try:
            await adapter.disconnect()
        except Exception:
            pass
        self.markets.clear()
        await self._init_markets()
        return bool(self.markets)

    async def run(self):
        """Ciclo de vida completo: valida estratégia -> opera -> clona/morre."""
        ok, reason = self.strategist.validate_strategy(self.robot_id, self.symbol, [self.strategy_name])
        if not ok:
            await self._die(f"Estrategista recusou a estratégia no nascimento: {reason}")
            return

        self.logger.born(self.config.starting_capital, self.parent_id)
        await self._init_markets()
        if not self.markets:
            await self._die("No markets available")
            return

        self.logger.info(
            f"[{self.robot_id}] symbol={self.symbol} | Heartbeat: {self.config.heartbeat_interval}s | "
            f"Scan: {self._scan_timeframe.value} | Aggression: {self._aggression_level:.2f}"
        )

        try:
            while self.health.is_alive:
                self.cycle_count += 1
                await self._heartbeat()
                if not self.health.is_alive:
                    break
                await asyncio.sleep(self.config.heartbeat_interval)
        except (KeyboardInterrupt, asyncio.CancelledError):
            self.logger.warning("Cancelled")
        except Exception as e:
            self.logger.error(f"Fatal: {e}")
            await self._die(f"Fatal: {e}")
        finally:
            await self._die()
            await self._cleanup()

    async def _heartbeat(self):
        if not self.health.is_alive:
            return

        if self.cycle_count % 5 == 0:
            self.logger.health_update(self.health.current_hp, 0,
                f"[{self.robot_id}] Cycle {self.cycle_count} | capital=${self.health.current_capital:.2f} | "
                f"DD={self.health.current_drawdown_pct:.1f}% | eps={self.brain.epsilon:.3f}")

        if self.cycle_count % 10 == 0:
            if not await self._check_market_health():
                self.logger.error("Markets unavailable, skipping cycle")
                return

        if self.cooldown_until and _utcnow() < self.cooldown_until:
            return

        try:
            await self._trade_cycle()
        except Exception as e:
            self.logger.error(f"Cycle error (non-fatal): {e}")

        if not self.health.is_alive:
            return
        await self._check_clone()

    async def _manage_positions(self, adapter):
        try:
            positions = await adapter.get_open_positions()
        except Exception as e:
            self.logger.error(f"Cannot get positions: {e}")
            return

        closed_any = False
        for pos in positions:
            try:
                price = await adapter.get_current_price(pos.symbol)
                if price <= 0:
                    continue
                pos.update_pnl(price)

                if pos.has_server_sltp:
                    continue

                close = False
                if pos.stop_loss:
                    if (pos.side == OrderSide.BUY and price <= pos.stop_loss) or \
                       (pos.side == OrderSide.SELL and price >= pos.stop_loss):
                        close = True
                if pos.take_profit:
                    if (pos.side == OrderSide.BUY and price >= pos.take_profit) or \
                       (pos.side == OrderSide.SELL and price <= pos.take_profit):
                        close = True

                if close:
                    result = await adapter.close_position(pos)
                    if result.success:
                        self._process_result(pos.pnl, pos.pnl_pct, pos.symbol)
                        closed_any = True
            except Exception as e:
                self.logger.error(f"Position mgmt {pos.symbol}: {e}")

        if closed_any:
            try:
                balance = await adapter.get_balance()
                if balance >= 0:
                    self.health.update_capital(balance)
            except Exception:
                pass

    async def _trade_cycle(self):
        adapter = list(self.markets.values())[0]
        await self._manage_positions(adapter)
        if not self.health.is_alive:
            return

        symbol = self.symbol
        if self._symbol_errors.get(symbol, 0) >= self._max_symbol_errors:
            return

        try:
            candles = await adapter.get_candles(symbol, self._scan_timeframe, limit=self._candle_lookback)
            if not candles or len(candles) < 50:
                return

            self._last_candles[symbol] = candles
            hp = self.health.current_hp / self.health.max_hp
            decision = self.selector.decide(candles, symbol, self._scan_timeframe, hp)

            if decision.should_trade and decision.signal:
                positions = await adapter.get_open_positions()
                ok, reason = self.strategist.validate_entry(
                    self.robot_id, decision.signal, self.health.current_capital, len(positions))
                if ok:
                    base_mult = self.selector.sizing_multipliers.get(
                        decision.action.sizing if decision.action else "normal", 1.0)
                    vol_mult = self._volatility_sizing(candles)
                    health_mult = self._health_sizing(hp)
                    final_mult = base_mult * vol_mult * health_mult * self._aggression_level
                    await self._execute(decision, adapter, final_mult)
                else:
                    self.selector.report_result(0, 0)
            else:
                self.selector.report_hold_result(candles, symbol)

            self._symbol_errors[symbol] = 0
        except Exception as e:
            self._symbol_errors[symbol] = self._symbol_errors.get(symbol, 0) + 1
            self.logger.error(f"{symbol}: {e} (errors: {self._symbol_errors[symbol]})")

    def _volatility_sizing(self, candles) -> float:
        if len(candles) < 20:
            return 1.0
        closes = [c.close for c in candles[-20:]]
        returns = [(closes[i] - closes[i-1]) / closes[i-1] for i in range(1, len(closes))]
        vol = float(max(0.001, (sum(r**2 for r in returns) / len(returns)) ** 0.5))
        baseline_vol = 0.01
        ratio = baseline_vol / max(vol, 0.001)
        return max(0.5, min(1.5, ratio))

    def _health_sizing(self, health_pct: float) -> float:
        if health_pct > 0.7:
            return 1.0
        elif health_pct > 0.4:
            return 0.75
        elif health_pct > 0.2:
            return 0.5
        else:
            return 0.3

    async def _execute(self, decision, adapter, sizing_mult=1.0) -> bool:
        signal = decision.signal
        if not signal:
            return False

        size = self.strategist.calculate_position_size(
            self.robot_id, self.health.current_capital, signal.entry_price, signal.stop_loss)
        size *= sizing_mult

        # Reaplica o teto de acessibilidade depois dos multiplicadores de
        # agressividade/volatilidade/saúde — sem isso, a multiplicação em
        # cascata pode pedir mais do que o capital do robô permite (fica
        # muito visível com capital de $5; RiskManager já limita antes dos
        # multiplicadores, mas eles podem estourar de novo).
        if signal.entry_price > 0:
            max_affordable = (self.health.current_capital * 0.9) / signal.entry_price
            size = min(size, max_affordable)

        min_size = await adapter.get_min_trade_size(signal.symbol)
        if size < min_size:
            return False

        result = await adapter.place_order(
            symbol=signal.symbol, side=signal.side, order_type=OrderType.MARKET,
            quantity=size, stop_loss=signal.stop_loss, take_profit=signal.take_profit)

        if result.success:
            strat = decision.action.strategy if decision.action else "unknown"
            self.logger.trade(
                action=signal.side.value.upper(), market="crypto",
                symbol=signal.symbol, amount=size, price=signal.entry_price,
                reason=f"[{strat}] {signal.reason}")
            return True
        else:
            self.logger.warning(f"Order failed: {result.error}")
            return False

    def _process_result(self, pnl, pnl_pct, symbol):
        self.health.record_trade(pnl, pnl_pct)
        candles = self._last_candles.get(symbol)
        self.selector.report_result(pnl_pct, pnl_pct, candles, symbol)
        self.strategist.record_result(self.robot_id, pnl, self.health.current_capital)

        if self.health.loss_streak >= 2:
            mins = self.health.loss_streak * self._learned_cooldown_mult / max(0.75, self._aggression_level)
            self.cooldown_until = _utcnow() + timedelta(minutes=mins)
            self.logger.warning(f"Cooldown {mins:.0f}min (streak:{self.health.loss_streak})")
        elif self.cooldown_until and pnl > 0:
            self._learn_cooldown(success=True)
        elif self.cooldown_until and pnl <= 0:
            self._learn_cooldown(success=False)

        if self.cooldown_until and _utcnow() >= self.cooldown_until:
            self.cooldown_until = None

        self.logger.health_update(self.health.current_hp, 0,
                                  f"Trade: ${pnl:+.2f} ({pnl_pct:+.2f}%) | {symbol}")

    def _learn_cooldown(self, success: bool):
        if success:
            self._learned_cooldown_mult = max(2.0, self._learned_cooldown_mult * 0.95)
        else:
            self._learned_cooldown_mult = min(15.0, self._learned_cooldown_mult * 1.1)

    async def _check_clone(self):
        """Clonagem: capital >= último marco * clone_multiplier (ver CLAUDE.md).
        O original NÃO reseta — segue operando com o saldo cheio; o clone
        nasce com capital inicial (config.starting_capital)."""
        cap = self.health.current_capital
        if cap >= self._clone_milestone * self.config.clone_multiplier:
            self._clone_milestone = cap
            self.clones_generated += 1
            self.logger.evolution(
                f"[{self.robot_id}] CLONE! capital=${cap:.2f} (x{self.config.clone_multiplier} do marco)")
            if self.on_clone:
                await self.on_clone(self)

    async def _die(self, cause: Optional[str] = None):
        if self._death_reported:
            return
        if self.health.is_alive and cause:
            self.health._die(cause)
        if not self.health.is_alive:
            self._death_reported = True
            self.phase = AgentPhase.DEAD
            final_cause = self.health.cause_of_death or cause or "Unknown"
            life_hours = (_utcnow() - self.born_at).total_seconds() / 3600
            self.logger.death(final_cause, self.health.current_capital, self.health.total_trades,
                             self.health.win_rate, life_hours)
            if self.on_death:
                await self.on_death(self, final_cause)

    async def _cleanup(self):
        for a in self.markets.values():
            try:
                await a.disconnect()
            except Exception:
                pass

    def get_status(self):
        return {
            "robot_id": self.robot_id,
            "parent_id": self.parent_id,
            "symbol": self.symbol,
            "strategy_name": self.strategy_name,
            "strategy_params": self.strategy_params,
            "phase": self.phase.value,
            "health": self.health.get_vitals(),
            "clones_generated": self.clones_generated,
            "cycle": self.cycle_count,
            "uptime_seconds": (_utcnow() - self.born_at).total_seconds(),
            "scan_timeframe": self._scan_timeframe.value,
            "aggression_level": round(self._aggression_level, 2),
        }
