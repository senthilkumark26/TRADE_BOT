"""
Market Configuration System
Handles market-specific trading parameters, volatility-based TP/SL, and risk management
"""

# Market-specific trading configurations
MARKET_CONFIGS = {
    "MCX": {
        "CRUDEOIL": {
            "tp_pct": 0.20,           # 20% target
            "sl_pct": 0.15,           # 15% stoploss
            "trailing_sl_start": 0.10, # Start trailing at 10% profit
            "trailing_sl_lock": 0.20,  # Lock profit at 20% gain
            "max_trades_per_day": 2,  # Limit exposure
            "risk_per_trade": 0.01,   # 1% risk per trade
            "max_hold_time_minutes": 30,  # Time exit
            "volatility_multiplier": 1.0,  # Base volatility adjustment
            "min_volume": 10,         # Minimum volume for trading
            "min_oi": 100,            # Minimum OI for trading
            "description": "Crude Oil - Moderate volatility, liquid"
        },
        "NATGAS": {
            "tp_pct": 0.30,           # 30% target (higher due to volatility)
            "sl_pct": 0.20,           # 20% stoploss (wider due to volatility)
            "trailing_sl_start": 0.15, # Start trailing at 15% profit
            "trailing_sl_lock": 0.25,  # Lock profit at 25% gain
            "max_trades_per_day": 1,  # Limit exposure (high volatility)
            "risk_per_trade": 0.008,  # 0.8% risk per trade (conservative)
            "max_hold_time_minutes": 15,  # Shorter hold time (fast moves)
            "volatility_multiplier": 1.5,  # Higher volatility adjustment
            "min_volume": 5,          # Lower volume requirement (less liquid)
            "min_oi": 50,             # Lower OI requirement
            "description": "Natural Gas - High volatility, less liquid"
        },
        "GOLDM": {
            "tp_pct": 0.12,           # 12% target (conservative)
            "sl_pct": 0.08,           # 8% stoploss (tighter)
            "trailing_sl_start": 0.08, # Start trailing at 8% profit
            "trailing_sl_lock": 0.12,  # Lock profit at 12% gain
            "max_trades_per_day": 3,  # Moderate exposure
            "risk_per_trade": 0.015,  # 1.5% risk per trade
            "max_hold_time_minutes": 45,  # Longer hold time (slower moves)
            "volatility_multiplier": 0.8,  # Lower volatility adjustment
            "min_volume": 10,         # Standard volume requirement
            "min_oi": 100,            # Standard OI requirement
            "description": "Gold Mini - Lower volatility, stable"
        },
        "SILVERM": {
            "tp_pct": 0.15,           # 15% target
            "sl_pct": 0.10,           # 10% stoploss
            "trailing_sl_start": 0.10, # Start trailing at 10% profit
            "trailing_sl_lock": 0.15,  # Lock profit at 15% gain
            "max_trades_per_day": 2,  # Moderate exposure
            "risk_per_trade": 0.012,  # 1.2% risk per trade
            "max_hold_time_minutes": 30,  # Standard hold time
            "volatility_multiplier": 1.0,  # Base volatility adjustment
            "min_volume": 5,          # Lower volume requirement
            "min_oi": 50,             # Lower OI requirement
            "description": "Silver Mini - Moderate volatility"
        }
    },
    "NSE": {
        "NIFTY": {
            "tp_pct": 0.10,           # 10% target
            "sl_pct": 0.05,           # 5% stoploss
            "trailing_sl_start": 0.06, # Start trailing at 6% profit
            "trailing_sl_lock": 0.10,  # Lock profit at 10% gain
            "max_trades_per_day": 5,  # Higher exposure (liquid)
            "risk_per_trade": 0.02,   # 2% risk per trade
            "max_hold_time_minutes": 60,  # Longer hold time
            "volatility_multiplier": 0.9,  # Slightly lower volatility
            "min_volume": 100,        # High volume requirement
            "min_oi": 500,            # High OI requirement
            "description": "NIFTY - High liquidity, moderate volatility"
        },
        "BANKNIFTY": {
            "tp_pct": 0.12,           # 12% target
            "sl_pct": 0.06,           # 6% stoploss
            "trailing_sl_start": 0.07, # Start trailing at 7% profit
            "trailing_sl_lock": 0.12,  # Lock profit at 12% gain
            "max_trades_per_day": 3,  # Moderate exposure
            "risk_per_trade": 0.015,  # 1.5% risk per trade
            "max_hold_time_minutes": 45,  # Standard hold time
            "volatility_multiplier": 1.1,  # Higher volatility
            "min_volume": 80,         # High volume requirement
            "min_oi": 400,            # High OI requirement
            "description": "BANKNIFTY - High volatility, liquid"
        }
    }
}

# Global trading parameters
GLOBAL_CONFIG = {
    "debug_mode": True,              # Override filters for testing
    "max_total_risk": 0.05,          # 5% total daily risk
    "max_open_positions": 4,         # Maximum concurrent positions
    "min_confidence_threshold": 0.60,  # Minimum confidence for trades
    "enable_trailing_sl": True,      # Enable trailing stop-loss
    "enable_time_exit": True,        # Enable time-based exits
    "kill_switch_daily_loss": -3000,  # Kill switch at -3000 loss
}


