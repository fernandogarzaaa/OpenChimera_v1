import os
import smtplib
from email.message import EmailMessage
from dotenv import load_dotenv

# Path to the isolated secrets file
secrets_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), '.env.secrets')

def get_secret(key):
    """Safely fetch a secret from the isolated .env.secrets file"""
    load_dotenv(secrets_path, override=True)
    val = os.getenv(key)
    if key in os.environ:
        del os.environ[key]  # Hide from subprocess env dumps
    return val

def send_gmail(to_address, subject, body):
    """Send an email using the secure bridge Gmail credentials."""
    user = get_secret("GMAIL_USER")
    password = get_secret("GMAIL_APP_PASSWORD")
    
    if not user or not password:
        return {"status": "error", "message": "Gmail credentials not configured or missing."}
        
    msg = EmailMessage()
    msg.set_content(body)
    msg['Subject'] = subject
    msg['From'] = user
    msg['To'] = to_address
    
    try:
        server = smtplib.SMTP_SSL('smtp.gmail.com', 465)
        server.login(user, password)
        server.send_message(msg)
        server.quit()
        return {"status": "success", "message": f"Email successfully sent to {to_address}"}
    except Exception as e:
        return {"status": "error", "message": f"SMTP Error: {str(e)}\nNote: Gmail usually requires an App Password, not a standard login password, when 2FA is enabled."}

def get_solana_keypair():
    """Returns the loaded Solana Keypair object without exposing the string to logs."""
    try:
        from solders.keypair import Keypair
        from base58 import b58decode
    except ImportError:
        return {"status": "error", "message": "Solana SDK packages (solders, base58) not installed. Please run: pip install solana solders base58"}

    priv_key_str = get_secret("SOLANA_PRIVATE_KEY")
    if not priv_key_str:
        return {"status": "error", "message": "Solana private key not configured."}
        
    try:
        raw_bytes = b58decode(priv_key_str)
        keypair = Keypair.from_bytes(raw_bytes)
        return {"status": "success", "keypair": keypair, "public_key": str(keypair.pubkey())}
    except Exception as e:
        return {"status": "error", "message": f"Key decoding error: {str(e)}"}

def test_bridge():
    """Verifies that the bridge is functioning without returning sensitive data."""
    gmail_user = get_secret("GMAIL_USER")
    sol_pub = get_secret("SOLANA_PUBLIC_KEY")
    
    return {
        "status": "active",
        "gmail_configured_for": gmail_user if gmail_user else "None",
        "solana_configured_for": sol_pub if sol_pub else "None",
    }

if __name__ == "__main__":
    print("--- CHIMERA Secure Bridge ---")
    print(test_bridge())
