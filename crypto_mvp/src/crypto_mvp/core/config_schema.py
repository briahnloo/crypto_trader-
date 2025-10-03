"""
Configuration schema and validation for the Crypto MVP application.
"""

from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field, field_validator, model_validator


class TimeFrame(str, Enum):
    """Supported timeframes."""

    MINUTE_1 = "1m"
    MINUTE_5 = "5m"
    MINUTE_15 = "15m"
    MINUTE_30 = "30m"
    HOUR_1 = "1h"
    HOUR_4 = "4h"
    HOUR_12 = "12h"
    DAY_1 = "1d"
    WEEK_1 = "1w"


class StrategyType(str, Enum):
    """Supported strategy types."""

    MOMENTUM = "momentum"
    BREAKOUT = "breakout"
    MEAN_REVERSION = "mean_reversion"
    ARBITRAGE = "arbitrage"
    SENTIMENT = "sentiment"
    VOLATILITY = "volatility"
    CORRELATION = "correlation"
    WHALE_TRACKING = "whale_tracking"
    NEWS_DRIVEN = "news_driven"
    ON_CHAIN = "on_chain"
    COMPOSITE = "composite"


class PositionSizingMethod(str, Enum):
    """Position sizing methods."""

    FIXED_RISK = "fixed_risk"
    FIXED_SIZE = "fixed_size"
    KELLY_CRITERION = "kelly_criterion"


class ExchangeConfig(BaseModel):
    """Exchange configuration schema."""

    enabled: bool = Field(default=False, description="Whether the exchange is enabled")
    api_key: Optional[str] = Field(default=None, description="API key")
    secret: Optional[str] = Field(default=None, description="Secret key")
    sandbox: bool = Field(default=True, description="Use sandbox/testnet mode")
    rate_limit: float = Field(
        default=1.0, ge=0.1, le=100.0, description="Rate limit (calls per second)"
    )
    timeout: int = Field(
        default=30, ge=5, le=300, description="Request timeout in seconds"
    )
    symbols: list[str] = Field(default_factory=list, description="Supported symbols")

    @field_validator("api_key", "secret")
    @classmethod
    def validate_api_credentials(cls, v):
        """Validate API credentials."""
        if v and v in ["your_api_key_here", "your_secret_key_here", ""]:
            return None
        return v

    @field_validator("symbols")
    @classmethod
    def validate_symbols(cls, v):
        """Validate symbol format."""
        for symbol in v:
            if "/" not in symbol and "-" not in symbol:
                raise ValueError(
                    f"Invalid symbol format: {symbol}. Use format like 'BTC/USDT' or 'BTC-USD'"
                )
        return v


class PositionSizingConfig(BaseModel):
    """Position sizing configuration schema."""

    method: PositionSizingMethod = Field(
        default=PositionSizingMethod.FIXED_RISK, description="Position sizing method"
    )
    risk_per_trade: float = Field(
        default=0.01, ge=0.001, le=0.1, description="Risk per trade (1% = 0.01)"
    )
    max_position_size: float = Field(
        default=0.1, ge=0.01, le=1.0, description="Maximum position size (10% = 0.1)"
    )

    @field_validator("risk_per_trade")
    @classmethod
    def validate_risk_per_trade(cls, v):
        """Validate risk per trade."""
        if v > 0.05:  # 5%
            raise ValueError(
                f"Risk per trade ({v:.1%}) is too high. Consider reducing to ≤5% for safety."
            )
        return v


