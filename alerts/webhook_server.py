"""
V9 Strategy Webhook Server for TradingView Alerts

Receives alerts from TradingView and sends notifications via:
- Telegram (recommended - free, instant)
- Discord
- Pushover
- Email

Setup:
1. Choose notification method and configure credentials below
2. Run: python -m alerts.webhook_server
3. Use ngrok to expose: ngrok http 5000
4. Add webhook URL to TradingView alert
"""

import os
import requests
from datetime import datetime
from flask import Flask, request, jsonify
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)

# ============================================================================
# CONFIGURATION - Set your preferred notification method
# ============================================================================

# Telegram (Recommended - Free & Instant)
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN', '')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID', '')

# Discord
DISCORD_WEBHOOK_URL = os.getenv('DISCORD_WEBHOOK_URL', '')

# Pushover (Paid - $5 one-time)
PUSHOVER_USER_KEY = os.getenv('PUSHOVER_USER_KEY', '')
PUSHOVER_API_TOKEN = os.getenv('PUSHOVER_API_TOKEN', '')

# ============================================================================
# NOTIFICATION FUNCTIONS
# ============================================================================

def send_telegram(message: str, parse_mode: str = 'HTML') -> bool:
    """Send notification via Telegram bot."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("Telegram not configured")
        return False

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        'chat_id': TELEGRAM_CHAT_ID,
        'text': message,
        'parse_mode': parse_mode
    }

    try:
        response = requests.post(url, json=payload, timeout=10)
        return response.status_code == 200
    except Exception as e:
        print(f"Telegram error: {e}")
        return False


def send_discord(message: str) -> bool:
    """Send notification via Discord webhook."""
    if not DISCORD_WEBHOOK_URL:
        print("Discord not configured")
        return False

    payload = {'content': message}

    try:
        response = requests.post(DISCORD_WEBHOOK_URL, json=payload, timeout=10)
        return response.status_code in [200, 204]
    except Exception as e:
        print(f"Discord error: {e}")
        return False


def send_pushover(message: str, title: str = "V9 Alert") -> bool:
    """Send notification via Pushover."""
    if not PUSHOVER_USER_KEY or not PUSHOVER_API_TOKEN:
        print("Pushover not configured")
        return False

    url = "https://api.pushover.net/1/messages.json"
    payload = {
        'token': PUSHOVER_API_TOKEN,
        'user': PUSHOVER_USER_KEY,
        'message': message,
        'title': title,
        'priority': 1,  # High priority
        'sound': 'cashregister'
    }

    try:
        response = requests.post(url, data=payload, timeout=10)
        return response.status_code == 200
    except Exception as e:
        print(f"Pushover error: {e}")
        return False


def send_all_notifications(message: str):
    """Send to all configured notification channels."""
    results = []

    if TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID:
        results.append(('Telegram', send_telegram(message)))

    if DISCORD_WEBHOOK_URL:
        results.append(('Discord', send_discord(message)))

    if PUSHOVER_USER_KEY and PUSHOVER_API_TOKEN:
        results.append(('Pushover', send_pushover(message)))

    return results


# ============================================================================
# WEBHOOK ENDPOINTS
# ============================================================================

@app.route('/webhook', methods=['POST'])
def webhook():
    """Receive TradingView webhook alerts."""
    try:
        # TradingView sends JSON or plain text
        if request.is_json:
            data = request.get_json()
        else:
            data = {'message': request.data.decode('utf-8')}

        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        # Parse the alert message
        message = data.get('message', str(data))

        # Format notification
        notification = f"""
🚨 <b>V9 TRADING ALERT</b> 🚨
━━━━━━━━━━━━━━━━━━
{message}
━━━━━━━━━━━━━━━━━━
⏰ {timestamp}
"""

        # Log the alert
        print(f"\n{'='*50}")
        print(f"ALERT RECEIVED: {timestamp}")
        print(f"{'='*50}")
        print(message)
        print(f"{'='*50}\n")

        # Send notifications
        results = send_all_notifications(notification)

        for channel, success in results:
            status = "✓" if success else "✗"
            print(f"  {status} {channel}")

        return jsonify({'status': 'success', 'results': results}), 200

    except Exception as e:
        print(f"Webhook error: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500


@app.route('/health', methods=['GET'])
def health():
    """Health check endpoint."""
    return jsonify({
        'status': 'running',
        'telegram': bool(TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID),
        'discord': bool(DISCORD_WEBHOOK_URL),
        'pushover': bool(PUSHOVER_USER_KEY and PUSHOVER_API_TOKEN)
    })


@app.route('/test', methods=['GET'])
def test():
    """Send a test notification."""
    test_message = """
🧪 <b>TEST ALERT</b> 🧪
━━━━━━━━━━━━━━━━━━
V9 LONG: ES @ 6950.00
Entry: 6950.00
Stop: 6945.50
Risk: 4.5 pts
4R Target: 6968.00
━━━━━━━━━━━━━━━━━━
⏰ Test sent successfully!
"""
    results = send_all_notifications(test_message)
    return jsonify({'status': 'test_sent', 'results': results})


# ============================================================================
# MAIN
# ============================================================================

if __name__ == '__main__':
    print("""
╔══════════════════════════════════════════════════════════════╗
║           V9 Strategy Webhook Server                        ║
╠══════════════════════════════════════════════════════════════╣
║  Endpoints:                                                  ║
║    POST /webhook  - Receive TradingView alerts              ║
║    GET  /health   - Check server status                     ║
║    GET  /test     - Send test notification                  ║
╠══════════════════════════════════════════════════════════════╣
║  Notification Status:                                        ║
""")
    print(f"║    Telegram: {'✓ Configured' if TELEGRAM_BOT_TOKEN else '✗ Not configured':20}           ║")
    print(f"║    Discord:  {'✓ Configured' if DISCORD_WEBHOOK_URL else '✗ Not configured':20}           ║")
    print(f"║    Pushover: {'✓ Configured' if PUSHOVER_USER_KEY else '✗ Not configured':20}           ║")
    print("""╠══════════════════════════════════════════════════════════════╣
║  Next Steps:                                                 ║
║    1. Run: ngrok http 5000                                  ║
║    2. Copy ngrok URL (e.g., https://abc123.ngrok.io)        ║
║    3. Add to TradingView alert webhook URL                  ║
╚══════════════════════════════════════════════════════════════╝
""")

    app.run(host='0.0.0.0', port=5000, debug=True)
