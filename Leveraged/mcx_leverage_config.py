"""
MCX Leverage Configuration
All leverage and risk management settings for MCX commodities trading

This file contains:
- Lot sizes for each commodity
- Risk per trade percentages
- Maximum trades per day
- Position sizing parameters
- Volatility multipliers

Last Updated: 2026-06-09
"""

# MCX Commodity Leverage Settings
MCX_LEVERAGE_CONFIG = {
    "CRUDEOIL": {
        # LOT SIZE
        "lot_size": 100,                    # 100 barrels per lot
        "lot_value": 100,                   # Lot value multiplier
        
        # RISK MANAGEMENT
        "risk_per_trade_pct": 0.01,        # 1% risk per trade (conservative)
        "max_trades_per_day": 2,           # Maximum 2 trades per day
        "max_open_positions": 1,           # Maximum 1 open position at a time
        
        # LEVERAGE EFFECTIVE
        "margin_per_lot": 50000,           # Approximate margin required per lot
        "effective_leverage": 10,          # 10x leverage (typical for commodities)
        
        # POSITION SIZING
        "min_position_size": 1,             # Minimum 1 lot
        "max_position_size": 5,             # Maximum 5 lots
        "position_sizing_method": "risk_based",  # Risk-based position sizing
        
        # VOLATILITY ADJUSTMENT
        "volatility_multiplier": 1.0,       # Base volatility (no adjustment)
        "atr_multiplier": 1.5,             # ATR-based SL multiplier
        
        # TIME PARAMETERS
        "max_hold_time_minutes": 30,       # Maximum 30 minutes hold time
        "min_hold_time_minutes": 5,         # Minimum 5 minutes hold time
        
        # DESCRIPTION
        "description": "Crude Oil - 100 barrels per lot, moderate leverage",
        "exchange": "MCX",
        "segment": "COMMODITY",
        
        # OUTER SHELL THRESHOLDS (Safety Filters)
        "min_volume": 10,                 # Minimum volume for trading
        "min_oi": 100,                    # Minimum open interest
        "max_spread_pct": 0.10,          # Maximum 10% spread (bid-ask)
        "max_strike_distance_pct": 0.10,  # Maximum 10% from ATM
        "min_liquidity_score": 5,         # Minimum liquidity score (1-10)
    },
    
    "NATGAS": {
        # LOT SIZE
        "lot_size": 1250,                   # 1250 mmBtu per lot
        "lot_value": 1,                     # Lot value multiplier
        
        # RISK MANAGEMENT
        "risk_per_trade_pct": 0.008,       # 0.8% risk per trade (very conservative - high volatility)
        "max_trades_per_day": 1,           # Maximum 1 trade per day (high volatility)
        "max_open_positions": 1,           # Maximum 1 open position at a time
        
        # LEVERAGE EFFECTIVE
        "margin_per_lot": 25000,           # Approximate margin required per lot
        "effective_leverage": 8,            # 8x leverage (lower due to volatility)
        
        # POSITION SIZING
        "min_position_size": 1,             # Minimum 1 lot
        "max_position_size": 2,             # Maximum 2 lots (limited due to volatility)
        "position_sizing_method": "risk_based",  # Risk-based position sizing
        
        # VOLATILITY ADJUSTMENT
        "volatility_multiplier": 1.5,       # Higher volatility adjustment
        "atr_multiplier": 2.0,             # Wider ATR-based SL
        
        # TIME PARAMETERS
        "max_hold_time_minutes": 15,       # Maximum 15 minutes (fast moves)
        "min_hold_time_minutes": 3,         # Minimum 3 minutes
        
        # DESCRIPTION
        "description": "Natural Gas - 1250 mmBtu per lot, high volatility, conservative leverage",
        "exchange": "MCX",
        "segment": "COMMODITY",
        
        # OUTER SHELL THRESHOLDS (Safety Filters)
        "min_volume": 5,                  # Lower volume requirement (less liquid)
        "min_oi": 50,                     # Lower OI requirement
        "max_spread_pct": 0.15,          # Maximum 15% spread (wider for less liquid)
        "max_strike_distance_pct": 0.15,  # Maximum 15% from ATM (wider for volatility)
        "min_liquidity_score": 3,         # Lower liquidity score (less liquid)
    },
    
    "GOLDM": {
        # LOT SIZE
        "lot_size": 10,                     # 10 grams per lot (Mini Gold)
        "lot_value": 10,                    # Lot value multiplier
        
        # RISK MANAGEMENT
        "risk_per_trade_pct": 0.015,       # 1.5% risk per trade (moderate)
        "max_trades_per_day": 3,           # Maximum 3 trades per day
        "max_open_positions": 2,           # Maximum 2 open positions
        
        # LEVERAGE EFFECTIVE
        "margin_per_lot": 30000,           # Approximate margin required per lot
        "effective_leverage": 12,           # 12x leverage (higher for gold)
        
        # POSITION SIZING
        "min_position_size": 1,             # Minimum 1 lot
        "max_position_size": 10,            # Maximum 10 lots
        "position_sizing_method": "risk_based",  # Risk-based position sizing
        
        # VOLATILITY ADJUSTMENT
        "volatility_multiplier": 0.8,       # Lower volatility (gold is stable)
        "atr_multiplier": 1.2,             # Tighter ATR-based SL
        
        # TIME PARAMETERS
        "max_hold_time_minutes": 45,       # Maximum 45 minutes (slower moves)
        "min_hold_time_minutes": 10,        # Minimum 10 minutes
        
        # DESCRIPTION
        "description": "Gold Mini - 10 grams per lot, stable, higher leverage",
        "exchange": "MCX",
        "segment": "COMMODITY",
        
        # OUTER SHELL THRESHOLDS (Safety Filters)
        "min_volume": 10,                 # Standard volume requirement
        "min_oi": 100,                    # Standard OI requirement
        "max_spread_pct": 0.08,          # Maximum 8% spread (tighter for liquid)
        "max_strike_distance_pct": 0.08,  # Maximum 8% from ATM (tighter for stable)
        "min_liquidity_score": 7,         # Higher liquidity score (more liquid)
    },
    
    "SILVERM": {
        # LOT SIZE
        "lot_size": 5,                      # 5 kg per lot (Mini Silver)
        "lot_value": 5,                     # Lot value multiplier
        
        # RISK MANAGEMENT
        "risk_per_trade_pct": 0.012,       # 1.2% risk per trade (moderate)
        "max_trades_per_day": 2,           # Maximum 2 trades per day
        "max_open_positions": 1,           # Maximum 1 open position
        
        # LEVERAGE EFFECTIVE
        "margin_per_lot": 25000,           # Approximate margin required per lot
        "effective_leverage": 15,           # 15x leverage (highest for silver)
        
        # POSITION SIZING
        "min_position_size": 1,             # Minimum 1 lot
        "max_position_size": 5,             # Maximum 5 lots
        "position_sizing_method": "risk_based",  # Risk-based position sizing
        
        # VOLATILITY ADJUSTMENT
        "volatility_multiplier": 1.0,       # Base volatility
        "atr_multiplier": 1.5,             # Standard ATR-based SL
        
        # TIME PARAMETERS
        "max_hold_time_minutes": 30,       # Maximum 30 minutes
        "min_hold_time_minutes": 5,         # Minimum 5 minutes
        
        # DESCRIPTION
        "description": "Silver Mini - 5 kg per lot, moderate volatility, high leverage",
        "exchange": "MCX",
        "segment": "COMMODITY",
        
        # OUTER SHELL THRESHOLDS (Safety Filters)
        "min_volume": 5,                  # Lower volume requirement
        "min_oi": 50,                     # Lower OI requirement
        "max_spread_pct": 0.12,          # Maximum 12% spread (moderate)
        "max_strike_distance_pct": 0.12,  # Maximum 12% from ATM (moderate)
        "min_liquidity_score": 4,         # Moderate liquidity score
    }
}

