"""
Trade Notification System - Telegram, Discord, Email

Sends real-time alerts for:
- Trade entries
- Trade exits (with P/L)
- Daily summaries
- Errors/warnings
"""
import os
import requests
from datetime import datetime
from typing import Optional
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables
_env_path = Path(__file__).parent.parent / "config" / ".env"
load_dotenv(_env_path)


class TelegramNotifier:
    """Send notifications via Telegram bot."""

    def __init__(self, bot_token: str = None, chat_id: str = None):
        self.bot_token = bot_token or os.getenv("TELEGRAM_BOT_TOKEN")
        self.chat_id = chat_id or os.getenv("TELEGRAM_CHAT_ID")
        self.enabled = bool(self.bot_token and self.chat_id)

        if not self.enabled:
            print("Telegram notifications disabled (no token/chat_id)")

    def send(self, message: str, parse_mode: str = "HTML") -> bool:
        """Send a message to Telegram."""
        if not self.enabled:
            return False

        try:
            url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
            data = {
                "chat_id": self.chat_id,
                "text": message,
                "parse_mode": parse_mode,
            }
            response = requests.post(url, data=data, timeout=10)
            return response.status_code == 200
        except Exception as e:
            print(f"Telegram error: {e}")
            return False

    def notify_entry(self, symbol: str, direction: str, entry_type: str,
                     entry_price: float, stop_price: float, contracts: int,
                     risk_pts: float) -> bool:
        """Send trade entry notification."""
        emoji = "🟢" if direction == "LONG" else "🔴"
        msg = f"""
{emoji} <b>ICT V10.9 | NEW TRADE - {symbol}</b>

<b>Direction:</b> {direction}
<b>Type:</b> {entry_type}
<b>Entry:</b> ${entry_price:,.2f}
<b>Stop:</b> ${stop_price:,.2f}
<b>Risk:</b> {risk_pts:.2f} pts
<b>Size:</b> {contracts} contracts

⏰ {datetime.now().strftime('%H:%M:%S')} ET
"""
        return self.send(msg.strip())

    def notify_exit(self, symbol: str, direction: str, exit_type: str,
                    exit_price: float, pnl: float, contracts: int) -> bool:
        """Send trade exit notification."""
        emoji = "✅" if pnl > 0 else "❌"
        pnl_emoji = "💰" if pnl > 0 else "📉"
        msg = f"""
{emoji} <b>ICT V10.9 | TRADE EXIT - {symbol}</b>

<b>Direction:</b> {direction}
<b>Exit Type:</b> {exit_type}
<b>Exit Price:</b> ${exit_price:,.2f}
<b>Contracts:</b> {contracts}
{pnl_emoji} <b>P/L:</b> ${pnl:+,.2f}

⏰ {datetime.now().strftime('%H:%M:%S')} ET
"""
        return self.send(msg.strip())

    def notify_daily_summary(self, trades: int, wins: int, losses: int,
                             total_pnl: float, symbols_traded: list) -> bool:
        """Send end-of-day summary."""
        win_rate = (wins / trades * 100) if trades > 0 else 0
        emoji = "🎉" if total_pnl > 0 else "😔"
        msg = f"""
{emoji} <b>ICT V10.9 | DAILY SUMMARY</b>

<b>Trades:</b> {trades}
<b>Wins:</b> {wins} | <b>Losses:</b> {losses}
<b>Win Rate:</b> {win_rate:.1f}%
<b>Symbols:</b> {', '.join(symbols_traded)}

💵 <b>Total P/L:</b> ${total_pnl:+,.2f}

📅 {datetime.now().strftime('%Y-%m-%d')}
"""
        return self.send(msg.strip())

    def notify_error(self, error_msg: str) -> bool:
        """Send error notification."""
        msg = f"""
⚠️ <b>ICT V10.9 | ERROR</b>

{error_msg}

⏰ {datetime.now().strftime('%H:%M:%S')} ET
"""
        return self.send(msg.strip())

    def notify_status(self, status: str) -> bool:
        """Send status update."""
        msg = f"""
ℹ️ <b>ICT V10.9 | STATUS</b>

{status}

⏰ {datetime.now().strftime('%H:%M:%S')} ET
"""
        return self.send(msg.strip())


class DiscordNotifier:
    """Send notifications via Discord webhook."""

    def __init__(self, webhook_url: str = None):
        self.webhook_url = webhook_url or os.getenv("DISCORD_WEBHOOK_URL")
        self.enabled = bool(self.webhook_url)

        if not self.enabled:
            print("Discord notifications disabled (no webhook URL)")

    def send(self, message: str) -> bool:
        """Send a message to Discord."""
        if not self.enabled:
            return False

        try:
            data = {"content": message}
            response = requests.post(self.webhook_url, json=data, timeout=10)
            return response.status_code in [200, 204]
        except Exception as e:
            print(f"Discord error: {e}")
            return False


# Global notifier instance
_notifier: Optional[TelegramNotifier] = None


def get_notifier() -> TelegramNotifier:
    """Get or create the global notifier instance."""
    global _notifier
    if _notifier is None:
        _notifier = TelegramNotifier()
    return _notifier


def notify_entry(symbol: str, direction: str, entry_type: str,
                 entry_price: float, stop_price: float, contracts: int,
                 risk_pts: float) -> bool:
    """Convenience function for trade entry notification."""
    return get_notifier().notify_entry(
        symbol, direction, entry_type, entry_price, stop_price, contracts, risk_pts
    )


def notify_exit(symbol: str, direction: str, exit_type: str,
                exit_price: float, pnl: float, contracts: int) -> bool:
    """Convenience function for trade exit notification."""
    return get_notifier().notify_exit(
        symbol, direction, exit_type, exit_price, pnl, contracts
    )


def notify_daily_summary(trades: int, wins: int, losses: int,
                         total_pnl: float, symbols_traded: list) -> bool:
    """Convenience function for daily summary notification."""
    return get_notifier().notify_daily_summary(
        trades, wins, losses, total_pnl, symbols_traded
    )


def notify_error(error_msg: str) -> bool:
    """Convenience function for error notification."""
    return get_notifier().notify_error(error_msg)


def notify_status(status: str) -> bool:
    """Convenience function for status notification."""
    return get_notifier().notify_status(status)


if __name__ == "__main__":
    # Test notifications
    notifier = TelegramNotifier()

    if notifier.enabled:
        print("Testing Telegram notifications...")
        notifier.notify_status("Paper Trading bot started!")
        notifier.notify_entry("ES", "LONG", "CREATION", 6950.25, 6945.00, 3, 5.25)
        notifier.notify_exit("ES", "LONG", "T1_4R", 6971.25, 787.50, 1)
        notifier.notify_daily_summary(5, 4, 1, 2150.00, ["ES", "NQ"])
        print("Test notifications sent!")
    else:
        print("Telegram not configured. Add to config/.env:")
        print("  TELEGRAM_BOT_TOKEN=your_bot_token")
        print("  TELEGRAM_CHAT_ID=your_chat_id")
