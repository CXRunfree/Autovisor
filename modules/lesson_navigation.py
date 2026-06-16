from dataclasses import dataclass
import math


@dataclass(frozen=True)
class CatalogSelectors:
    item: str
    active: str
    finish: str
    progress: str | None = None


def next_lesson_index(current_index: int, lesson_count: int, lesson_completed=True) -> int:
    if not lesson_completed:
        return current_index
    return min(current_index + 1, lesson_count)


def is_finished(current_index: int, lesson_count: int) -> bool:
    return current_index >= lesson_count


def course_is_complete(last_lesson_completed: bool) -> bool:
    return last_lesson_completed


def parse_progress_value(value) -> int:
    try:
        percent = int(float(value))
    except (TypeError, ValueError):
        return 0
    if not math.isfinite(percent):
        return 0
    return max(0, min(percent, 100))


def has_class(class_attr: str | None, class_name: str) -> bool:
    return class_name in (class_attr or "").split()


def get_active_class(is_new_version=False, is_hike_class=False) -> str:
    if is_hike_class:
        return "active"
    if is_new_version:
        return "current"
    return "current_play"


def get_catalog_selectors(is_new_version=False, is_hike_class=False) -> CatalogSelectors:
    if is_hike_class:
        return CatalogSelectors(".file-item", ".file-item.active", ".icon-finish", ".rate")
    if is_new_version:
        return CatalogSelectors(".chapter-content-second", ".chapter-content-second.current", ".finish-icon")
    return CatalogSelectors(".clearfix.video", ".current_play", ".time_icofinish", ".progress-num")
