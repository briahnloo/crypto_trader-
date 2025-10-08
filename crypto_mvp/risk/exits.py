"""
Exit strategies with Decimal precision.

This module provides exit strategy functionality with:
- Chandelier exits
- Time-based exits
- Decimal-based calculations
- Monotonic level verification
"""

from decimal import Decimal, getcontext, ROUND_HALF_UP
from typing import Dict, List, Optional, Tuple, Union, Any
from datetime import datetime, timedelta
import logging

# Set decimal precision
getcontext().prec = 28

logger = logging.getLogger(__name__)


class ExitSpecError(Exception):
    """Raised when exit strategy specifications are invalid."""
    pass


class ChandelierExit:
    """Chandelier exit strategy with Decimal precision."""
    
    def __init__(
        self,
        symbol: str,
        side: str,
        entry_price: Union[float, Decimal],
        quantity: Union[float, Decimal],
        atr: Union[float, Decimal],
        atr_multiplier: Union[float, Decimal] = Decimal('3.0'),
        highest_price: Optional[Union[float, Decimal]] = None,
        lowest_price: Optional[Union[float, Decimal]] = None,
        strategy: str = "unknown"
    ):
        """
        Initialize chandelier exit.
        
        Args:
            symbol: Trading symbol
            side: Order side (BUY/SELL)
            entry_price: Entry price
            quantity: Order quantity
            atr: Average True Range
            atr_multiplier: ATR multiplier for exit distance
            highest_price: Highest price since entry (for long positions)
            lowest_price: Lowest price since entry (for short positions)
            strategy: Strategy name
        """
        # Convert inputs to Decimal
        self.entry_price = Decimal(str(entry_price))
        self.quantity = Decimal(str(quantity))
        self.atr = Decimal(str(atr))
        self.atr_multiplier = Decimal(str(atr_multiplier))
        self.side = side.upper()
        self.symbol = symbol
        self.strategy = strategy
        
        # Initialize tracking prices
        if side == "BUY":
            self.highest_price = Decimal(str(highest_price)) if highest_price else self.entry_price
            self.lowest_price = None
        else:
            self.lowest_price = Decimal(str(lowest_price)) if lowest_price else self.entry_price
            self.highest_price = None
        
        # Calculate initial exit level
        self.exit_level = self._calculate_exit_level()
        
        # Validate exit specifications
        self._validate_exit_specs()
    
    def _validate_exit_specs(self) -> None:
        """Validate exit strategy specifications."""
        if self.atr <= 0:
            raise ExitSpecError(f"ATR must be positive: {self.atr}")
        
        if self.atr_multiplier <= 0:
            raise ExitSpecError(f"ATR multiplier must be positive: {self.atr_multiplier}")
        
        if self.quantity <= 0:
            raise ExitSpecError(f"Quantity must be positive: {self.quantity}")
        
        if self.side not in ["BUY", "SELL"]:
            raise ExitSpecError(f"Invalid side: {self.side}. Must be BUY or SELL")
    
    def _calculate_exit_level(self) -> Decimal:
        """Calculate current exit level."""
        if self.side == "BUY":
            # For long positions, exit below highest price
            exit_distance = self.atr * self.atr_multiplier
            return self.highest_price - exit_distance
        else:
            # For short positions, exit above lowest price
            exit_distance = self.atr * self.atr_multiplier
            return self.lowest_price + exit_distance
    
    def update_price(self, current_price: Union[float, Decimal]) -> bool:
        """
        Update current price and recalculate exit level.
        
        Args:
            current_price: Current market price
            
        Returns:
            True if exit level was updated
        """
        current_decimal = Decimal(str(current_price))
        old_exit_level = self.exit_level
        
        if self.side == "BUY":
            # For long positions, update highest price
            if current_decimal > self.highest_price:
                self.highest_price = current_decimal
                self.exit_level = self._calculate_exit_level()
                return True
        else:
            # For short positions, update lowest price
            if current_decimal < self.lowest_price:
                self.lowest_price = current_decimal
                self.exit_level = self._calculate_exit_level()
                return True
        
        return False
    
    def should_exit(self, current_price: Union[float, Decimal]) -> bool:
        """
        Check if position should be exited.
        
        Args:
            current_price: Current market price
            
        Returns:
            True if position should be exited
        """
        current_decimal = Decimal(str(current_price))
        
        if self.side == "BUY":
            return current_decimal <= self.exit_level
        else:
            return current_decimal >= self.exit_level
    
    def get_exit_level(self) -> Decimal:
        """Get current exit level."""
        return self.exit_level
    
    def get_trailing_distance(self) -> Decimal:
        """Get current trailing distance."""
        if self.side == "BUY":
            return self.highest_price - self.exit_level
        else:
            return self.exit_level - self.lowest_price
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert chandelier exit to dictionary."""
        return {
            "symbol": self.symbol,
            "side": self.side,
            "entry_price": float(self.entry_price),
            "quantity": float(self.quantity),
            "atr": float(self.atr),
            "atr_multiplier": float(self.atr_multiplier),
            "exit_level": float(self.exit_level),
            "highest_price": float(self.highest_price) if self.highest_price else None,
            "lowest_price": float(self.lowest_price) if self.lowest_price else None,
            "trailing_distance": float(self.get_trailing_distance()),
            "strategy": self.strategy
        }


class TimeExit:
    """Time-based exit strategy with Decimal precision."""
    
    def __init__(
        self,
        symbol: str,
        side: str,
        entry_price: Union[float, Decimal],
        quantity: Union[float, Decimal],
        entry_time: datetime,
        exit_time: datetime,
        strategy: str = "unknown"
    ):
        """
        Initialize time exit.
        
        Args:
            symbol: Trading symbol
            side: Order side (BUY/SELL)
            entry_price: Entry price
            quantity: Order quantity
            entry_time: Entry time
            exit_time: Scheduled exit time
            strategy: Strategy name
        """
        # Convert inputs to Decimal
        self.entry_price = Decimal(str(entry_price))
        self.quantity = Decimal(str(quantity))
        self.side = side.upper()
        self.symbol = symbol
        self.strategy = strategy
        
        # Time tracking
        self.entry_time = entry_time
        self.exit_time = exit_time
        
        # Validate exit specifications
        self._validate_exit_specs()
    
    def _validate_exit_specs(self) -> None:
        """Validate exit strategy specifications."""
        if self.quantity <= 0:
            raise ExitSpecError(f"Quantity must be positive: {self.quantity}")
        
        if self.side not in ["BUY", "SELL"]:
            raise ExitSpecError(f"Invalid side: {self.side}. Must be BUY or SELL")
        
        if self.exit_time <= self.entry_time:
            raise ExitSpecError(f"Exit time must be after entry time: {self.exit_time} <= {self.entry_time}")
    
    def should_exit(self, current_time: Optional[datetime] = None) -> bool:
        """
        Check if position should be exited based on time.
        
        Args:
            current_time: Current time (defaults to now)
            
        Returns:
            True if position should be exited
        """
        if current_time is None:
            current_time = datetime.now()
        
        return current_time >= self.exit_time
    
    def get_time_remaining(self, current_time: Optional[datetime] = None) -> timedelta:
        """
        Get time remaining until exit.
        
        Args:
            current_time: Current time (defaults to now)
            
        Returns:
            Time remaining until exit
        """
        if current_time is None:
            current_time = datetime.now()
        
        return self.exit_time - current_time
    
    def get_holding_duration(self, current_time: Optional[datetime] = None) -> timedelta:
        """
        Get holding duration since entry.
        
        Args:
            current_time: Current time (defaults to now)
            
        Returns:
            Holding duration since entry
        """
        if current_time is None:
            current_time = datetime.now()
        
        return current_time - self.entry_time
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert time exit to dictionary."""
        return {
            "symbol": self.symbol,
            "side": self.side,
            "entry_price": float(self.entry_price),
            "quantity": float(self.quantity),
            "entry_time": self.entry_time.isoformat(),
            "exit_time": self.exit_time.isoformat(),
            "time_remaining": str(self.get_time_remaining()),
            "holding_duration": str(self.get_holding_duration()),
            "strategy": self.strategy
        }


