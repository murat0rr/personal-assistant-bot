from datetime import UTC, datetime

from src.handlers.f_reminders import _haversine_m, _is_within_radius
from src.models.reminder import Reminder

# Красная площадь и Кремль — известное небольшое расстояние (~350-400 м).
_RED_SQUARE = (55.7539, 37.6208)
_KREMLIN = (55.7520, 37.6175)


def _reminder(lat: float, lon: float, radius_m: int = 200) -> Reminder:
    return Reminder(
        id=1,
        text="тест",
        schedule_kind="location",
        schedule_value={"place_name": "тест", "lat": lat, "lon": lon, "radius_m": radius_m},
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
    )


def test_haversine_same_point_is_zero():
    assert _haversine_m(55.75, 37.62, 55.75, 37.62) == 0


def test_haversine_known_distance_approx():
    distance = _haversine_m(*_RED_SQUARE, *_KREMLIN)
    assert 200 < distance < 500


def test_within_radius_when_close():
    r = _reminder(*_RED_SQUARE, radius_m=200)
    # Точка в паре метров от центра.
    assert _is_within_radius(r, 55.7540, 37.6209) is True


def test_not_within_radius_when_far():
    r = _reminder(*_RED_SQUARE, radius_m=200)
    assert _is_within_radius(r, *_KREMLIN) is False


def test_missing_coordinates_never_matches():
    r = Reminder(
        id=1,
        text="тест",
        schedule_kind="location",
        schedule_value={"place_name": "где-то"},
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    assert _is_within_radius(r, 55.75, 37.62) is False
