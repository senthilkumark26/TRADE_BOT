# Consensus Service

**Version:** 1.0.0  
**Protection Level:** CRITICAL  
**Status:** PRODUCTION READY

## Overview

Consensus Service that coordinates between independent services for trade decisions. Implements a consensus-based architecture where multiple services must agree before the LLM makes the final decision.

## Architecture

### Service Flow
```
1. Market Analyzer Service → Identifies potential strikes (PCR/OI/VWAP analysis)
2. Breakout Entry Service → Identifies entry timing (breakout detection)
3. Consensus Service → Finds common strikes and validates agreement
4. LLM Analyzer → Makes final YES/NO decision on consensus strikes
```

### Dependencies
- market_analyzer_service
- breakout_entry_service

### Dependents
- llm_analyzer
- trading_bot

## Capabilities

- **Consensus Building**: Finds agreement between independent services
- **Strike Agreement**: Identifies strikes both services recommend
- **Confidence Scoring**: Calculates overall consensus confidence
- **LLM Payload Preparation**: Formats data for LLM final decision
- **Service Coordination**: Manages communication between services

## API Methods

### `find_consensus(market_analysis, breakout_analysis)`
Find consensus between market analyzer and breakout service.

**Parameters:**
- `market_analysis` (Dict): Results from Market Analyzer Service
- `breakout_analysis` (Dict): Results from Breakout Entry Service

**Returns:**
- Dictionary with consensus strikes and confidence levels

### `prepare_llm_payload(consensus_result)`
Prepare payload for LLM final decision.

**Parameters:**
- `consensus_result` (Dict): Results from consensus analysis

**Returns:**
- Dictionary formatted for LLM analysis

## Consensus Logic

### Strike Agreement
- Market Analyzer identifies potential strikes based on PCR/OI/VWAP
- Breakout Service identifies entry timing and strike selection
- Consensus Service finds strikes both services agree on (within tolerance)

### Confidence Scoring
- Market confidence (60% weight): Based on PCR bias, OI analysis, VWAP position
- Breakout confidence (40% weight): Based on breakout strength and entry type
- Overall consensus confidence: Weighted average

### LLM Review Threshold
- Confidence ≥ 0.8: High priority LLM review
- Confidence ≥ 0.6: Standard LLM review
- Confidence < 0.6: Reject (insufficient consensus)

## Usage Example

```python
from services.consensus_service import ConsensusService
from services.market_analyzer_service import MarketAnalyzerService
from services.breakout_entry_service import BreakoutEntryService

# Initialize services
market_service = MarketAnalyzerService()
breakout_service = BreakoutEntryService()
consensus_service = ConsensusService()

# Run independent analysis
market_analysis = market_service.analyze_market(
    symbol="NIFTY", spot_price=23400.0, vwap=23380.0,
    price_change=5.0, delta_oi=15000, pcr=1.2,
    option_chain=option_chain_data
)

breakout_analysis = {
    "breakout": "BULLISH",
    "strength": "STRONG",
    "entry_decision": {"signal": "BUY CE", "entry_type": "EARLY", "strike": "OTM"}
}

# Find consensus
consensus_result = consensus_service.find_consensus(market_analysis, breakout_analysis)

# Prepare for LLM
llm_payload = consensus_service.prepare_llm_payload(consensus_result)
```

## Benefits of Consensus Architecture

1. **Independent Analysis**: Services analyze independently without bias
2. **Error Reduction**: Multiple services must agree, reducing false signals
3. **Specialization**: Each service focuses on its expertise
4. **Scalability**: Easy to add more services to consensus
5. **Final Authority**: LLM makes final decision with full context

## Service Info

```python
service_info = consensus_service.get_service_info()
```

Returns:
```json
{
    "service_name": "consensus_service",
    "version": "1.0.0",
    "dependencies": ["market_analyzer_service", "breakout_entry_service"],
    "dependents": ["llm_analyzer", "trading_bot"],
    "protection_level": "CRITICAL",
    "capabilities": [
        "consensus_building",
        "strike_agreement",
        "confidence_scoring",
        "llm_payload_preparation",
        "service_coordination"
    ]
}
```

## Future Enhancements

- Add more services to consensus (volatility, liquidity, etc.)
- Implement weighted voting based on service accuracy
- Add service health monitoring
- Implement fallback mechanisms if services fail
