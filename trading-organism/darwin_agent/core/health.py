"""Health System — elimina o robô quando o capital cai `death_drawdown_pct`
(padrão 60%) a partir do PICO de capital que ele já alcançou (não do valor
atual). Regra fixa do organismo — ver CLAUDE.md.

`current_hp`/`max_hp` são mantidos como uma projeção 0-100 do drawdown atual
(só para compatibilidade com logging/dashboard existentes); a morte é
sempre decidida por `current_drawdown_pct`, nunca pelo HP em si.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import List, Optional
from enum import Enum


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class HealthStatus(Enum):
    HEALTHY = "healthy"
    WOUNDED = "wounded"
    CRITICAL = "critical"
    DEAD = "dead"


@dataclass
class HealthEvent:
    timestamp: datetime
    change: float
    reason: str
    event_type: str


@dataclass
class HealthSystem:
    peak_capital: float = 5.0
    current_capital: float = 5.0
    is_alive: bool = True
    cause_of_death: Optional[str] = None
    death_time: Optional[datetime] = None

    death_drawdown_pct: float = 60.0

    win_streak: int = 0
    loss_streak: int = 0
    total_trades: int = 0
    winning_trades: int = 0
    history: List[HealthEvent] = field(default_factory=list)

    @property
    def current_drawdown_pct(self) -> float:
        if self.peak_capital <= 0:
            return 0.0
        return max(0.0, (self.peak_capital - self.current_capital) / self.peak_capital) * 100

    @property
    def win_rate(self) -> float:
        return self.winning_trades / self.total_trades if self.total_trades > 0 else 0.0

    @property
    def max_hp(self) -> float:
        return 100.0

    @property
    def current_hp(self) -> float:
        if not self.is_alive:
            return 0.0
        ratio = self.current_drawdown_pct / self.death_drawdown_pct if self.death_drawdown_pct > 0 else 0.0
        return max(0.0, 100.0 * (1.0 - ratio))

    def get_status(self) -> HealthStatus:
        if not self.is_alive:
            return HealthStatus.DEAD
        ratio = self.current_drawdown_pct / self.death_drawdown_pct if self.death_drawdown_pct > 0 else 0.0
        if ratio > 0.66:
            return HealthStatus.CRITICAL
        if ratio > 0.33:
            return HealthStatus.WOUNDED
        return HealthStatus.HEALTHY

    def _die(self, cause: str):
        self.is_alive = False
        self.cause_of_death = cause
        self.death_time = _utcnow()

    def record_trade(self, pnl: float, pnl_pct: float):
        """Só atualiza estatísticas de trades (usadas no painel). A morte é
        decidida exclusivamente em `update_capital`."""
        if not self.is_alive:
            return
        self.total_trades += 1
        if pnl > 0:
            self.winning_trades += 1
            self.win_streak += 1
            self.loss_streak = 0
            reason = f"Win ${pnl:.2f} ({pnl_pct:+.2f}%)"
            event_type = "trade_win"
        else:
            self.loss_streak += 1
            self.win_streak = 0
            reason = f"Loss ${pnl:.2f} ({pnl_pct:+.2f}%)"
            event_type = "trade_loss"
        self.history.append(HealthEvent(
            timestamp=_utcnow(), change=pnl, reason=reason, event_type=event_type
        ))

    def update_capital(self, new_capital: float):
        if not self.is_alive:
            return
        self.current_capital = new_capital
        if new_capital > self.peak_capital:
            self.peak_capital = new_capital

        dd = self.current_drawdown_pct
        if dd >= self.death_drawdown_pct:
            self._die(
                f"Drawdown {dd:.1f}% do pico (${self.peak_capital:.2f} -> "
                f"${new_capital:.2f}) atingiu o limite de {self.death_drawdown_pct:.0f}%"
            )

    def get_vitals(self) -> dict:
        return {
            "hp": round(self.current_hp, 1),
            "max_hp": self.max_hp,
            "status": self.get_status().value,
            "is_alive": self.is_alive,
            "capital": round(self.current_capital, 2),
            "peak_capital": round(self.peak_capital, 2),
            "drawdown_pct": round(self.current_drawdown_pct, 2),
            "death_drawdown_pct": self.death_drawdown_pct,
            "total_trades": self.total_trades,
            "win_rate": round(self.win_rate, 4),
            "win_streak": self.win_streak,
            "loss_streak": self.loss_streak,
            "cause_of_death": self.cause_of_death,
        }
