import time

class RiskManager:

    def __init__(self, capital=100000, risk_per_trade_pct=1, max_daily_loss_pct=3):

        self.capital = capital

        # Risk settings
        self.risk_per_trade = capital * (risk_per_trade_pct / 100)
        self.max_daily_loss = capital * (max_daily_loss_pct / 100)

        # Tracking
        self.daily_loss = 0
        self.trade_count = 0
        self.max_trades_per_day = 5

        # Control
        self.stop_trading = False

        print(f"""
[RISK MANAGER INIT]

Capital: {self.capital}
Risk/Trade: {self.risk_per_trade}
Max Daily Loss: {self.max_daily_loss}
""")

    # -----------------------------------
    # 1. AUTO LOT SIZE CALCULATOR
    # -----------------------------------
    def calculate_lot_size(self, stop_loss_points, lot_size_unit=1):

        if stop_loss_points <= 0:
            return 0

        qty = self.risk_per_trade / stop_loss_points

        # round to nearest lot
        qty = int(qty // lot_size_unit) * lot_size_unit

        return max(qty, lot_size_unit)

    # -----------------------------------
    # 2. UPDATE TRADE RESULT
    # -----------------------------------
    def update_trade(self, pnl):

        self.trade_count += 1

        if pnl < 0:
            self.daily_loss += abs(pnl)

        print(f"""
[RISK UPDATE]

Trade #: {self.trade_count}
PnL: {pnl}
Daily Loss: {self.daily_loss}
""")

        # check limits
        self.check_limits()

    # -----------------------------------
    # 3. CHECK LIMITS (KILL SWITCH)
    # -----------------------------------
    def check_limits(self):

        if self.daily_loss >= self.max_daily_loss:
            print(" MAX DAILY LOSS HIT - STOP TRADING")
            self.stop_trading = True

        if self.trade_count >= self.max_trades_per_day:
            print(" MAX TRADES REACHED - STOP TRADING")
            self.stop_trading = True

    # -----------------------------------
    # 4. CAN TAKE TRADE?
    # -----------------------------------
    def can_trade(self):

        return not self.stop_trading

    # -----------------------------------
    # 5. RESET DAILY (CALL ONCE PER DAY)
    # -----------------------------------
    def reset_daily(self):

        print(" Resetting daily risk limits")

        self.daily_loss = 0
        self.trade_count = 0
        self.stop_trading = False