class ExitManager:
    """Manages exit strategies with Decimal precision."""
    
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """
        Initialize exit manager.
        
        Args:
            config: Configuration dictionary
        """
        self.config = config or {}
        self.active_exits: Dict[str, Union[ChandelierExit, TimeExit]] = {}
        
        # Default configuration
        self.default_atr_multiplier = Decimal('3.0')
        self.default_time_exit_minutes = 30
    
    def create_chandelier_exit(
        self,
        symbol: str,
        side: str,
        entry_price: Union[float, Decimal],
        quantity: Union[float, Decimal],
        atr: Union[float, Decimal],
        atr_multiplier: Optional[Union[float, Decimal]] = None,
        strategy: str = "unknown",
        exit_id: str = ""
    ) -> ChandelierExit:
        """
        Create chandelier exit strategy.
        
        Args:
            symbol: Trading symbol
            side: Order side (BUY/SELL)
            entry_price: Entry price
            quantity: Order quantity
            atr: Average True Range
            atr_multiplier: ATR multiplier
            strategy: Strategy name
            exit_id: Exit strategy ID
            
        Returns:
            ChandelierExit instance
        """
        if atr_multiplier is None:
            atr_multiplier = self.default_atr_multiplier
        
        exit_strategy = ChandelierExit(
            symbol=symbol,
            side=side,
            entry_price=entry_price,
            quantity=quantity,
            atr=atr,
            atr_multiplier=atr_multiplier,
            strategy=strategy
        )
        
        if exit_id:
            self.active_exits[exit_id] = exit_strategy
        
        logger.info(f"Created chandelier exit {exit_id}: {exit_strategy.to_dict()}")
        
        return exit_strategy
    
    def create_time_exit(
        self,
        symbol: str,
        side: str,
        entry_price: Union[float, Decimal],
        quantity: Union[float, Decimal],
        entry_time: datetime,
        exit_minutes: Optional[int] = None,
        strategy: str = "unknown",
        exit_id: str = ""
    ) -> TimeExit:
        """
        Create time-based exit strategy.
        
        Args:
            symbol: Trading symbol
            side: Order side (BUY/SELL)
            entry_price: Entry price
            quantity: Order quantity
            entry_time: Entry time
            exit_minutes: Exit time in minutes from entry
            strategy: Strategy name
            exit_id: Exit strategy ID
            
        Returns:
            TimeExit instance
        """
        if exit_minutes is None:
            exit_minutes = self.default_time_exit_minutes
        
        exit_time = entry_time + timedelta(minutes=exit_minutes)
        
        exit_strategy = TimeExit(
            symbol=symbol,
            side=side,
            entry_price=entry_price,
            quantity=quantity,
            entry_time=entry_time,
            exit_time=exit_time,
            strategy=strategy
        )
        
        if exit_id:
            self.active_exits[exit_id] = exit_strategy
        
        logger.info(f"Created time exit {exit_id}: {exit_strategy.to_dict()}")
        
        return exit_strategy
    
    def update_chandelier_price(
        self,
        exit_id: str,
        current_price: Union[float, Decimal]
    ) -> bool:
        """
        Update chandelier exit with current price.
        
        Args:
            exit_id: Exit strategy ID
            current_price: Current market price
            
        Returns:
            True if exit level was updated
        """
        if exit_id not in self.active_exits:
            logger.warning(f"Exit strategy {exit_id} not found")
            return False
        
        exit_strategy = self.active_exits[exit_id]
        
        if isinstance(exit_strategy, ChandelierExit):
            return exit_strategy.update_price(current_price)
        else:
            logger.warning(f"Exit strategy {exit_id} is not a chandelier exit")
            return False
    
    def check_exit_conditions(
        self,
        exit_id: str,
        current_price: Optional[Union[float, Decimal]] = None,
        current_time: Optional[datetime] = None
    ) -> bool:
        """
        Check if exit conditions are met.
        
        Args:
            exit_id: Exit strategy ID
            current_price: Current market price (for chandelier exits)
            current_time: Current time (for time exits)
            
        Returns:
            True if exit conditions are met
        """
        if exit_id not in self.active_exits:
            logger.warning(f"Exit strategy {exit_id} not found")
            return False
        
        exit_strategy = self.active_exits[exit_id]
        
        if isinstance(exit_strategy, ChandelierExit):
            if current_price is None:
                logger.warning(f"Current price required for chandelier exit {exit_id}")
                return False
            return exit_strategy.should_exit(current_price)
        
        elif isinstance(exit_strategy, TimeExit):
            return exit_strategy.should_exit(current_time)
        
        else:
            logger.warning(f"Unknown exit strategy type for {exit_id}")
            return False
    
    def close_exit(self, exit_id: str) -> Optional[Union[ChandelierExit, TimeExit]]:
        """
        Close exit strategy.
        
        Args:
            exit_id: Exit strategy ID
            
        Returns:
            Closed exit strategy or None if not found
        """
        if exit_id in self.active_exits:
            exit_strategy = self.active_exits.pop(exit_id)
            logger.info(f"Closed exit strategy {exit_id}")
            return exit_strategy
        
        logger.warning(f"Exit strategy {exit_id} not found for closing")
        return None
    
    def get_active_exits(self) -> Dict[str, Union[ChandelierExit, TimeExit]]:
        """Get all active exit strategies."""
        return self.active_exits.copy()
    
    def validate_exit_specs(
        self,
        exit_type: str,
        side: str,
        entry_price: Union[float, Decimal],
        quantity: Union[float, Decimal],
        **kwargs
    ) -> bool:
        """
        Validate exit strategy specifications without creating strategy.
        
        Args:
            exit_type: Type of exit strategy ("chandelier" or "time")
            side: Order side (BUY/SELL)
            entry_price: Entry price
            quantity: Order quantity
            **kwargs: Additional parameters for validation
            
        Returns:
            True if specifications are valid
        """
        try:
            if exit_type == "chandelier":
                atr = kwargs.get("atr", Decimal('100'))
                ChandelierExit(
                    symbol="VALIDATION",
                    side=side,
                    entry_price=entry_price,
                    quantity=quantity,
                    atr=atr,
                    strategy="validation"
                )
            elif exit_type == "time":
                entry_time = kwargs.get("entry_time", datetime.now())
                exit_time = kwargs.get("exit_time", datetime.now() + timedelta(minutes=30))
                TimeExit(
                    symbol="VALIDATION",
                    side=side,
                    entry_price=entry_price,
                    quantity=quantity,
                    entry_time=entry_time,
                    exit_time=exit_time,
                    strategy="validation"
                )
            else:
                raise ExitSpecError(f"Unknown exit type: {exit_type}")
            
            return True
        except ExitSpecError:
            return False