class RiskConfig(BaseModel):
    """Risk management configuration schema."""

    max_drawdown: float = Field(
        default=0.1, ge=0.01, le=0.5, description="Maximum drawdown (10% = 0.1)"
    )
    stop_loss: float = Field(
        default=0.02, ge=0.001, le=0.1, description="Stop loss percentage (2% = 0.02)"
    )
    take_profit: float = Field(
        default=0.04, ge=0.001, le=0.5, description="Take profit percentage (4% = 0.04)"
    )
    position_sizing: PositionSizingConfig = Field(
        default_factory=PositionSizingConfig,
        description="Position sizing configuration",
    )
    daily_loss_limit: float = Field(
        default=0.03, ge=0.01, le=0.2, description="Daily loss limit (3% = 0.03)"
    )
    max_correlation: float = Field(
        default=0.7, ge=0.1, le=1.0, description="Maximum correlation between positions"
    )
    volatility_adjustment: bool = Field(
        default=True, description="Enable volatility adjustment"
    )
    dynamic_sizing: bool = Field(
        default=True, description="Enable dynamic position sizing"
    )

    @field_validator("take_profit")
    @classmethod
    def validate_take_profit_vs_stop_loss(cls, v, info):
        """Validate take profit vs stop loss ratio."""
        if (
            hasattr(info, "data")
            and "stop_loss" in info.data
            and v <= info.data["stop_loss"]
        ):
            raise ValueError(
                f"Take profit ({v:.1%}) should be greater than stop loss ({info.data['stop_loss']:.1%})"
            )
        return v

    @field_validator("daily_loss_limit")
    @classmethod
    def validate_daily_loss_limit(cls, v):
        """Validate daily loss limit."""
        if v > 0.1:  # 10%
            raise ValueError(
                f"Daily loss limit ({v:.1%}) is too high. Consider reducing to ≤10% for safety."
            )
        return v


class TradingConfig(BaseModel):
    """Trading configuration schema."""

    timeframe: TimeFrame = Field(
        default=TimeFrame.HOUR_1, description="Trading timeframe"
    )
    symbols: list[str] = Field(default_factory=list, description="Trading symbols")
    strategies: Optional[list[StrategyType]] = Field(
        default=None, description="Enabled strategies"
    )
    max_open_trades: int = Field(
        default=5, ge=1, le=50, description="Maximum open trades"
    )
    min_trade_interval: int = Field(
        default=300, ge=60, le=3600, description="Minimum trade interval in seconds"
    )
    trade_timeout: int = Field(
        default=3600, ge=300, le=86400, description="Trade timeout in seconds"
    )
    initial_capital: float = Field(
        default=10000.0, ge=100.0, le=10000000.0, description="Initial capital"
    )
    live_mode: bool = Field(default=False, description="Live trading mode")
    dry_run: bool = Field(
        default=False, description="Dry run mode (prevents live trading)"
    )
    primary_strategy: Optional[StrategyType] = Field(
        default=None, description="Primary strategy"
    )
    cycle_interval: int = Field(
        default=300, ge=60, le=3600, description="Trading cycle interval in seconds"
    )

    @field_validator("symbols")
    @classmethod
    def validate_symbols(cls, v):
        """Validate symbol format."""
        for symbol in v:
            if "/" not in symbol and "-" not in symbol:
                raise ValueError(
                    f"Invalid symbol format: {symbol}. Use format like 'BTC/USDT' or 'BTC-USD'"
                )
        return v

    @field_validator("strategies")
    @classmethod
    def validate_strategies(cls, v):
        """Validate strategies."""
        if v is not None and not v:
            raise ValueError("At least one strategy must be enabled")
        return v

    @field_validator("primary_strategy")
    @classmethod
    def validate_primary_strategy(cls, v, info):
        """Validate primary strategy is in enabled strategies."""
        if (
            v
            and hasattr(info, "data")
            and "strategies" in info.data
            and v not in info.data["strategies"]
        ):
            raise ValueError(
                f"Primary strategy '{v}' must be in enabled strategies: {info.data['strategies']}"
            )
        return v


class DataSourceConfig(BaseModel):
    """Data source configuration schema."""

    enabled: bool = Field(
        default=True, description="Whether the data source is enabled"
    )
    update_interval: int = Field(
        default=60, ge=10, le=3600, description="Update interval in seconds"
    )
    api_keys: dict[str, str] = Field(
        default_factory=dict, description="API keys for the data source"
    )

    @field_validator("api_keys")
    @classmethod
    def validate_api_keys(cls, v):
        """Validate API keys."""
        for key_name, key_value in v.items():
            if key_value and key_value in ["your_api_key_here", ""]:
                v[key_name] = None
        return v


