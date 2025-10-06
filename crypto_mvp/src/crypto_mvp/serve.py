"""
FastAPI server for exposing trading system metrics and health checks.
"""

import asyncio
import threading
import time
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel

from .core.logging_utils import get_logger
from .metrics import MetricsCollector


class HealthResponse(BaseModel):
    """Health check response model."""

    status: str
    timestamp: float
    uptime: float
    version: str = "0.1.0"


class MetricsServer:
    """FastAPI server for exposing trading metrics."""

    def __init__(self, host: str = "localhost", port: int = 8000):
        """Initialize the metrics server.

        Args:
            host: Server host address
            port: Server port
        """
        self.host = host
        self.port = port
        self.metrics_collector: Optional[MetricsCollector] = None
        self.app: Optional[FastAPI] = None
        self.server_task: Optional[asyncio.Task] = None
        self.logger = get_logger("metrics_server")
        self._start_time = time.time()

    def set_metrics_collector(self, metrics_collector: MetricsCollector) -> None:
        """Set the metrics collector instance.

        Args:
            metrics_collector: MetricsCollector instance
        """
        self.metrics_collector = metrics_collector

    def create_app(self) -> FastAPI:
        """Create and configure the FastAPI application.

        Returns:
            Configured FastAPI application
        """

        @asynccontextmanager
        async def lifespan(app: FastAPI):
            """Application lifespan manager."""
            self.logger.info(f"Starting metrics server on {self.host}:{self.port}")
            yield
            self.logger.info("Shutting down metrics server")

        app = FastAPI(
            title="Crypto MVP Metrics Server",
            description="Metrics and health endpoints for the Crypto MVP trading system",
            version="0.1.0",
            lifespan=lifespan,
        )

        @app.get("/", response_class=PlainTextResponse)
        async def root():
            """Root endpoint with basic information."""
            return """Crypto MVP Metrics Server
=======================

Available endpoints:
- /health - Health check
- /metrics - Prometheus metrics
- /status - System status
- /docs - API documentation

Version: 0.1.0
"""

        @app.get("/health", response_model=HealthResponse)
        async def health_check():
            """Health check endpoint."""
            uptime = time.time() - self._start_time
            return HealthResponse(
                status="healthy", timestamp=time.time(), uptime=uptime
            )

        @app.get("/metrics", response_class=PlainTextResponse)
        async def get_metrics():
            """Get Prometheus-style metrics."""
            if not self.metrics_collector:
                raise HTTPException(
                    status_code=503, detail="Metrics collector not available"
                )

            try:
                metrics = self.metrics_collector.get_prometheus_metrics()
                return metrics
            except Exception as e:
                self.logger.error(f"Error getting metrics: {e}")
                raise HTTPException(
                    status_code=500, detail=f"Error retrieving metrics: {str(e)}"
                )

        @app.get("/status", response_class=PlainTextResponse)
        async def get_status():
            """Get system status information."""
            if not self.metrics_collector:
                return "Metrics collector not available"

            try:
                metrics = self.metrics_collector.get_metrics()
                uptime = time.time() - self._start_time

                status_lines = [
                    "Crypto MVP Trading System Status",
                    "=================================",
                    f"Uptime: {uptime:.2f} seconds",
                    f"Last Update: {time.ctime(metrics.last_update)}",
                    "",
                    "Portfolio:",
                    f"  Equity: ${metrics.equity:,.2f}",
                    f"  Cash Balance: ${metrics.cash_balance:,.2f}",
                    f"  Total P&L: ${metrics.total_pnl:,.2f}",
                    f"  Daily P&L: ${metrics.daily_pnl:,.2f}",
                    "",
                    "Trading Activity:",
                    f"  Total Trades: {metrics.total_trades}",
                    f"  Winning Trades: {metrics.winning_trades}",
                    f"  Losing Trades: {metrics.losing_trades}",
                    f"  Total Volume: ${metrics.total_volume:,.2f}",
                    f"  Total Fees: ${metrics.total_fees:,.2f}",
                    "",
                    "System:",
                    f"  Active Positions: {metrics.active_positions}",
                    f"  Available Capital: ${metrics.available_capital:,.2f}",
                    f"  Trading Cycles: {metrics.cycle_count}",
                ]

                # Add strategy metrics
                if metrics.strategy_metrics:
                    status_lines.extend(["", "Strategy Performance:"])
                    for strategy, strategy_metrics in metrics.strategy_metrics.items():
                        status_lines.extend(
                            [
                                f"  {strategy}:",
                                f"    Trades: {strategy_metrics['total_trades']}",
                                f"    Win Rate: {strategy_metrics['win_rate']:.2f}%",
                                f"    Hit Rate: {strategy_metrics['hit_rate']:.2f}%",
                                f"    P&L: ${strategy_metrics['total_pnl']:,.2f}",
                                f"    Volume: ${strategy_metrics['total_volume']:,.2f}",
                            ]
                        )

                return "\n".join(status_lines)

            except Exception as e:
                self.logger.error(f"Error getting status: {e}")
                return f"Error retrieving status: {str(e)}"

        return app

    async def start_server(self) -> None:
        """Start the metrics server."""
        if self.app is None:
            self.app = self.create_app()

        try:
            import uvicorn

            config = uvicorn.Config(
                app=self.app,
                host=self.host,
                port=self.port,
                log_level="info",
                access_log=False,
            )
            server = uvicorn.Server(config)
            await server.serve()
        except Exception as e:
            self.logger.error(f"Failed to start metrics server: {e}")
            raise

    def start_server_background(self) -> None:
        """Start the metrics server in a background thread."""

        def run_server():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                loop.run_until_complete(self.start_server())
            except Exception as e:
                self.logger.error(f"Background server error: {e}")
            finally:
                loop.close()

        server_thread = threading.Thread(target=run_server, daemon=True)
        server_thread.start()
        self.logger.info(
            f"Started metrics server in background on {self.host}:{self.port}"
        )

    def stop_server(self) -> None:
        """Stop the metrics server."""
        if self.server_task and not self.server_task.done():
            self.server_task.cancel()
        self.logger.info("Metrics server stopped")


# Global metrics server instance
_metrics_server: Optional[MetricsServer] = None


def get_metrics_server() -> Optional[MetricsServer]:
    """Get the global metrics server instance.

    Returns:
        MetricsServer instance or None
    """
    return _metrics_server


def start_metrics_server(
    host: str = "localhost",
    port: int = 8000,
    metrics_collector: Optional[MetricsCollector] = None,
) -> MetricsServer:
    """Start the metrics server.

    Args:
        host: Server host address
        port: Server port
        metrics_collector: MetricsCollector instance

    Returns:
        Started MetricsServer instance
    """
    global _metrics_server

    _metrics_server = MetricsServer(host, port)
    if metrics_collector:
        _metrics_server.set_metrics_collector(metrics_collector)

    _metrics_server.start_server_background()
    return _metrics_server


def stop_metrics_server() -> None:
    """Stop the metrics server."""
    global _metrics_server

    if _metrics_server:
        _metrics_server.stop_server()
        _metrics_server = None
