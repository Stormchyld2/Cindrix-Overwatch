"""The Overwatch PIN for the Watchtower tab: stored as a salted hash (never the PIN itself), with a wait after too many wrong tries."""

import hashlib
import hmac
import os
import time

ITERATIONS = 200_000
MAX_TRIES = 5
WAIT_SECONDS = 60
MIN_LEN = 4


def make_hash(pin, salt=None):
    salt = salt or os.urandom(16)
    return salt.hex(), hashlib.pbkdf2_hmac("sha256", pin.encode("utf-8"), salt, ITERATIONS).hex()


def check_hash(pin, salt_hex, hash_hex):
    try:
        h = hashlib.pbkdf2_hmac("sha256", pin.encode("utf-8"), bytes.fromhex(salt_hex), ITERATIONS).hex()
    except ValueError:
        return False
    return hmac.compare_digest(h, hash_hex)


def valid_pin(pin):
    """None when the PIN is fine, otherwise the problem in plain words."""
    if len(pin) < MIN_LEN:
        return f"Use at least {MIN_LEN} digits."
    if not pin.isdigit():
        return "Use digits only."
    return None


class Throttle:
    """Counts wrong tries and says how long to wait. `now` is injectable for tests."""

    def __init__(self, tries=0, until=0.0):
        self.tries, self.until = tries, until

    def wait(self, now=None):
        left = self.until - (now if now is not None else time.time())
        return max(0, int(left + 0.999)) if left > 0 else 0

    def wrong(self, now=None):
        self.tries += 1
        if self.tries >= MAX_TRIES:
            self.tries = 0
            self.until = (now if now is not None else time.time()) + WAIT_SECONDS

    def right(self):
        self.tries, self.until = 0, 0.0