class MarketDataConfig(BaseModel):
    """Market data configuration schema."""

    enabled: bool = Field(default=True, description="Whether market data is enabled")
    sources: list[str] = Field(default_factory=list, description="Data sources")
    historical_days: int = Field(
        default=30, ge=1, le=365, description="Historical data days"
    )
    update_interval: int = Field(
        default=60, ge=10, le=3600, description="Update interval in seconds"
    )


class SentimentConfig(BaseModel):
    """Sentiment data configuration schema."""

    enabled: bool = Field(default=True, description="Whether sentiment data is enabled")
    sources: dict[str, DataSourceConfig] = Field(
        default_factory=dict, description="Sentiment data sources"
    )


class OnChainConfig(BaseModel):
    """On-chain data configuration schema."""

    enabled: bool = Field(default=True, description="Whether on-chain data is enabled")
    sources: list[str] = Field(
        default_factory=list, description="On-chain data sources"
    )
    api_keys: dict[str, str] = Field(
        default_factory=dict, description="API keys for on-chain sources"
    )
    min_whale_value: float = Field(
        default=1000000.0,
        ge=10000.0,
        le=100000000.0,
        description="Minimum whale transaction value",
    )

    @field_validator("api_keys")
    @classmethod
    def validate_api_keys(cls, v):
        """Validate API keys."""
        for key_name, key_value in v.items():
            if key_value and key_value in ["your_api_key_here", ""]:
                v[key_name] = None
        return v


class DataSourcesConfig(BaseModel):
    """Data sources configuration schema."""

    market_data: MarketDataConfig = Field(
        default_factory=MarketDataConfig, description="Market data configuration"
    )
    sentiment: SentimentConfig = Field(
        default_factory=SentimentConfig, description="Sentiment data configuration"
    )
    on_chain: OnChainConfig = Field(
        default_factory=OnChainConfig, description="On-chain data configuration"
    )


class TechnicalIndicatorsConfig(BaseModel):
    """Technical indicators configuration schema."""

    enabled: bool = Field(
        default=True, description="Whether technical indicators are enabled"
    )
    indicators: list[str] = Field(
        default_factory=list, description="Enabled indicators"
    )
    lookback_periods: int = Field(
        default=100, ge=10, le=1000, description="Lookback periods for indicators"
    )


class SignalsConfig(BaseModel):
    """Signals configuration schema."""

    enabled: bool = Field(
        default=True, description="Whether signal generation is enabled"
    )
    confidence_threshold: float = Field(
        default=0.6, ge=0.1, le=1.0, description="Minimum confidence threshold"
    )
    signal_timeout: int = Field(
        default=300, ge=60, le=1800, description="Signal timeout in seconds"
    )
    composite_weighting: dict[str, float] = Field(
        default_factory=dict, description="Strategy weights for composite signals"
    )

    @field_validator("composite_weighting")
    @classmethod
    def validate_composite_weighting(cls, v):
        """Validate composite weighting sums to 1.0."""
        if v:
            total_weight = sum(v.values())
            if abs(total_weight - 1.0) > 0.01:  # Allow small floating point errors
                raise ValueError(
                    f"Composite weighting must sum to 1.0, got {total_weight:.3f}"
                )
        return v


class LoggingConfig(BaseModel):
    """Logging configuration schema."""

    level: str = Field(default="INFO", description="Logging level")
    console_output: bool = Field(default=True, description="Enable console output")
    file_output: bool = Field(default=True, description="Enable file output")
    file_path: str = Field(default="logs/crypto_mvp.log", description="Log file path")
    max_file_size: str = Field(default="10MB", description="Maximum log file size")
    backup_count: int = Field(
        default=5, ge=1, le=20, description="Number of backup log files"
    )
    emoji_enabled: bool = Field(default=True, description="Enable emoji in logs")

    @field_validator("level")
    @classmethod
    def validate_log_level(cls, v):
        """Validate log level."""
        valid_levels = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
        if v.upper() not in valid_levels:
            raise ValueError(f"Invalid log level: {v}. Must be one of: {valid_levels}")
        return v.upper()