def create_chandelier_exit(
    symbol: str,
    side: str,
    entry_price: Union[float, Decimal],
    quantity: Union[float, Decimal],
    atr: Union[float, Decimal],
    atr_multiplier: Union[float, Decimal] = Decimal('3.0'),
    strategy: str = "unknown"
) -> ChandelierExit:
    """
    Convenience function to create chandelier exit.
    
    Args:
        symbol: Trading symbol
        side: Order side (BUY/SELL)
        entry_price: Entry price
        quantity: Order quantity
        atr: Average True Range
        atr_multiplier: ATR multiplier
        strategy: Strategy name
        
    Returns:
        ChandelierExit instance
    """
    manager = ExitManager()
    return manager.create_chandelier_exit(
        symbol=symbol,
        side=side,
        entry_price=entry_price,
        quantity=quantity,
        atr=atr,
        atr_multiplier=atr_multiplier,
        strategy=strategy
    )


def create_time_exit(
    symbol: str,
    side: str,
    entry_price: Union[float, Decimal],
    quantity: Union[float, Decimal],
    entry_time: datetime,
    exit_minutes: int = 30,
    strategy: str = "unknown"
) -> TimeExit:
    """
    Convenience function to create time exit.
    
    Args:
        symbol: Trading symbol
        side: Order side (BUY/SELL)
        entry_price: Entry price
        quantity: Order quantity
        entry_time: Entry time
        exit_minutes: Exit time in minutes from entry
        strategy: Strategy name
        
    Returns:
        TimeExit instance
    """
    manager = ExitManager()
    return manager.create_time_exit(
        symbol=symbol,
        side=side,
        entry_price=entry_price,
        quantity=quantity,
        entry_time=entry_time,
        exit_minutes=exit_minutes,
        strategy=strategy
    )
