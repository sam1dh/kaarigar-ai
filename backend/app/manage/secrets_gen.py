"""PINs and temporary passwords. Shown once to the supervisor; never stored by Kaarigar (Supabase keeps a hash)."""
from __future__ import annotations

import secrets
import string

_WEAK = {"123456", "654321", "000000", "111111", "121212", "112233", "123123", "696969", "159753", "147258"}


def is_weak_pin(pin: str) -> bool:
    if len(pin) != 6 or not pin.isdigit() or pin in _WEAK:
        return True
    if len(set(pin)) <= 2:                                  # 111111, 121212, 112112
        return True
    d = [int(c) for c in pin]
    steps = {d[i + 1] - d[i] for i in range(5)}
    if steps in ({1}, {-1}):                                # 345678, 876543
        return True
    if pin[:3] == pin[3:]:                                  # 482482
        return True
    return False


def new_pin() -> str:
    while True:
        pin = "".join(secrets.choice(string.digits) for _ in range(6))
        if not is_weak_pin(pin):
            return pin


def new_temp_password() -> str:
    """12 characters, easy to read aloud: no 0/O, 1/l/I."""
    alphabet = "abcdefghijkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    while True:
        pw = "".join(secrets.choice(alphabet) for _ in range(12))
        if any(c.isdigit() for c in pw) and any(c.isupper() for c in pw) and any(c.islower() for c in pw):
            return pw
