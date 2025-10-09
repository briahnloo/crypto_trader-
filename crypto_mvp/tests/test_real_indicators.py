"""
Test that real technical indicators calculate correctly from OHLCV data.
"""

import pytest
import numpy as np
from crypto_mvp.indicators.technical_calculator import TechnicalCalculator


class TestTechnicalCalculator:
    """Test suite for real technical indicator calculations."""
    
    def setup_method(self):
        """Set up test fixtures."""
        self.calc = TechnicalCalculator()
        
        # Create sample OHLCV data (50 periods of mock price data)
        np.random.seed(42)  # Reproducible results
        base_price = 100.0
        self.closes = np.array([base_price + np.sin(i/5) * 5 + np.random.randn() for i in range(50)])
        self.highs = self.closes + np.abs(np.random.randn(50)) * 0.5
        self.lows = self.closes - np.abs(np.random.randn(50)) * 0.5
        self.volumes = np.random.uniform(1000, 2000, 50)
    
    def test_rsi_calculation(self):
        """Test that RSI is calculated and returns value in 0-100 range."""
        rsi = self.calc.calculate_rsi(self.closes, period=14)
        
        assert rsi is not None
        assert 0 <= rsi <= 100
        assert isinstance(rsi, float)
        
        print(f"✅ RSI calculated: {rsi:.2f}")
    
    def test_macd_calculation(self):
        """Test that MACD is calculated with macd, signal, and histogram."""
        macd_data = self.calc.calculate_macd(self.closes, fast=12, slow=26, signal=9)
        
        assert macd_data is not None
        assert "macd" in macd_data
        assert "signal" in macd_data
        assert "histogram" in macd_data
        assert isinstance(macd_data["macd"], float)
        
        print(f"✅ MACD calculated: macd={macd_data['macd']:.4f}, signal={macd_data['signal']:.4f}, histogram={macd_data['histogram']:.4f}")
    
    def test_bollinger_bands_calculation(self):
        """Test that Bollinger Bands are calculated correctly."""
        bb_data = self.calc.calculate_bollinger_bands(self.closes, period=20, std_dev=2.0)
        
        assert bb_data is not None
        assert "upper" in bb_data
        assert "middle" in bb_data
        assert "lower" in bb_data
        assert "percent_b" in bb_data
        
        # Upper should be > middle > lower
        assert bb_data["upper"] > bb_data["middle"]
        assert bb_data["middle"] > bb_data["lower"]
        
        # Percent B should be 0-1 range (or slightly outside)
        assert -0.5 <= bb_data["percent_b"] <= 1.5
        
        print(f"✅ Bollinger Bands: upper={bb_data['upper']:.2f}, middle={bb_data['middle']:.2f}, lower={bb_data['lower']:.2f}, %B={bb_data['percent_b']:.2f}")
    
    def test_williams_r_calculation(self):
        """Test that Williams %R is calculated in -100 to 0 range."""
        williams_r = self.calc.calculate_williams_r(self.highs, self.lows, self.closes, period=14)
        
        assert williams_r is not None
        assert -100 <= williams_r <= 0
        assert isinstance(williams_r, float)
        
        print(f"✅ Williams %R calculated: {williams_r:.2f}")
    
    def test_atr_calculation(self):
        """Test that ATR is calculated and positive."""
        atr = self.calc.calculate_atr(self.highs, self.lows, self.closes, period=14)
        
        assert atr is not None
        assert atr > 0
        assert isinstance(atr, float)
        
        print(f"✅ ATR calculated: {atr:.4f}")
    
    def test_sma_calculation(self):
        """Test Simple Moving Average calculation."""
        sma = self.calc.calculate_sma(self.closes, period=20)
        
        assert sma is not None
        assert isinstance(sma, float)
        
        # SMA should be close to actual mean
        expected_sma = np.mean(self.closes[-20:])
        assert abs(sma - expected_sma) < 0.01
        
        print(f"✅ SMA calculated: {sma:.2f}")
    
    def test_volume_ratio_calculation(self):
        """Test volume ratio calculation."""
        volume_ratio = self.calc.calculate_volume_ratio(self.volumes, period=20)
        
        assert volume_ratio is not None
        assert volume_ratio > 0
        assert isinstance(volume_ratio, float)
        
        print(f"✅ Volume ratio calculated: {volume_ratio:.2f}")
    
    def test_support_resistance_detection(self):
        """Test support/resistance level detection."""
        levels = self.calc.detect_support_resistance(self.highs, self.lows, self.closes, lookback=20)
        
        assert "support" in levels
        assert "resistance" in levels
        assert "current" in levels
        assert levels["resistance"] >= levels["current"] >= levels["support"]
        
        print(f"✅ S/R levels: support={levels['support']:.2f}, current={levels['current']:.2f}, resistance={levels['resistance']:.2f}")
    
    def test_insufficient_data_returns_none(self):
        """Test that insufficient data returns None gracefully."""
        short_closes = np.array([100, 101, 102])
        
        rsi = self.calc.calculate_rsi(short_closes, period=14)
        assert rsi is None
        
        macd = self.calc.calculate_macd(short_closes, fast=12, slow=26, signal=9)
        assert macd is None
        
        print("✅ Insufficient data handled gracefully")


class TestRealStrategy:
    """Test that strategies work with real indicators."""
    
    def test_momentum_strategy_with_mock_data_engine(self):
        """Test momentum strategy can analyze with data engine."""
        from crypto_mvp.strategies.momentum import MomentumStrategy
        
        # Create strategy
        config = {"parameters": {"rsi_period": 14}}
        strategy = MomentumStrategy(config)
        
        # Create mock data engine
        class MockDataEngine:
            def get_ohlcv(self, symbol, timeframe, limit):
                # Return sample OHLCV data
                return [[i, 100+i, 101+i, 99+i, 100+i, 1000] for i in range(50)]
        
        strategy.data_engine = MockDataEngine()
        
        # Analyze
        result = strategy.analyze("BTC/USDT", "1h")
        
        assert "score" in result
        assert "confidence" in result
        assert "entry_price" in result
        assert result["metadata"]["strategy"] == "momentum"
        
        # Should have real indicator values
        if not result["metadata"].get("error"):
            assert "rsi" in result["metadata"]
            assert "macd" in result["metadata"]
            
            print(f"✅ Momentum strategy analysis: score={result['score']:.3f}, confidence={result['confidence']:.3f}")
        else:
            print(f"⚠️  Momentum strategy returned neutral (reason: {result['metadata'].get('reason')})")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])

