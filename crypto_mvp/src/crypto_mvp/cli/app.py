"""
Command-line interface for the Crypto MVP trading system.
"""

import argparse
import asyncio
import sys
from pathlib import Path

from ..core.config_manager import ConfigManager
from ..core.logging_utils import get_logger
from ..trading_system import ProfitMaximizingTradingSystem


def create_argument_parser() -> argparse.ArgumentParser:
    """Create and configure the argument parser.

    Returns:
        Configured ArgumentParser instance
    """
    parser = argparse.ArgumentParser(
        description="Crypto MVP - Profit-Maximizing Trading System",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Run with default config
  python -m crypto_mvp

  # Run with custom config and capital
  python -m crypto_mvp --config config/profit_optimized.yaml --capital 10000

  # Run in live mode with specific symbols
  python -m crypto_mvp --live --symbols BTC/USDT ETH/USDT --capital 50000

  # Run single cycle for testing
  python -m crypto_mvp --once --config config/profit_optimized.yaml

  # Run with specific strategy
  python -m crypto_mvp --strategy momentum --capital 25000
        """,
    )

    # Configuration options
    parser.add_argument(
        "--config",
        type=str,
        default="config/profit_optimized.yaml",
        help="Path to configuration file (default: config/profit_optimized.yaml)",
    )

    # Trading mode options
    parser.add_argument(
        "--live",
        action="store_true",
        help="Run in live trading mode (default: paper/simulation mode). Requires API keys and explicit confirmation.",
    )

    parser.add_argument(
        "--once",
        action="store_true",
        help="Run exactly one trading cycle and exit (useful for testing)",
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Force dry run mode (prevents live trading even with --live flag, useful for staging)",
    )

    # Trading parameters
    parser.add_argument(
        "--capital", type=float, help="Initial capital amount (overrides config file)"
    )

    parser.add_argument(
        "--symbols", nargs="+", help="Trading symbols (e.g., BTC/USDT ETH/USDT)"
    )

    parser.add_argument(
        "--strategy",
        type=str,
        choices=[
            "momentum",
            "breakout",
            "mean_reversion",
            "arbitrage",
            "sentiment",
            "composite",
        ],
        help="Primary trading strategy to use",
    )

    # System options
    parser.add_argument(
        "--log-level",
        type=str,
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        default="INFO",
        help="Logging level (default: INFO)",
    )

    parser.add_argument(
        "--no-emoji", action="store_true", help="Disable emoji output in logs"
    )

    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress console output (logs only to file)",
    )

    # Advanced options
    parser.add_argument(
        "--max-cycles",
        type=int,
        help="Maximum number of trading cycles to run (default: unlimited)",
    )

    parser.add_argument(
        "--cycle-interval",
        type=int,
        help="Interval between trading cycles in seconds (default: from config)",
    )

    # Session management options
    parser.add_argument(
        "--session-id",
        type=str,
        help="Session identifier for state persistence (default: auto-generated timestamp-rand)",
    )

    parser.add_argument(
        "--continue-session",
        action="store_true",
        default=False,
        help="Continue an existing session instead of starting fresh (requires --session-id)",
    )

    parser.add_argument(
        "--override-session-capital",
        action="store_true",
        default=False,
        help="Override session capital with --capital value (default: False). When True, --capital overrides session state.",
    )

    parser.add_argument(
        "--include-existing",
        action="store_true",
        default=False,
        help="Include existing positions from exchange in live mode (default: False). Reduces session cash by market value of existing positions.",
    )

    return parser


def validate_arguments(args: argparse.Namespace) -> None:
    """Validate command-line arguments.

    Args:
        args: Parsed arguments

    Raises:
        SystemExit: If validation fails
    """
    # Validate config file
    config_path = Path(args.config)
    if not config_path.exists():
        print(f"Error: Configuration file not found: {args.config}")
        sys.exit(1)

    # Validate capital
    if args.capital is not None and args.capital <= 0:
        print("Error: Capital must be positive")
        sys.exit(1)

    # Validate symbols format
    if args.symbols:
        for symbol in args.symbols:
            if "/" not in symbol:
                print(
                    f"Error: Invalid symbol format '{symbol}'. Use format like 'BTC/USDT'"
                )
                sys.exit(1)

    # Validate session arguments
    if args.continue_session and not args.session_id:
        print("Error: --continue-session requires --session-id to be specified")
        sys.exit(1)


def validate_live_mode_safety(args: argparse.Namespace) -> None:
    """
    Validate safety requirements for live trading mode.

    Args:
        args: Parsed arguments

    Raises:
        SystemExit: If safety validation fails
    """
    if not args.live:
        return  # No validation needed for paper trading

    print("🔒 LIVE TRADING MODE SAFETY CHECKS")
    print("=" * 50)

    # Load configuration
    try:
        config_manager = ConfigManager(args.config)
        config = config_manager.to_dict()
    except Exception as e:
        print(f"❌ Failed to load configuration: {e}")
        sys.exit(1)

    # Check for dry run override
    if args.dry_run:
        print("🛡️  DRY RUN MODE ENABLED: Live trading is disabled")
        print("   This prevents live trading even with --live flag")
        return

    # Check API keys
    missing_keys = []

    # Check exchange API keys
    exchanges = config.get("exchanges", {})
    for exchange_name, exchange_config in exchanges.items():
        if exchange_config.get("enabled", False):
            api_key = exchange_config.get("api_key")
            secret = exchange_config.get("secret")

            if not api_key or api_key in ["your_api_key_here", ""]:
                missing_keys.append(f"Exchange {exchange_name}: API key")

            if not secret or secret in ["your_secret_key_here", ""]:
                missing_keys.append(f"Exchange {exchange_name}: Secret key")

    if missing_keys:
        print("❌ MISSING API KEYS FOR LIVE TRADING:")
        for key in missing_keys:
            print(f"   • {key}")
        print("\n💡 To enable live trading:")
        print("   1. Add your API keys to the configuration file")
        print("   2. Ensure keys are valid and have trading permissions")
        print("   3. Test with paper trading first")
        sys.exit(1)

    # Require explicit confirmation
    print("⚠️  LIVE TRADING MODE DETECTED")
    print("   This will place REAL trades with REAL money!")
    print("   Make sure you understand the risks involved.")
    print()

    confirmation = input("Type 'CONFIRM' to proceed with live trading: ").strip()

    if confirmation != "CONFIRM":
        print("❌ Live trading cancelled. Use paper trading mode for testing.")
        sys.exit(1)

    print("✅ Live trading mode confirmed")
    print("🚀 Proceeding with live trading...")


def check_dry_run_mode(args: argparse.Namespace) -> bool:
    """
    Check if dry run mode should be enforced.

    Args:
        args: Parsed arguments

    Returns:
        True if dry run mode is active
    """
    if args.dry_run:
        print("🛡️  DRY RUN MODE: All trading will be simulated")
        return True

    # Check config for dry run setting
    try:
        config_manager = ConfigManager(args.config)
        config = config_manager.to_dict()

        if config.get("development", {}).get("dry_run", False):
            print("🛡️  DRY RUN MODE (from config): All trading will be simulated")
            return True
    except Exception:
        pass  # Ignore config errors, use defaults

    return False

    # Validate cycle interval
    if args.cycle_interval is not None and args.cycle_interval <= 0:
        print("Error: Cycle interval must be positive")
        sys.exit(1)


def print_startup_info(args: argparse.Namespace) -> None:
    """Print startup information.

    Args:
        args: Parsed arguments
    """
    print("🚀 Crypto MVP - Profit-Maximizing Trading System")
    print("=" * 60)
    print(f"📁 Config: {args.config}")
    print(f"💰 Mode: {'LIVE' if args.live else 'PAPER/SIMULATION'}")
    print(f"🔄 Cycles: {'Single cycle' if args.once else 'Continuous'}")

    if args.capital:
        print(f"💵 Capital: ${args.capital:,.2f}")

    if args.symbols:
        print(f"📊 Symbols: {', '.join(args.symbols)}")

    if args.strategy:
        print(f"🎯 Strategy: {args.strategy}")

    if args.max_cycles:
        print(f"🔢 Max Cycles: {args.max_cycles}")

    if args.cycle_interval:
        print(f"⏱️  Cycle Interval: {args.cycle_interval}s")

    # Session information
    if args.session_id:
        print(f"🆔 Session ID: {args.session_id}")
        print(f"🔄 Session Mode: {'Continue' if args.continue_session else 'New'}")
    else:
        print(f"🆔 Session ID: Auto-generated")

    print("=" * 60)


def print_cycle_summary(cycle_results: dict) -> None:
    """Print trading cycle summary.

    Args:
        cycle_results: Results from trading cycle
    """
    print("\n📊 Trading Cycle Summary")
    print("=" * 40)
    print(f"🆔 Cycle ID: {cycle_results.get('cycle_id', 'unknown')}")
    print(f"⏱️  Duration: {cycle_results.get('duration', 0):.2f}s")

    # Market data summary
    market_data = cycle_results.get("market_data", {})
    symbols = market_data.get("symbols", [])
    print(f"📈 Symbols Analyzed: {len(symbols)}")

    # Signals summary
    signals = cycle_results.get("signals", {})
    print(f"🎯 Signals Generated: {len(signals)}")

    # Execution summary
    execution = cycle_results.get("execution_results", {})
    trades_executed = execution.get("trades_executed", 0)
    total_pnl = execution.get("total_pnl", 0.0)
    total_fees = execution.get("total_fees", 0.0)

    print(f"💼 Trades Executed: {trades_executed}")
    print(f"💰 Total P&L: ${total_pnl:.2f}")
    print(f"💸 Total Fees: ${total_fees:.2f}")

    # Portfolio summary
    portfolio = cycle_results.get("portfolio_snapshot", {})
    total_equity = portfolio.get("total_equity", 0.0)
    cash_balance = portfolio.get("cash_balance", 0.0)
    active_positions = portfolio.get("active_positions", 0)
    available_capital = portfolio.get("available_capital", 0.0)

    print(f"💎 Total Equity: ${total_equity:,.2f}")
    print(f"💵 Cash Balance: ${cash_balance:,.2f}")
    print(f"📋 Active Positions: {active_positions}")
    print(f"🔄 Available Capital: ${available_capital:,.2f}")

    # Errors
    errors = cycle_results.get("errors", [])
    if errors:
        print(f"⚠️  Errors: {len(errors)}")
        for error in errors:
            print(f"   • {error}")
    else:
        print("✅ No errors")

    print("=" * 40)


async def run_single_cycle(args: argparse.Namespace) -> None:
    """Run a single trading cycle.

    Args:
        args: Parsed arguments
    """
    print("🔄 Running single trading cycle...")

    try:
        # Generate session_id if not provided
        if not args.session_id:
            from datetime import datetime
            import random
            timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            random_suffix = f"{random.randint(1000, 9999)}"
            args.session_id = f"{timestamp}-{random_suffix}"
            print(f"🆕 Generated session ID: {args.session_id}")
        
        # Initialize trading system
        trading_system = ProfitMaximizingTradingSystem(args.config)
        
        # Load config first
        trading_system.config_manager = ConfigManager(args.config)
        trading_system.config = trading_system.config_manager.to_dict()
        
        # Override config with CLI arguments BEFORE full initialization
        if args.capital:
            trading_system.config["trading"]["initial_capital"] = args.capital
        
        # Now initialize with the updated config and session parameters
        trading_system.initialize(
            session_id=args.session_id,
            continue_session=args.continue_session,
            respect_session_capital=not args.override_session_capital,
            include_existing=args.include_existing
        )

        # Update in-memory portfolio after initialization
        if args.capital:
            trading_system.portfolio["equity"] = args.capital
            trading_system.portfolio["cash_balance"] = args.capital

        if args.symbols:
            trading_system.config["trading"]["symbols"] = args.symbols

        if args.strategy:
            trading_system.config["trading"]["primary_strategy"] = args.strategy

        if args.cycle_interval:
            trading_system.config["trading"]["cycle_interval"] = args.cycle_interval

        # Set live mode and dry run flags
        trading_system.config["trading"]["live_mode"] = args.live
        trading_system.config["trading"]["dry_run"] = args.dry_run

        # Run single cycle
        cycle_results = await trading_system.run_trading_cycle()

        # Print summary
        print_cycle_summary(cycle_results)

        print("\n✅ Single cycle completed successfully!")

    except Exception as e:
        print(f"\n❌ Error running single cycle: {e}")
        sys.exit(1)


async def run_continuous(args: argparse.Namespace) -> None:
    """Run continuous trading cycles.

    Args:
        args: Parsed arguments
    """
    print("🔄 Starting continuous trading...")

    try:
        # Generate session_id if not provided
        if not args.session_id:
            from datetime import datetime
            import random
            timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            random_suffix = f"{random.randint(1000, 9999)}"
            args.session_id = f"{timestamp}-{random_suffix}"
            print(f"🆕 Generated session ID: {args.session_id}")
        
        # Initialize trading system
        trading_system = ProfitMaximizingTradingSystem(args.config)
        
        # Load config first
        trading_system.config_manager = ConfigManager(args.config)
        trading_system.config = trading_system.config_manager.to_dict()
        
        # Override config with CLI arguments BEFORE full initialization
        if args.capital:
            trading_system.config["trading"]["initial_capital"] = args.capital
        
        # Now initialize with the updated config and session parameters
        trading_system.initialize(
            session_id=args.session_id,
            continue_session=args.continue_session,
            respect_session_capital=not args.override_session_capital,
            include_existing=args.include_existing
        )

        # Update in-memory portfolio after initialization
        if args.capital:
            trading_system.portfolio["equity"] = args.capital
            trading_system.portfolio["cash_balance"] = args.capital

        if args.symbols:
            trading_system.config["trading"]["symbols"] = args.symbols

        if args.strategy:
            trading_system.config["trading"]["primary_strategy"] = args.strategy

        if args.cycle_interval:
            trading_system.config["trading"]["cycle_interval"] = args.cycle_interval

        # Set live mode and dry run flags
        trading_system.config["trading"]["live_mode"] = args.live
        trading_system.config["trading"]["dry_run"] = args.dry_run

        # Run continuous trading
        await trading_system.run(max_cycles=args.max_cycles)

    except KeyboardInterrupt:
        print("\n⏹️  Trading stopped by user")
    except Exception as e:
        print(f"\n❌ Error in continuous trading: {e}")
        sys.exit(1)


def main() -> None:
    """Main CLI entry point."""
    # Parse arguments
    parser = create_argument_parser()
    args = parser.parse_args()

    # Validate arguments
    validate_arguments(args)

    # Check dry run mode
    dry_run_active = check_dry_run_mode(args)

    # Validate live mode safety
    validate_live_mode_safety(args)

    # Print startup info
    print_startup_info(args)

    # Configure logging
    logger_config = {
        "level": args.log_level,
        "console_output": not args.quiet,
        "emoji_enabled": not args.no_emoji,
    }

    # Set up logging
    logger = get_logger("crypto_mvp", logger_config)
    logger.info("Starting Crypto MVP trading system")

    # Run appropriate mode
    if args.once:
        asyncio.run(run_single_cycle(args))
    else:
        asyncio.run(run_continuous(args))


if __name__ == "__main__":
    main()
