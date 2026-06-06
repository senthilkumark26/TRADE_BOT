from services.combined_intelligence import CombinedIntelligence

ci_engine = CombinedIntelligence()

def get_combined_signal(nse_signal, mcx_signal):
    return ci_engine.combine(nse_signal, mcx_signal)