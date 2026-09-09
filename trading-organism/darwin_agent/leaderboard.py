"""Ranking vivo de estratégias — até 500, realimentado continuamente pelo
Investigador e reordenado pelos eventos reais da população (ver CLAUDE.md).

Regras (conforme especificado):
- Uma estratégia nova, trazida pelo Investigador, entra no ranking se
  houver vaga OU se for melhor que a pior colocada — nesse caso ela
  sobrepõe (substitui) a pior.
- Quando um robô com uma estratégia é ELIMINADO (drawdown -60%), a
  estratégia é REBAIXADA no ranking.
- Quando um robô com uma estratégia CLONA (bate +70%), a estratégia é
  PROMOVIDA no ranking.
- Isso é avaliação por MÉRITO real (resultado dos robôs), não por
  formulário — é a autonomia do Estrategista expressa como ranking.
"""

import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

from darwin_agent.investigator import StrategyProposal


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class LeaderboardEntry:
    strategy_id: str
    name: str
    implementation: str
    timeframe: str
    source: str
    added_at: str
    attempts: int = 0  # robôs nascidos com esta estratégia
    clones: int = 0    # eventos de clonagem (+70%)
    deaths: int = 0    # eventos de eliminação (-60% do pico)

    @property
    def score(self) -> float:
        """Razão suavizada (Laplace) clones/mortes — sobe com promoção,
        desce com rebaixamento. Estratégia nova (0/0) começa neutra em 1.0,
        podendo competir por uma vaga até acumular histórico próprio."""
        return (self.clones + 1) / (self.deaths + 1)

    def to_dict(self) -> dict:
        return {
            "strategy_id": self.strategy_id, "name": self.name,
            "implementation": self.implementation, "timeframe": self.timeframe,
            "source": self.source, "added_at": self.added_at,
            "attempts": self.attempts, "clones": self.clones, "deaths": self.deaths,
            "score": round(self.score, 3),
        }


class StrategyLeaderboard:
    CAPACITY = 500

    def __init__(self, capacity: int = CAPACITY):
        self.capacity = capacity
        self._entries: Dict[str, LeaderboardEntry] = {}

    def __len__(self) -> int:
        return len(self._entries)

    def get(self, strategy_id: str) -> Optional[LeaderboardEntry]:
        return self._entries.get(strategy_id)

    def consider(self, proposal: StrategyProposal) -> Tuple[bool, str]:
        """Uma proposta nova do Investigador tenta entrar no ranking.
        Aceita direto se: já está no ranking (reforça a mesma entrada), ou
        há vaga livre. Se o ranking está cheio, só entra se for melhor que
        a pior colocada — nesse caso ela é substituída (sobreposta)."""
        sid = proposal.strategy_id
        if sid in self._entries:
            return True, f"'{proposal.name}' já está no ranking (posição atual mantida)"

        if len(self._entries) < self.capacity:
            self._entries[sid] = LeaderboardEntry(
                strategy_id=sid, name=proposal.name, implementation=proposal.implementation,
                timeframe=proposal.timeframe, source=proposal.source,
                added_at=_utcnow().isoformat(),
            )
            return True, f"'{proposal.name}' entrou no ranking ({len(self._entries)}/{self.capacity})"

        worst_id, worst = min(self._entries.items(), key=lambda kv: kv[1].score)
        # Proposta nova começa com score neutro (1.0, ver LeaderboardEntry.score);
        # só desbanca quem já provou ser pior que neutro (mais mortes que clones).
        new_score = 1.0
        if new_score > worst.score:
            del self._entries[worst_id]
            self._entries[sid] = LeaderboardEntry(
                strategy_id=sid, name=proposal.name, implementation=proposal.implementation,
                timeframe=proposal.timeframe, source=proposal.source,
                added_at=_utcnow().isoformat(),
            )
            return True, (f"'{proposal.name}' sobrepôs '{worst.name}' "
                          f"(score {worst.score:.2f}, {worst.deaths} mortes/{worst.clones} clones) no ranking")

        return False, (f"Ranking cheio ({len(self._entries)}/{self.capacity}) e '{proposal.name}' não supera a "
                       f"pior colocada ('{worst.name}', score {worst.score:.2f}) — fica de fora por agora")

    def register_attempt(self, strategy_id: str):
        e = self._entries.get(strategy_id)
        if e:
            e.attempts += 1

    def promote(self, strategy_id: str):
        """Robô com esta estratégia clonou (+70%) — sobe no ranking."""
        e = self._entries.get(strategy_id)
        if e:
            e.clones += 1

    def demote(self, strategy_id: str):
        """Robô com esta estratégia foi eliminado (-60% do pico) — desce no ranking."""
        e = self._entries.get(strategy_id)
        if e:
            e.deaths += 1

    def top(self, n: int = 20) -> List[LeaderboardEntry]:
        return sorted(self._entries.values(), key=lambda e: e.score, reverse=True)[:n]

    def bottom(self, n: int = 20) -> List[LeaderboardEntry]:
        return sorted(self._entries.values(), key=lambda e: e.score)[:n]

    def all_entries(self) -> List[LeaderboardEntry]:
        return list(self._entries.values())
