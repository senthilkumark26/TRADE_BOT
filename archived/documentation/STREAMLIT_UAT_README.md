# Streamlit Single Strike Trader - UAT Validation

## 🚀 Overview

Real-time trading dashboard with second-by-second sync with Zerodha API for UAT (User Acceptance Testing) validation.

## ✨ Features

### 📊 Real-Time Data
- ✅ **Second-by-second sync** with Zerodha API
- ✅ **Live spot prices** from Zerodha
- ✅ **Live option chain** from Zerodha
- ✅ **Real VWAP** calculated by Engine1
- ✅ **No mock data** - 100% live API

### 🔧 Engine Integration
- ✅ **Engine1 (Fast Market Analyzer)**
  - Real-time VWAP from price history
  - PCR (Put-Call Ratio) analysis
  - Build-up pattern detection
  - Strike-wise OI confluence

- ✅ **LLM (Human Sentiment)**
  - Ollama integration
  - Trade validation (TAKE/SKIP)
  - Exit decision analysis
  - Confidence scoring

### 💰 Capital Management
- ✅ 30k investment
- ✅ Affordability check
- ✅ Position sizing
- ✅ P&L tracking
- ✅ Capital protection

## 📋 Installation

### Install Dependencies
```bash
pip install -r requirements_streamlit.txt
```

### Required Files
- `config.json` - Zerodha API credentials
- `option_token_map.json` - Pre-loaded option instruments
- `single_strike_trader.py` - Trading logic
- `streamlit_single_strike_trader.py` - Streamlit interface

## 🚀 Running the App

### Method 1: Using Launcher (Recommended)
```bash
python run_streamlit_trader.py
```

### Method 2: Direct Streamlit
```bash
streamlit run streamlit_single_strike_trader.py
```

### Method 3: Custom Port
```bash
streamlit run streamlit_single_strike_trader.py --server.port 8502
```

## 📱 Dashboard Sections

### 1. Status Bar
- **Status**: Running/Stopped
- **Current Capital**: Real-time capital
- **Total Trades**: Trade count
- **Total P&L**: Overall profit/loss

### 2. Current Trade
- **Symbol**: Current instrument
- **Strike**: Option strike
- **Direction**: CALL/PUT
- **Entry Price**: Trade entry
- **Current Price**: Live option price
- **P&L**: Real-time profit/loss
- **Target/SL**: Risk management

### 3. Market Data
- Real-time spot prices
- VWAP for each instrument
- Timestamp of last update

### 4. Trade History
- All executed trades
- Entry/exit prices
- P&L per trade
- Trade duration

### 5. System Logs
- Real-time activity log
- Engine1 signals
- LLM validations
- Trade executions

### 6. Engine Status
- Engine1 status
- LLM status
- Data source status

## ⚙️ Configuration

### Investment Amount
- Default: ₹30,000
- Range: ₹10,000 - ₹1,000,000
- Adjustable via sidebar

### Auto Start
- Enable to auto-start trading on load
- Disabled by default

## 🔐 Security Notes

### UAT Validation Mode
- ✅ **NO DEMO MODE** - Live trading only
- ✅ Real Zerodha API credentials
- ✅ Real capital at risk
- ⚠️ **USE AT YOUR OWN RISK**

### Before UAT Validation
1. Test thoroughly in paper trading mode
2. Validate all engine signals
3. Verify LLM integration
4. Test capital management
5. Ensure proper risk management

## 📊 UAT Validation Checklist

### Data Validation
- [ ] Spot prices match Zerodha
- [ ] Option prices match Zerodha
- [ ] VWAP calculated correctly
- [ ] PCR analysis accurate
- [ ] Build-up detection working

### Engine Validation
- [ ] Engine1 generates signals
- [ ] LLM validates signals
- [ ] Affordability check working
- [ ] Trade execution correct
- [ ] SL/TP triggers properly

### Integration Validation
- [ ] Second-by-second sync working
- [ ] No data lag
- [ ] No API errors
- [ ] No connection drops
- [ ] Auto-recovery working

### Risk Management
- [ ] Capital protection active
- [ ] Position sizing correct
- [ ] SL/TP calculated properly
- [ ] P&L tracking accurate
- [ ] Trade history complete

## 🐛 Troubleshooting

### Streamlit Not Starting
```bash
# Check if Streamlit is installed
pip show streamlit

# Reinstall if needed
pip install --upgrade streamlit
```

### Zerodha API Errors
- Check API credentials in `config.json`
- Verify access token is valid
- Check API rate limits
- Ensure market hours

### Engine1 Not Generating Signals
- Check option chain data loading
- Verify VWAP calculation
- Check PCR analysis
- Ensure price history is building

### LLM Not Working
- Check Ollama is running
- Verify model is downloaded
- Check connection to localhost:11434
- Review LLM logs

## 📈 Performance Optimization

### Reduce API Calls
- Increase batch size for option chain
- Reduce refresh interval (default: 2 seconds)
- Cache market data

### Memory Management
- Limit log history (last 20)
- Limit trade history display
- Clear old data periodically

## 🔧 Customization

### Add New Instruments
Edit `config.json`:
```json
{
  "instruments": {
    "NEW_SYMBOL": {
      "instrument_token": "12345678",
      "lot_size": 100
    }
  }
}
```

### Change LLM Model
Edit `config.json`:
```json
{
  "ollama": {
    "default_model": "phi3:mini"
  }
}
```

### Adjust Refresh Rate
Edit `streamlit_single_strike_trader.py`:
```python
time.sleep(2)  # Change to desired seconds
```

## 📞 Support

### Logs
- Check Streamlit logs in terminal
- Review system logs in dashboard
- Check Engine1 logs
- Review LLM logs

### Debug Mode
Enable detailed logging:
```python
logging.basicConfig(level=logging.DEBUG)
```

## ⚠️ Disclaimer

**THIS IS FOR UAT VALIDATION ONLY**

- Real money at risk
- No guarantee of profit
- Use proper risk management
- Test thoroughly before live trading
- Monitor trades actively

## 📄 License

Internal use only - UAT validation purposes
