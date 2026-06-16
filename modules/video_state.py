import math


def is_valid_video_time(value) -> bool:
    return isinstance(value, (int, float)) and math.isfinite(value) and value > 0


def should_refresh_video_duration(duration) -> bool:
    return not is_valid_video_time(duration)


def should_resume_paused_video(paused, current_time, duration, end_tolerance=1.0) -> bool:
    if not paused:
        return False
    if not is_valid_video_time(current_time) or not is_valid_video_time(duration):
        return True
    return current_time < duration - end_tolerance


def is_video_complete(current_time, duration, end_tolerance=1.0) -> bool:
    if not is_valid_video_time(current_time) or not is_valid_video_time(duration):
        return False
    return current_time >= duration - end_tolerance


def completion_settle_ms() -> int:
    return 3000


def replay_from_time(duration, tail_seconds=5.0) -> float:
    if not is_valid_video_time(duration):
        return 0
    return max(0, duration - tail_seconds)


def time_from_percent(duration, percent) -> float:
    if not is_valid_video_time(duration):
        return 0
    percent = max(0, min(float(percent), 100))
    return duration * percent / 100


def video_percent(current_time, duration) -> str:
    if not is_valid_video_time(current_time) or not is_valid_video_time(duration):
        return "0%"
    percent = int(current_time / duration * 100)
    return f"{max(0, min(percent, 100))}%"
