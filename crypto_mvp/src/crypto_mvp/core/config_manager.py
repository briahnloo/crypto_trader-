"""
Configuration management for the Crypto MVP application.
"""

import os
from pathlib import Path
from typing import Any, Optional, TypeVar, Union

import yaml
from pydantic import BaseModel, Field, validator

from .config_schema import CryptoMVPConfig, validate_config_dict

T = TypeVar("T")


class ConfigManager:
    """Manages application configuration from YAML files and environment variables."""

    def __init__(
        self, config_path: Optional[Union[str, Path]] = None, validate: bool = True
    ):
        """Initialize the configuration manager.

        Args:
            config_path: Path to the configuration file. If None, uses default.
            validate: Whether to validate configuration against schema.
        """
        self.config_path = (
            Path(config_path) if config_path else self._get_default_config_path()
        )
        self._config: Optional[dict[str, Any]] = None
        self._validated_config: Optional[CryptoMVPConfig] = None
        self._load_config()

        if validate:
            self._validate_config()

    def _get_default_config_path(self) -> Path:
        """Get the default configuration file path."""
        return (
            Path(__file__).parent.parent.parent.parent
            / "config"
            / "profit_optimized.yaml"
        )

    def _load_config(self) -> None:
        """Load configuration from YAML file."""
        try:
            with open(self.config_path, encoding="utf-8") as file:
                self._config = yaml.safe_load(file) or {}
        except FileNotFoundError as e:
            raise FileNotFoundError(
                f"Configuration file not found: {self.config_path}"
            ) from e
        except yaml.YAMLError as e:
            raise ValueError(f"Invalid YAML configuration: {e}") from e

    def _validate_config(self) -> None:
        """Validate configuration against schema."""
        if self._config is None:
            raise ValueError("No configuration loaded")

        try:
            self._validated_config = validate_config_dict(self._config)
        except ValueError as e:
            raise ValueError(
                f"Configuration validation failed in {self.config_path}:\n{e}"
            ) from e

    def get(self, key: str, default: Any = None) -> Any:
        """Get a configuration value by key with dotted path support.

        Args:
            key: Configuration key (supports dot notation like 'trading.timeframe')
            default: Default value if key not found

        Returns:
            Configuration value or default

        Examples:
            >>> config.get('trading.timeframe')  # Returns '1h'
            >>> config.get('risk.max_drawdown')  # Returns 0.1
            >>> config.get('nonexistent.key', 'default')  # Returns 'default'
        """
        if self._config is None:
            return default

        keys = key.split(".")
        value = self._config

        try:
            for k in keys:
                if isinstance(value, dict) and k in value:
                    value = value[k]
                else:
                    return default
        except (KeyError, TypeError):
            return default

        # Replace environment variable placeholders
        if isinstance(value, str) and value.startswith("${") and value.endswith("}"):
            env_var = value[2:-1]
            return os.getenv(env_var, default)

        return value

    def get_section(self, section: str) -> dict[str, Any]:
        """Get an entire configuration section.

        Args:
            section: Section name (supports dot notation)

        Returns:
            Section configuration as dictionary
        """
        return self.get(section, {})

    def set(self, key: str, value: Any) -> None:
        """Set a configuration value with dotted path support.

        Args:
            key: Configuration key (supports dot notation)
            value: New value
        """
        if self._config is None:
            self._config = {}

        keys = key.split(".")
        config = self._config

        # Navigate to the parent of the target key
        for k in keys[:-1]:
            if k not in config:
                config[k] = {}
            elif not isinstance(config[k], dict):
                config[k] = {}
            config = config[k]

        # Set the final value
        config[keys[-1]] = value

    def update(self, key: str, value: Any) -> None:
        """Alias for set method for backward compatibility."""
        self.set(key, value)

    def save(self) -> None:
        """Save configuration to file."""
        if self._config is None:
            return

        with open(self.config_path, "w", encoding="utf-8") as file:
            yaml.dump(
                self._config, file, default_flow_style=False, indent=2, sort_keys=False
            )

    def reload(self) -> None:
        """Reload configuration from file."""
        self._load_config()

    def has(self, key: str) -> bool:
        """Check if a configuration key exists.

        Args:
            key: Configuration key (supports dot notation)

        Returns:
            True if key exists, False otherwise
        """
        if self._config is None:
            return False

        keys = key.split(".")
        value = self._config

        try:
            for k in keys:
                if isinstance(value, dict) and k in value:
                    value = value[k]
                else:
                    return False
            return True
        except (KeyError, TypeError):
            return False

    def keys(self, section: str = None) -> list[str]:
        """Get configuration keys.

        Args:
            section: Optional section to get keys from

        Returns:
            List of configuration keys
        """
        if section:
            config = self.get_section(section)
        else:
            config = self._config or {}

        if isinstance(config, dict):
            return list(config.keys())
        return []

    def to_dict(self) -> dict[str, Any]:
        """Convert configuration to dictionary.

        Returns:
            Configuration as dictionary
        """
        return self._config or {}

    def get_validated_config(self) -> CryptoMVPConfig:
        """Get the validated configuration object.

        Returns:
            Validated configuration object

        Raises:
            ValueError: If configuration is not validated
        """
        if self._validated_config is None:
            raise ValueError("Configuration has not been validated")
        return self._validated_config

    def is_validated(self) -> bool:
        """Check if configuration has been validated.

        Returns:
            True if configuration is validated, False otherwise
        """
        return self._validated_config is not None

    def get_schema(self) -> dict[str, Any]:
        """Get the configuration schema.

        Returns:
            JSON schema dictionary
        """
        from .config_schema import get_config_schema

        return get_config_schema()

    @property
    def config(self) -> dict[str, Any]:
        """Get the entire configuration dictionary."""
        return self._config or {}