class DatabaseConfig(BaseModel):
    """Database configuration schema."""

    enabled: bool = Field(default=True, description="Whether database is enabled")
    url: str = Field(default="sqlite:///crypto_mvp.db", description="Database URL")
    echo: bool = Field(default=False, description="Enable SQL echo")
    pool_size: int = Field(default=10, ge=1, le=100, description="Connection pool size")
    max_overflow: int = Field(
        default=20, ge=0, le=100, description="Maximum overflow connections"
    )
    tables: dict[str, bool] = Field(
        default_factory=dict, description="Table configuration"
    )


class DevelopmentConfig(BaseModel):
    """Development configuration schema."""

    debug: bool = Field(default=False, description="Enable debug mode")
    paper_trading: bool = Field(default=True, description="Enable paper trading")
    dry_run: bool = Field(default=False, description="Enable dry run mode")
    simulation: dict[str, Any] = Field(
        default_factory=dict, description="Simulation configuration"
    )
    backtesting: dict[str, Any] = Field(
        default_factory=dict, description="Backtesting configuration"
    )


class CryptoMVPConfig(BaseModel):
    """Main configuration schema for Crypto MVP."""

    trading: TradingConfig = Field(
        default_factory=TradingConfig, description="Trading configuration"
    )
    risk: RiskConfig = Field(
        default_factory=RiskConfig, description="Risk management configuration"
    )
    exchanges: dict[str, ExchangeConfig] = Field(
        default_factory=dict, description="Exchange configurations"
    )
    data_sources: DataSourcesConfig = Field(
        default_factory=DataSourcesConfig, description="Data sources configuration"
    )
    technical_indicators: TechnicalIndicatorsConfig = Field(
        default_factory=TechnicalIndicatorsConfig,
        description="Technical indicators configuration",
    )
    signals: SignalsConfig = Field(
        default_factory=SignalsConfig, description="Signals configuration"
    )
    logging: LoggingConfig = Field(
        default_factory=LoggingConfig, description="Logging configuration"
    )
    database: DatabaseConfig = Field(
        default_factory=DatabaseConfig, description="Database configuration"
    )
    development: DevelopmentConfig = Field(
        default_factory=DevelopmentConfig, description="Development configuration"
    )

    @model_validator(mode="after")
    def validate_config_consistency(self):
        """Validate overall configuration consistency."""
        # Check if live mode is enabled but no exchanges are configured
        if self.trading.live_mode:
            enabled_exchanges = [
                name for name, config in self.exchanges.items() if config.enabled
            ]
            if not enabled_exchanges:
                raise ValueError("Live mode requires at least one enabled exchange")

        # Check if symbols are supported by enabled exchanges
        if self.trading.symbols:
            supported_symbols = set()
            for exchange_config in self.exchanges.values():
                if exchange_config.enabled:
                    supported_symbols.update(exchange_config.symbols)

            if supported_symbols:
                unsupported_symbols = set(self.trading.symbols) - supported_symbols
                if unsupported_symbols:
                    raise ValueError(
                        f"Symbols not supported by any enabled exchange: {list(unsupported_symbols)}"
                    )

        return self

    model_config = {
        "use_enum_values": True,
        "validate_assignment": True,
        "extra": "allow",  # Allow extra fields for flexibility
    }


def validate_config_dict(config_dict: dict[str, Any]) -> CryptoMVPConfig:
    """
    Validate a configuration dictionary against the schema.

    Args:
        config_dict: Configuration dictionary to validate

    Returns:
        Validated configuration object

    Raises:
        ValidationError: If configuration is invalid
    """
    try:
        return CryptoMVPConfig(**config_dict)
    except Exception as e:
        # Provide more helpful error messages
        if hasattr(e, "errors"):
            error_messages = []
            for error in e.errors():
                field_path = " -> ".join(str(x) for x in error["loc"])
                error_msg = error["msg"]
                error_messages.append(f"  • {field_path}: {error_msg}")

            raise ValueError(
                "Configuration validation failed:\n" + "\n".join(error_messages)
            ) from e
        else:
            raise ValueError(f"Configuration validation failed: {e}") from e


def get_config_schema() -> dict[str, Any]:
    """
    Get the JSON schema for the configuration.

    Returns:
        JSON schema dictionary
    """
    return CryptoMVPConfig.model_json_schema()
