from telethon import TelegramClient, events
from .signal_adapter import adapt_signal
import time

class TelegramService:

    def __init__(self, api_id, api_hash, group_id, execution_brain=None, signal_callback=None, signal_received_callback=None, kite_client=None, session_file=None):
        session_name = session_file if session_file else "tg_session"
        self.client = TelegramClient(session_name, api_id, api_hash)
        self.group_id = group_id
        self.execution_brain = execution_brain
        self.signal_callback = signal_callback  # Direct callback for telegram-only bot
        self.signal_received_callback = signal_received_callback  # Callback when signal is received (for CSV logging)
        self.kite_client = kite_client  # Kite client for symbol lookup
        
        # Safety features
        self.recent_signals = set()
        self.signal_timeout = 300  # 5 minutes
        
        # Signal tracking
        self.signal_stats = {
            "received": 0,
            "valid": 0,
            "invalid": 0,
            "duplicates": 0,
            "expired": 0,
            "executed": 0
        }

    def _is_duplicate_signal(self, signal):
        """Check if signal is a duplicate"""
        signal_key = f"{signal['symbol']}_{signal['strike']}_{signal['option_type']}"
        
        if signal_key in self.recent_signals:
            return True
        
        self.recent_signals.add(signal_key)
        
        # Clean old signals from set (prevent memory leak)
        if len(self.recent_signals) > 100:
            self.recent_signals.clear()
        
        return False

    def _is_expired_signal(self, signal):
        """Check if signal is too old"""
        if "timestamp" not in signal:
            return False
        
        signal_age = time.time() - signal["timestamp"]
        return signal_age > self.signal_timeout

    def _update_stats(self, stat_type):
        """Update signal statistics"""
        if stat_type in self.signal_stats:
            self.signal_stats[stat_type] += 1

    def get_stats(self):
        """Get current signal statistics"""
        return self.signal_stats

    async def start(self):

        @self.client.on(events.NewMessage(chats=self.group_id))
        async def handler(event):

            message = event.raw_text
            self._update_stats("received")
            print(f"[TG RECEIVED] {message}")

            # Step 1: Adapt + Validate
            signal = adapt_signal(message, self.kite_client)

            if not signal:
                self._update_stats("invalid")
                print("[TG SKIPPED] Invalid signal format")
                return

            # Add timestamp
            signal["timestamp"] = time.time()
            self._update_stats("valid")
            print(f"[TG VALID SIGNAL] {signal}")
            
            # Call signal received callback (for CSV logging)
            if self.signal_received_callback:
                self.signal_received_callback(signal)

            # Step 2: Check for duplicates
            if self._is_duplicate_signal(signal):
                self._update_stats("duplicates")
                print("[TG SKIPPED] Duplicate signal")
                return

            # Step 3: Check for expired signals
            if self._is_expired_signal(signal):
                self._update_stats("expired")
                print("[TG SKIPPED] Expired signal")
                return

            # Step 4: Send to Execution Brain OR callback
            try:
                if self.execution_brain:
                    # Integrated mode: Use Execution Brain
                    decision = self.execution_brain.process_external_signal(signal)
                    
                    if decision.get("action") == "EXECUTE":
                        self._update_stats("executed")
                    
                    print(f"[TG DECISION] {decision}")
                elif self.signal_callback:
                    # Telegram-only mode: Direct callback
                    self.signal_callback(signal)
                    self._update_stats("executed")
                    print(f"[TG CALLBACK] Signal sent to callback")
                else:
                    print("[TG WARNING] No execution method configured")
                
            except Exception as e:
                print(f"[TG ERROR] Execution failed: {e}")

        await self.client.start()
        print("[TG SERVICE STARTED]")
        print(f"Listening to group: {self.group_id}")
        print(f"Signal timeout: {self.signal_timeout} seconds")
        await self.client.run_until_disconnected()