class TradingConfig(BaseModel):
    """Trading configuration model."""

    default_symbol: str = Field(
        default="BTC/USDT", description="Default trading symbol"
    )
    default_timeframe: str = Field(default="1h", description="Default timeframe")
    max_position_size: float = Field(
        default=0.1, ge=0, le=1, description="Maximum position size"
    )
    max_daily_loss: float = Field(
        default=0.05, ge=0, le=1, description="Maximum daily loss"
    )
    risk_free_rate: float = Field(default=0.02, ge=0, description="Risk-free rate")

    @validator("max_position_size", "max_daily_loss")
    def validate_percentage(cls, v):
        """Validate that percentage values are between 0 and 1."""
        if not 0 <= v <= 1:
            raise ValueError("Value must be between 0 and 1")
        return v


class ExchangeConfig(BaseModel):
    """Exchange configuration model."""

    enabled: bool = Field(default=True, description="Whether exchange is enabled")
    api_key: str = Field(..., description="API key")
    secret: str = Field(..., description="API secret")
    sandbox: bool = Field(default=True, description="Use sandbox/testnet")
    rate_limit: int = Field(default=10, ge=1, description="Rate limit per second")

    @validator("api_key", "secret")
    def validate_credentials(cls, v):
        """Validate that credentials are not empty."""
        if not v or v.startswith("your_"):
            raise ValueError("API credentials must be set")
        return v


class RiskConfig(BaseModel):
    """Risk management configuration model."""

    max_drawdown: float = Field(default=0.1, ge=0, le=1, description="Maximum drawdown")
    stop_loss_pct: float = Field(
        default=0.02, ge=0, le=1, description="Stop loss percentage"
    )
    take_profit_pct: float = Field(
        default=0.04, ge=0, le=1, description="Take profit percentage"
    )
    max_open_positions: int = Field(
        default=5, ge=1, description="Maximum open positions"
    )
    position_sizing_method: str = Field(
        default="fixed", description="Position sizing method"
    )

    @validator("max_drawdown", "stop_loss_pct", "take_profit_pct")
    def validate_percentage(cls, v):
        """Validate that percentage values are between 0 and 1."""
        if not 0 <= v <= 1:
            raise ValueError("Value must be between 0 and 1")
        return v


class DataSourceConfig(BaseModel):
    """Data source configuration model."""

    enabled: bool = Field(default=True, description="Whether data source is enabled")
    api_key: Optional[str] = Field(default=None, description="API key if required")
    rate_limit: int = Field(default=60, ge=1, description="Rate limit per minute")
    timeout: int = Field(default=30, ge=1, description="Request timeout in seconds")


class LoggingConfig(BaseModel):
    """Logging configuration model."""

    level: str = Field(default="INFO", description="Log level")
    file: Optional[str] = Field(default=None, description="Log file path")
    rotation: str = Field(default="1 week", description="Log rotation period")
    retention: str = Field(default="1 month", description="Log retention period")
    format: str = Field(
        default="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        description="Log format",
    )


class ConfigValidator:
    """Validates configuration against expected schema."""

    @staticmethod
    def validate_trading_config(config: dict[str, Any]) -> bool:
        """Validate trading configuration section."""
        trading = config.get("trading", {})
        required_keys = ["timeframe", "symbols", "strategies"]
        return all(key in trading for key in required_keys)

    @staticmethod
    def validate_risk_config(config: dict[str, Any]) -> bool:
        """Validate risk management configuration section."""
        risk = config.get("risk", {})
        required_keys = ["max_drawdown", "stop_loss", "position_sizing"]
        return all(key in risk for key in required_keys)

    @staticmethod
    def validate_exchange_config(config: dict[str, Any]) -> bool:
        """Validate exchange configuration section."""
        exchanges = config.get("exchanges", {})
        if not exchanges:
            return False

        for exchange_name, exchange_config in exchanges.items():
            if not isinstance(exchange_config, dict):
                return False
            required_keys = ["enabled", "api_key", "secret", "sandbox"]
            if not all(key in exchange_config for key in required_keys):
                return False

        return True

    @staticmethod
    def validate_data_sources_config(config: dict[str, Any]) -> bool:
        """Validate data sources configuration section."""
        data_sources = config.get("data_sources", {})
        if not data_sources:
            return False

        for source_name, source_config in data_sources.items():
            if not isinstance(source_config, dict):
                return False
            if "enabled" not in source_config:
                return False

        return True

    @classmethod
    def validate_all(cls, config: dict[str, Any]) -> bool:
        """Validate entire configuration."""
        validators = [
            cls.validate_trading_config,
            cls.validate_risk_config,
            cls.validate_exchange_config,
            cls.validate_data_sources_config,
        ]
        return all(validator(config) for validator in validators)