def get_symbol_config(market: str, symbol: str) -> dict:
    """
    Get configuration for a specific symbol in a market.
    
    Args:
        market: Market name (MCX, NSE)
        symbol: Symbol name (CRUDEOIL, NIFTY, etc.)
    
    Returns:
        Configuration dictionary for the symbol
    """
    if market not in MARKET_CONFIGS:
        raise ValueError(f"Market {market} not found in configuration")
    
    if symbol not in MARKET_CONFIGS[market]:
        # Return default configuration if symbol not found
        return get_default_config()
    
    return MARKET_CONFIGS[market][symbol]


def get_default_config() -> dict:
    """Get default configuration for unknown symbols."""
    return {
        "tp_pct": 0.15,
        "sl_pct": 0.10,
        "trailing_sl_start": 0.10,
        "trailing_sl_lock": 0.15,
        "max_trades_per_day": 2,
        "risk_per_trade": 0.01,
        "max_hold_time_minutes": 30,
        "volatility_multiplier": 1.0,
        "min_volume": 10,
        "min_oi": 100,
        "description": "Default configuration"
    }


def calculate_volatility_adjusted_tp_sl(entry_price: float, config: dict, 
                                       current_volatility: float = None) -> tuple:
    """
    Calculate volatility-adjusted TP/SL based on market configuration.
    
    Args:
        entry_price: Entry price
        config: Symbol configuration dictionary
        current_volatility: Optional current volatility (ATR, std dev, etc.)
    
    Returns:
        (target_price, stoploss_price) tuple
    """
    base_tp_pct = config["tp_pct"]
    base_sl_pct = config["sl_pct"]
    vol_multiplier = config["volatility_multiplier"]
    
    # If current volatility is provided, adjust dynamically
    if current_volatility:
        # Higher volatility = wider TP/SL
        vol_adjustment = current_volatility * vol_multiplier
        adjusted_tp_pct = base_tp_pct * (1 + vol_adjustment)
        adjusted_sl_pct = base_sl_pct * (1 + vol_adjustment)
    else:
        # Use configured volatility multiplier
        adjusted_tp_pct = base_tp_pct * vol_multiplier
        adjusted_sl_pct = base_sl_pct * vol_multiplier
    
    # Calculate absolute prices
    target_price = entry_price * (1 + adjusted_tp_pct)
    stoploss_price = entry_price * (1 - adjusted_sl_pct)
    
    return target_price, stoploss_price


def calculate_position_size(capital: float, entry_price: float, sl_price: float, 
                           config: dict) -> int:
    """
    Calculate position size based on risk management rules.
    
    Args:
        capital: Total capital
        entry_price: Entry price
        sl_price: Stoploss price
        config: Symbol configuration
    
    Returns:
        Position size (number of lots/contracts)
    """
    risk_per_trade = capital * config["risk_per_trade"]
    risk_per_unit = abs(entry_price - sl_price)
    
    if risk_per_unit == 0:
        return 1  # Minimum position
    
    position_size = int(risk_per_trade / risk_per_unit)
    return max(1, position_size)  # At least 1 position


def validate_trade_config(market: str, symbol: str, config: dict) -> bool:
    """
    Validate that a trade configuration is within acceptable limits.
    
    Args:
        market: Market name
        symbol: Symbol name
        config: Configuration to validate
    
    Returns:
        True if configuration is valid
    """
    # Check TP/SL ratios
    if config["tp_pct"] <= 0 or config["sl_pct"] <= 0:
        return False
    
    if config["tp_pct"] < config["sl_pct"]:
        return False  # Target should be wider than stoploss
    
    # Check risk parameters
    if config["risk_per_trade"] <= 0 or config["risk_per_trade"] > 0.05:
        return False  # Risk should be 0-5%
    
    # Check trading limits
    if config["max_trades_per_day"] <= 0:
        return False
    
    return True


if __name__ == "__main__":
    # Test the configuration system
    print("Testing Market Configuration System")
    print("=" * 50)
    
    # Test MCX configurations
    for symbol in ["CRUDEOIL", "NATGAS", "GOLDM", "SILVERM"]:
        config = get_symbol_config("MCX", symbol)
        print(f"\n{symbol}:")
        print(f"  TP: {config['tp_pct']*100:.1f}%")
        print(f"  SL: {config['sl_pct']*100:.1f}%")
        print(f"  Risk: {config['risk_per_trade']*100:.1f}%")
        print(f"  Description: {config['description']}")
    
    # Test volatility-adjusted TP/SL
    entry = 100
    config = get_symbol_config("MCX", "CRUDEOIL")
    tp, sl = calculate_volatility_adjusted_tp_sl(entry, config)
    print(f"\nVolatility-adjusted TP/SL for CRUDEOIL @ {entry}:")
    print(f"  Target: {tp:.2f} ({((tp-entry)/entry)*100:.1f}%)")
    print(f"  Stoploss: {sl:.2f} ({((sl-entry)/entry)*100:.1f}%)")