# GLOBAL LEVERAGE SETTINGS
GLOBAL_LEVERAGE_SETTINGS = {
    # CAPITAL MANAGEMENT
    "total_capital": 100000,              # Total trading capital
    "max_total_risk_pct": 0.05,          # Maximum 5% total daily risk
    "max_total_exposure_pct": 0.20,      # Maximum 20% total exposure
    
    # LEVERAGE LIMITS
    "max_effective_leverage": 15,         # Maximum 15x leverage across all positions
    "margin_usage_limit": 0.50,          # Maximum 50% margin usage
    
    # POSITION LIMITS
    "max_total_positions": 4,            # Maximum 4 positions across all symbols
    "max_same_symbol_positions": 1,      # Maximum 1 position per symbol
    
    # RISK CONTROLS
    "daily_loss_limit": -3000,           # Kill switch at -3000 daily loss
    "max_drawdown_pct": 0.10,            # Maximum 10% drawdown
    "consecutive_loss_limit": 3,         # Stop after 3 consecutive losses
    
    # LEVERAGE ADJUSTMENT
    "reduce_leverage_after_loss": True,  # Reduce leverage after losses
    "leverage_reduction_factor": 0.5,    # Reduce by 50% after loss
    "restore_leverage_after_win": True,  # Restore leverage after win
}

