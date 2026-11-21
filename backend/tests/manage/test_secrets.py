import re

import pytest

from app.manage.auth_admin import hidden_email
from app.manage.secrets_gen import is_weak_pin, new_pin, new_temp_password


@pytest.mark.parametrize("pin", ["000000", "123456", "654321", "111222", "121212", "123123", "112211", "999999",
                                 "234567", "987654", "12345", "1234567", "12a456"])
def test_weak_pins(pin):
    assert is_weak_pin(pin)


@pytest.mark.parametrize("pin", ["284719", "503826", "917364"])
def test_ok_pins(pin):
    assert not is_weak_pin(pin)


def test_new_pin_never_weak():
    pins = {new_pin() for _ in range(400)}
    assert all(len(p) == 6 and p.isdigit() and not is_weak_pin(p) for p in pins)
    assert len(pins) > 350


def test_temp_password():
    for _ in range(200):
        p = new_temp_password()
        assert len(p) == 12 and re.search(r"\d", p) and re.search(r"[a-z]", p) and re.search(r"[A-Z]", p)
        assert not set(p) & set("0O1lI")


def test_hidden_email():
    assert hidden_email("SH-0412", "shree", "employees.kaarigar.app") == "sh-0412@shree.employees.kaarigar.app"
