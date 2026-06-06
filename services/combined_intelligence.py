class CombinedIntelligence:

    def __init__(self):
        pass

    def combine(self, nse_signal=None, mcx_signal=None):

        confidence = 0
        action = None
        reasons = []

        # -------------------------
        # NSE SIGNAL (weight = 0.6 - stronger driver)
        # -------------------------
        if nse_signal:
            confidence += 0.6
            action = nse_signal.get("action")
            reasons.append("NSE")

        # -------------------------
        # MCX SIGNAL (weight = 0.4 - confirmation filter)
        # -------------------------
        if mcx_signal:
            confidence += 0.4
            reasons.append("MCX")

            # Conflict check
            if action and action != mcx_signal.get("action"):
                return {
                    "action": None,
                    "confidence": 0,
                    "reason": "Conflict NSE vs MCX"
                }

            action = mcx_signal.get("action")

        return {
            "action": action,
            "confidence": confidence,
            "reason": " + ".join(reasons)
        }