# POSITION SIZING CALCULATIONS
def calculate_position_size(symbol: str, entry_price: float, sl_price: float, 
                           capital: float, leverage_config: dict = None) -> dict:
    """
    Calculate optimal position size based on leverage and risk parameters.
    
    Args:
        symbol: Trading symbol (CRUDEOIL, NATGAS, etc.)
        entry_price: Entry price
        sl_price: Stop loss price
        capital: Total capital
        leverage_config: Optional leverage configuration
    
    Returns:
        Dictionary with position sizing details
    """
    if leverage_config is None:
        leverage_config = MCX_LEVERAGE_CONFIG.get(symbol, MCX_LEVERAGE_CONFIG["CRUDEOIL"])
    
    lot_size = leverage_config["lot_size"]
    risk_per_trade_pct = leverage_config["risk_per_trade_pct"]
    max_lots = leverage_config["max_position_size"]
    
    # Calculate risk amount
    risk_amount = capital * risk_per_trade_pct
    
    # Calculate risk per lot
    risk_per_lot = abs(entry_price - sl_price) * lot_size
    
    if risk_per_lot == 0:
        risk_per_lot = entry_price * 0.10 * lot_size  # Fallback 10% risk
    
    # Calculate optimal lots
    optimal_lots = int(risk_amount / risk_per_lot)
    optimal_lots = max(1, min(optimal_lots, max_lots))  # Between 1 and max
    
    # Calculate total margin required
    margin_per_lot = leverage_config["margin_per_lot"]
    total_margin = optimal_lots * margin_per_lot
    
    # Calculate effective leverage
    position_value = optimal_lots * lot_size * entry_price
    effective_leverage = position_value / total_margin if total_margin > 0 else 1
    
    return {
        "symbol": symbol,
        "optimal_lots": optimal_lots,
        "risk_amount": risk_amount,
        "risk_per_lot": risk_per_lot,
        "total_margin": total_margin,
        "position_value": position_value,
        "effective_leverage": effective_leverage,
        "margin_usage_pct": (total_margin / capital) * 100,
        "lot_size": lot_size
    }

def get_leverage_summary(symbol: str) -> str:
    """Get a human-readable summary of leverage settings for a symbol."""
    config = MCX_LEVERAGE_CONFIG.get(symbol)
    if not config:
        return f"No leverage config found for {symbol}"
    
    return f"""
{symbol} LEVERAGE SUMMARY
{'=' * 50}
Lot Size: {config['lot_size']} units
Risk Per Trade: {config['risk_per_trade_pct']*100:.1f}% of capital
Max Trades/Day: {config['max_trades_per_day']}
Max Open Positions: {config['max_open_positions']}
Effective Leverage: {config['effective_leverage']}x
Margin Per Lot: INR {config['margin_per_lot']:,}
Max Position Size: {config['max_position_size']} lots
Volatility Multiplier: {config['volatility_multiplier']}x
Max Hold Time: {config['max_hold_time_minutes']} minutes

OUTER SHELL THRESHOLDS:
Min Volume: {config.get('min_volume', 'N/A')}
Min OI: {config.get('min_oi', 'N/A')}
Max Spread: {config.get('max_spread_pct', 'N/A')}%
Max Strike Distance: {config.get('max_strike_distance_pct', 'N/A')}%
Min Liquidity Score: {config.get('min_liquidity_score', 'N/A')}/10

Description: {config['description']}
"""

if __name__ == "__main__":
    # Test leverage calculations
    print("MCX LEVERAGE CONFIGURATION SUMMARY")
    print("=" * 60)
    
    for symbol in ["CRUDEOIL", "NATGAS", "GOLDM", "SILVERM"]:
        print(get_leverage_summary(symbol))
        print()
    
    # Test position sizing
    print("\nPOSITION SIZING CALCULATION TEST")
    print("=" * 60)
    
    capital = 100000
    entry_price = 262.00
    sl_price = 222.70  # 15% SL
    
    position_size = calculate_position_size("CRUDEOIL", entry_price, sl_price, capital)
    print(f"\nCRUDEOIL Position Sizing (Capital: INR {capital:,}):")
    print(f"  Entry: INR {entry_price:.2f}")
    print(f"  Stop Loss: INR {sl_price:.2f}")
    print(f"  Optimal Lots: {position_size['optimal_lots']}")
    print(f"  Risk Amount: INR {position_size['risk_amount']:.2f}")
    print(f"  Total Margin: INR {position_size['total_margin']:.2f}")
    print(f"  Effective Leverage: {position_size['effective_leverage']:.1f}x")
    print(f"  Margin Usage: {position_size['margin_usage_pct']:.1f}%")
