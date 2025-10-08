"""
Command-line interface for the crypto trading system.
"""

import argparse
import asyncio
import sys
from pathlib import Path
from typing import Optional

from ..core.config_manager import ConfigManager
from ..trading_system import ProfitMaximizingTradingSystem


def create_argument_parser() -> argparse.ArgumentParser:
    """Create and configure argument parser.

    Returns:
        Configured argument parser
    """
    parser = argparse.ArgumentParser(
        description="Crypto Trading System - Profit-Optimized Strategy",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    # Configuration
    parser.add_argument(
        "--config",
        type=str,
        default="config/profit_optimized.yaml",
        help="Path to configuration file (default: config/profit_optimized.yaml)",
    )

    # Session management
    parser.add_argument(
        "--session-id",
        type=str,
        help="Session ID for tracking trades (auto-generated if not provided)",
    )

    parser.add_argument(
        "--continue-session",
        action="store_true",
        help="Continue an existing session (default: start new session)",
    )

    parser.add_argument(
        "--override-session-capital",
        action="store_true",
        help="Override session capital with CLI capital (clears existing positions)",
    )

    # Trading parameters
    parser.add_argument(
        "--capital",
        type=float,
        help="Trading capital to use (overrides config if --override-session-capital set)",
    )

    parser.add_argument(
        "--symbols",
        type=str,
        nargs="+",
        help="List of symbols to trade (overrides config)",
    )

    parser.add_argument(
        "--strategy",
        type=str,
        help="Primary strategy to use (overrides config)",
    )

    # Execution mode
    parser.add_argument(
        "--live",
        action="store_true",
        help="Enable live trading mode (default: paper trading)",
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Dry run mode - no orders placed (default: False)",
    )

    parser.add_argument(
        "--include-existing",
        action="store_true",
        help="Include existing exchange positions (live mode only)",
    )

    # Cycle control
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run single trading cycle and exit (default: continuous)",
    )

    parser.add_argument(
        "--cycle-interval",
        type=int,
        help="Interval between cycles in seconds (overrides config)",
    )

    # Logging
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable verbose logging (default: False)",
    )

    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug logging (default: False)",
    )

    return parser


def validate_arguments(args: argparse.Namespace) -> None:
    """Validate parsed arguments.

    Args:
        args: Parsed arguments

    Raises:
        SystemExit: If validation fails
    """
    # Validate config file exists
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
                print(f"Error: Invalid symbol format: {symbol} (expected: BASE/QUOTE)")
                sys.exit(1)

    # Validate live mode restrictions
    if args.live and args.dry_run:
        print("Error: Cannot use --live and --dry-run together")
        sys.exit(1)

    # Validate session capital override
    if args.override_session_capital and args.capital is None:
        print("Error: --override-session-capital requires --capital to be set")
        sys.exit(1)


def check_dry_run_mode(args: argparse.Namespace) -> bool:
    """Check if dry run mode is active and display warning.

    Args:
        args: Parsed arguments

    Returns:
        True if dry run is active
    """
    if args.dry_run:
        print("\n" + "=" * 60)
        print("🔒 DRY RUN MODE ACTIVE - NO ORDERS WILL BE PLACED")
        print("=" * 60 + "\n")
        return True

    if not args.live:
        print("\n" + "=" * 60)
        print("📝 PAPER TRADING MODE - SIMULATED EXECUTION ONLY")
        print("=" * 60 + "\n")

    return False


def print_session_info(args: argparse.Namespace) -> None:
    """Print session configuration information.

    Args:
        args: Parsed arguments
    """
    print("\n" + "=" * 60)
    print("🚀 CRYPTO TRADING SYSTEM - SESSION INFO")
    print("=" * 60)
    print(f"📁 Config: {args.config}")
    print(f"💰 Mode: {'LIVE' if args.live else 'PAPER/SIMULATION'}")
    print(f"🔄 Cycles: {'Single cycle' if args.once else 'Continuous'}")

    if args.capital:
        if args.override_session_capital:
            print(f"💵 Capital: ${args.capital:,.2f} (OVERRIDE - clearing old positions)")
        else:
            print(f"💵 Capital: ${args.capital:,.2f} (will use session capital if available)")

    if args.symbols:
        print(f"📊 Symbols: {', '.join(args.symbols)}")

    if args.strategy:
        print(f"🎯 Strategy: {args.strategy}")

    if args.session_id:
        print(f"🆔 Session: {args.session_id}")
        if args.continue_session:
            print("   (continuing existing session)")

    print("=" * 60 + "\n")


def print_cycle_summary(cycle_results: dict) -> None:
    """Print trading cycle summary.

    Args:
        cycle_results: Cycle execution results
    """
    print("\n" + "=" * 40)
    print("📊 CYCLE SUMMARY")
    print("=" * 40)

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
        
        # CRITICAL FIX: Determine if we should override session capital
        should_override = args.override_session_capital or (args.capital is not None and not args.continue_session)
        
        if should_override:
            print(f"⚠️  CAPITAL OVERRIDE: Starting fresh with ${args.capital:,.2f}")
            print("   All existing positions will be cleared")
        
        # Now initialize with the updated config and session parameters
        trading_system.initialize(
            session_id=args.session_id,
            continue_session=args.continue_session,
            respect_session_capital=not should_override,  # Force False when overriding
            include_existing=args.include_existing
        )

        # CRITICAL FIX: DO NOT override portfolio cash/equity here!
        # The initialize() method already handles capital correctly
        # when respect_session_capital=False. Overriding here creates phantom equity!

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
        
        # Override config with CLI arguments
        if args.capital:
            trading_system.config["trading"]["initial_capital"] = args.capital
        
        # CRITICAL FIX: Determine if we should override session capital
        should_override = args.override_session_capital or (args.capital is not None and not args.continue_session)
        
        if should_override:
            print(f"⚠️  CAPITAL OVERRIDE: Starting fresh with ${args.capital:,.2f}")
            print("   All existing positions will be cleared")
        
        trading_system.initialize(
            session_id=args.session_id,
            continue_session=args.continue_session,
            respect_session_capital=not should_override,
            include_existing=args.include_existing
        )

        # CRITICAL FIX: DO NOT override portfolio here!
        
        if args.symbols:
            trading_system.config["trading"]["symbols"] = args.symbols

        if args.strategy:
            trading_system.config["trading"]["primary_strategy"] = args.strategy

        if args.cycle_interval:
            trading_system.config["trading"]["cycle_interval"] = args.cycle_interval

        trading_system.config["trading"]["live_mode"] = args.live
        trading_system.config["trading"]["dry_run"] = args.dry_run

        print("✅ System initialized, starting continuous trading...")
        print("   Press Ctrl+C to stop gracefully\n")

        # CRITICAL FIX: Use correct method name
        await trading_system.run()  # Not run_continuous()!

    except KeyboardInterrupt:
        print("\n\n⚠️  Received interrupt signal, shutting down gracefully...")
        print("✅ System stopped successfully")
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

    # Print session info
    print_session_info(args)

    # Confirm live trading if enabled
    if args.live and not dry_run_active:
        response = input("⚠️  LIVE TRADING MODE - Real money will be used. Continue? (yes/no): ")
        if response.lower() not in ["yes", "y"]:
            print("❌ Aborted by user")
            sys.exit(0)

    # Run trading
    try:
        if args.once:
            asyncio.run(run_single_cycle(args))
        else:
            asyncio.run(run_continuous(args))
    except KeyboardInterrupt:
        print("\n\n⚠️  Interrupted by user")
        sys.exit(0)
    except Exception as e:
        print(f"\n❌ Fatal error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
