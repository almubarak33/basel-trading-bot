from datetime import datetime

from app.session import NY, extended_scan_active, opening_delay_active, session_fraction


def at(hour, minute):
    return datetime(2024, 3, 4, hour, minute, tzinfo=NY)


def test_session_fraction_floors_before_open():
    assert session_fraction(at(9, 0)) == 0.05


def test_session_fraction_is_half_at_midday():
    assert session_fraction(at(12, 45)) == 0.5


def test_session_fraction_caps_after_close():
    assert session_fraction(at(17, 0)) == 1.0


def test_session_fraction_never_below_floor_just_after_open():
    assert session_fraction(at(9, 31)) == 0.05


def test_opening_delay_covers_only_the_first_minutes():
    assert opening_delay_active(at(9, 35), 10) is True
    assert opening_delay_active(at(9, 40), 10) is False
    assert opening_delay_active(at(9, 29), 10) is False


def test_extended_discovery_covers_pre_and_post_market():
    assert extended_scan_active(at(6, 0)) is True
    assert extended_scan_active(at(18, 0)) is True
    assert extended_scan_active(at(3, 59)) is False
    assert extended_scan_active(at(20, 0)) is False
