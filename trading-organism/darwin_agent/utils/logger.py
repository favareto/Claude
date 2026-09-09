"""Logging system with structured trade journal."""

import logging
import json
import os
from datetime import datetime, timezone
from typing import Optional


class DarwinLogger:
    def __init__(self, label: str = "0", log_level: str = "INFO"):
        self.label = str(label)
        self.log_dir = "data/logs"
        os.makedirs(self.log_dir, exist_ok=True)

        # logging.getLogger(name) is a singleton per name — each robot needs
        # a unique label (its robot_id) so concurrent robots don't clobber
        # each other's handlers/log files.
        self.logger = logging.getLogger(f"Darwin.{self.label}")
        self.logger.setLevel(getattr(logging, log_level, logging.INFO))
        self.logger.handlers.clear()
        self.logger.propagate = False

        fmt = logging.Formatter(
            f"[{self.label}] %(asctime)s %(levelname)s %(message)s",
            datefmt="%H:%M:%S"
        )

        ch = logging.StreamHandler()
        ch.setLevel(getattr(logging, log_level, logging.INFO))
        ch.setFormatter(fmt)
        self.logger.addHandler(ch)

        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        fh = logging.FileHandler(f"{self.log_dir}/{self.label}_{ts}.log")
        fh.setLevel(logging.DEBUG)
        fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        self.logger.addHandler(fh)

        self.trade_journal = f"{self.log_dir}/trades_{self.label}.jsonl"

    def born(self, capital: float, inherited_from: Optional[str] = None):
        msg = f"BORN Capital: ${capital:.2f}"
        if inherited_from is not None:
            msg += f" | Clonado de {inherited_from}"
        self.logger.info(msg)

    def trade(self, action: str, market: str, symbol: str, amount: float,
              price: float, reason: str, result: Optional[dict] = None):
        entry = {
            "type": "entry",
            "ts": datetime.now(timezone.utc).isoformat(),
            "robot": self.label,
            "action": action,
            "market": market,
            "symbol": symbol,
            "amount": round(amount, 6),
            "price": round(price, 4),
            "reason": reason,
            "result": result
        }
        self._append_journal(entry)
        side = "BUY" if action == "BUY" else "SELL"
        self.logger.info(f"{side} {symbol} x{amount:.6f} @ ${price:.4f} | {reason}")

    def position_closed(self, symbol: str, side: str, quantity: float,
                        entry_price: float, entry_time, exit_price: float, exit_time,
                        pnl: float, pnl_pct: float, strategy: str = ""):
        """Registro de posição completa (entrada + saída) — o que o painel
        de apurações usa pra mostrar hora de entrada/saída, lado, e P&L de
        cada operação fechada. `entry_time`/`exit_time` aceitam datetime ou
        string ISO."""
        entry_iso = entry_time.isoformat() if hasattr(entry_time, "isoformat") else str(entry_time)
        exit_iso = exit_time.isoformat() if hasattr(exit_time, "isoformat") else str(exit_time)
        try:
            duration_seconds = (exit_time - entry_time).total_seconds() if hasattr(entry_time, "isoformat") else None
        except Exception:
            duration_seconds = None

        record = {
            "type": "position_closed",
            "ts": exit_iso,
            "robot": self.label,
            "strategy": strategy,
            "symbol": symbol,
            "side": side,
            "quantity": round(quantity, 6),
            "entry_time": entry_iso,
            "entry_price": round(entry_price, 6),
            "exit_time": exit_iso,
            "exit_price": round(exit_price, 6),
            "duration_seconds": duration_seconds,
            "pnl": round(pnl, 4),
            "pnl_pct": round(pnl_pct, 4),
        }
        self._append_journal(record)
        self.logger.info(
            f"CLOSED {side.upper()} {symbol} entry@${entry_price:.4f} ({entry_iso[11:19]}) -> "
            f"exit@${exit_price:.4f} ({exit_iso[11:19]}) | PnL: ${pnl:+.2f} ({pnl_pct:+.2f}%)"
        )

    def _append_journal(self, record: dict):
        try:
            with open(self.trade_journal, "a") as f:
                f.write(json.dumps(record) + "\n")
        except Exception:
            pass

    def health_update(self, hp: float, change: float, reason: str):
        self.logger.info(f"HP: {hp:.1f}/100 ({change:+.1f}) | {reason}")

    def death(self, cause: str, final_capital: float, trades_total: int,
              win_rate: float, lifespan_hours: float):
        self.logger.critical(
            f"DEATH Cause: {cause} | Capital: ${final_capital:.2f} | "
            f"Trades: {trades_total} | WR: {win_rate:.1%} | Life: {lifespan_hours:.1f}h"
        )

    def evolution(self, msg: str):
        self.logger.info(f"EVO {msg}")

    def warning(self, msg: str):
        self.logger.warning(msg)

    def info(self, msg: str):
        self.logger.info(msg)

    def error(self, msg: str):
        self.logger.error(msg)
