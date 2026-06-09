"""
Example Usage of MCX Sentiment Service
Shows how to use the plug-and-play MCX sentiment service
"""

from services.mcx_sentiment_service.service import get_mcx_sentiment_service

def example_usage():
    """Example of how to use MCX Sentiment Service"""
    
    # Get the service instance
    mcx_service = get_mcx_sentiment_service()
    
    # Check if service is enabled
    if not mcx_service.is_enabled():
        print("MCX sentiment service is disabled")
        return
    
    # Get overall MCX sentiment
    overall_sentiment = mcx_service.get_mcx_sentiment()
    print(f"Overall MCX Sentiment: {overall_sentiment}")
    
    # Get sentiment for specific symbol
    crude_sentiment = mcx_service.get_mcx_sentiment("CRUDEOIL")
    print(f"CRUDEOIL Sentiment: {crude_sentiment}")
    
    # Get MCX confirmation for NSE trade
    nse_call_confirmation = mcx_service.get_sentiment_for_nse_confirmation("CALL")
    print(f"NSE CALL Confirmation: {nse_call_confirmation}")
    
    nse_put_confirmation = mcx_service.get_sentiment_for_nse_confirmation("PUT")
    print(f"NSE PUT Confirmation: {nse_put_confirmation}")
    
    # Get service status
    status = mcx_service.get_status()
    print(f"Service Status: {status}")
    
    # Enable/disable service dynamically
    # mcx_service.disable()
    # mcx_service.enable()

if __name__ == "__main__":
    example_usage()
