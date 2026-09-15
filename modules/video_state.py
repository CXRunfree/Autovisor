import math


def is_valid_video_time(value) -> bool:
    return isinstance(value, (int, float)) and math.isfinite(value) and value >= 0


def has_valid_duration(value) -> bool:
    return is_valid_video_time(value) and value > 0


def video_at_end(current_time, duration, tolerance: float = 1.0) -> bool:
    if not is_valid_video_time(current_time) or not has_valid_duration(duration):
        return False
    return current_time >= duration - tolerance


def time_for_percent(duration, percent) -> float:
    if not has_valid_duration(duration):
        return 0.0
    try:
        bounded = max(0.0, min(float(percent), 100.0))
    except (TypeError, ValueError, OverflowError):
        return 0.0
    if not math.isfinite(bounded):
        return 0.0
    return duration * bounded / 100.0


def tail_retry_time(duration, tail_seconds: float = 5.0) -> float:
    if not has_valid_duration(duration):
        return 0.0
    return max(0.0, duration - tail_seconds)
