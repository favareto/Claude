"""Configuration — Typed, validated, with sensible defaults."""

import yaml
import os
from dataclasses import dataclass, field
from typing import Dict


@dataclass
class MarketConfig:
    enabled: bool = False
    api_key: str = ""
    api_secret: str = ""
    testnet: bool = True
    max_allocation_pct: float = 60.0


@dataclass
class HealthConfig:
    # Eliminação: drawdown desde o pico de capital do próprio robô.
    death_drawdown_pct: float = 60.0


@dataclass
class RiskConfig:
    # Reduzido de 2.0 -> 1.0: aposta menor por trade (sobre o risk_basis
    # ancorado no capital inicial, ver core/agent_v2.py) significa mais
    # trades até bater +70%/-60% — track record mais longo antes do
    # Estrategista/leaderboard julgarem por mérito (ver CLAUDE.md).
    max_position_pct: float = 1.0
    max_open_positions: int = 3
    max_daily_trades: int = 20
    max_daily_loss_pct: float = 5.0
    default_stop_loss_pct: float = 1.5
    default_take_profit_pct: float = 3.0
    min_risk_reward_ratio: float = 1.5


@dataclass
class AgentConfig:
    # Regras de vida do organismo (ver CLAUDE.md — não mudar sem confirmação).
    starting_capital: float = 5.0
    clone_multiplier: float = 1.7  # clona quando capital >= último marco * 1.7

    # Ativo em que este robô é especialista. Atribuído pelo Macro-organismo
    # (organism.py) na hora do nascimento; cada robô opera só este símbolo.
    symbol: str = ""

    markets: Dict[str, MarketConfig] = field(default_factory=lambda: {
        "crypto": MarketConfig(enabled=True, testnet=True),
    })
    health: HealthConfig = field(default_factory=HealthConfig)
    risk: RiskConfig = field(default_factory=RiskConfig)
    log_level: str = "INFO"
    heartbeat_interval: int = 60
    dashboard_port: int = 8080
    scan_timeframe: str = "1m"
    aggression_level: float = 1.35

    def validate(self):
        errors = []
        if self.starting_capital <= 0:
            errors.append("Starting capital must be > 0")
        if self.risk.max_position_pct > 10:
            errors.append("Max position % too high (max 10%)")
        if self.risk.min_risk_reward_ratio < 1.0:
            errors.append("Risk/reward ratio must be >= 1.0")
        if not (0 < self.health.death_drawdown_pct <= 100):
            errors.append("death_drawdown_pct must be between 0 and 100")
        if self.clone_multiplier <= 1.0:
            errors.append("clone_multiplier must be > 1.0")
        if not any(m.enabled for m in self.markets.values()):
            errors.append("At least one market must be enabled")
        allowed_timeframes = {"1m", "5m", "15m", "1h", "4h", "1d", "1w"}
        if self.scan_timeframe not in allowed_timeframes:
            errors.append(f"scan_timeframe must be one of: {', '.join(sorted(allowed_timeframes))}")
        if not (0.5 <= self.aggression_level <= 3.0):
            errors.append("aggression_level must be between 0.5 and 3.0")
        if errors:
            raise ValueError("Config errors: " + "; ".join(errors))


def load_config(path: str = "config.yaml") -> AgentConfig:
    config = AgentConfig()

    if not os.path.exists(path):
        return config

    with open(path, "r") as f:
        try:
            data = yaml.safe_load(f) or {}
        except yaml.YAMLError as e:
            raise ValueError(f"Invalid YAML in config file '{path}': {e}") from e

    for key in (
        "starting_capital",
        "clone_multiplier",
        "symbol",
        "heartbeat_interval",
        "log_level",
        "dashboard_port",
        "scan_timeframe",
        "aggression_level",
    ):
        if key in data:
            setattr(config, key, type(getattr(config, key))(data[key]))

    if "markets" in data:
        # If user explicitly provides markets, treat it as authoritative
        # to avoid silently keeping the default "crypto" market enabled.
        config.markets = {}
        for name, mdata in data["markets"].items():
            mc = MarketConfig()
            for k, v in (mdata or {}).items():
                if hasattr(mc, k):
                    setattr(mc, k, v)
            config.markets[name] = mc

    for section, obj in [("health", config.health), ("risk", config.risk)]:
        if section in data and data[section]:
            for k, v in data[section].items():
                if hasattr(obj, k):
                    setattr(obj, k, v)

    return config


def config_to_dict(config: AgentConfig) -> Dict:
    """Serialize AgentConfig to plain dict for APIs/YAML dump."""
    return {
        "starting_capital": config.starting_capital,
        "clone_multiplier": config.clone_multiplier,
        "symbol": config.symbol,
        "heartbeat_interval": config.heartbeat_interval,
        "log_level": config.log_level,
        "dashboard_port": config.dashboard_port,
        "scan_timeframe": config.scan_timeframe,
        "aggression_level": config.aggression_level,
        "markets": {
            name: {
                "enabled": market.enabled,
                "api_key": market.api_key,
                "api_secret": market.api_secret,
                "testnet": market.testnet,
                "max_allocation_pct": market.max_allocation_pct,
            }
            for name, market in config.markets.items()
        },
        "health": {
            "death_drawdown_pct": config.health.death_drawdown_pct,
        },
        "risk": {
            "max_position_pct": config.risk.max_position_pct,
            "max_open_positions": config.risk.max_open_positions,
            "max_daily_trades": config.risk.max_daily_trades,
            "max_daily_loss_pct": config.risk.max_daily_loss_pct,
            "default_stop_loss_pct": config.risk.default_stop_loss_pct,
            "default_take_profit_pct": config.risk.default_take_profit_pct,
            "min_risk_reward_ratio": config.risk.min_risk_reward_ratio,
        },
    }


def save_config(config: AgentConfig, path: str = "config.yaml"):
    """Persist AgentConfig into YAML file.

    Creates parent directories when needed and writes atomically to avoid
    partial/corrupt config files if the process is interrupted.
    """
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)

    tmp_path = f"{path}.tmp"
    with open(tmp_path, "w") as f:
        yaml.safe_dump(config_to_dict(config), f, sort_keys=False)
    os.replace(tmp_path, path)
