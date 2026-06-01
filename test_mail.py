#!/usr/bin/env python3
"""Test your email (SMTP) configuration.

Usage:
    python test_mail.py your_email@example.com

Reads MAIL_* settings from .env (or the environment) and tries to send a
single test message. Prints a clear success or failure reason.
"""
import sys
from pathlib import Path

# Load .env from this folder
try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent / ".env")
except ImportError:
    print("Tip: pip install python-dotenv  (so .env is loaded automatically)")

import mailer  # noqa: E402


def main():
    if len(sys.argv) < 2:
        print("Usage: python test_mail.py recipient@example.com")
        sys.exit(1)
    recipient = sys.argv[1]

    print("\nChecking configuration…")
    if not mailer.init_mail():
        print("\nFAILED: mail is not configured. Set MAIL_USERNAME and "
              "MAIL_PASSWORD in your .env file.")
        sys.exit(1)

    print(f"\nSending a test email to {recipient} …")
    err = mailer.send_test_email(recipient)
    if err is None:
        print(f"\n✓ SUCCESS — a test email was sent to {recipient}.")
        print("  Check the inbox (and spam folder). Your OTP delivery is working.")
    else:
        print(f"\n✗ FAILED — {err}")
        print("\nCommon fixes:")
        print("  • Use a Gmail App Password (16 chars), NOT your normal password.")
        print("  • Enable 2-Step Verification, then create an App Password at:")
        print("        https://myaccount.google.com/apppasswords")
        print("  • Make sure outbound port 587 is not blocked by your network.")
        sys.exit(1)


if __name__ == "__main__":
    main()
