import importlib
import sys
import unittest


class LessonNavigationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        sys.modules.pop("modules.lesson_navigation", None)
        cls.navigation = importlib.import_module("modules.lesson_navigation")

    def test_completed_lesson_advances_to_next_lesson_even_when_active_class_changed(self):
        next_index = self.navigation.next_lesson_index(2, 5)

        self.assertEqual(next_index, 3)

    def test_unconfirmed_lesson_does_not_advance(self):
        next_index = self.navigation.next_lesson_index(2, 5, lesson_completed=False)

        self.assertEqual(next_index, 2)

    def test_completed_last_lesson_advances_to_end_marker(self):
        next_index = self.navigation.next_lesson_index(4, 5)

        self.assertEqual(next_index, 5)

    def test_end_marker_reports_all_lessons_finished(self):
        self.assertTrue(self.navigation.is_finished(5, 5))

    def test_course_with_unconfirmed_lesson_is_not_complete(self):
        self.assertFalse(self.navigation.course_is_complete(False))

    def test_course_with_confirmed_lessons_is_complete(self):
        self.assertTrue(self.navigation.course_is_complete(True))

    def test_middle_index_reports_more_lessons_remaining(self):
        self.assertFalse(self.navigation.is_finished(3, 5))

    def test_standard_selectors_use_legacy_catalog(self):
        selectors = self.navigation.get_catalog_selectors(False, False)

        self.assertEqual(selectors.item, ".clearfix.video")
        self.assertEqual(selectors.active, ".current_play")
        self.assertEqual(selectors.finish, ".time_icofinish")

    def test_new_version_selectors_use_chapter_content_second(self):
        selectors = self.navigation.get_catalog_selectors(True, False)

        self.assertEqual(selectors.item, ".chapter-content-second")
        self.assertEqual(selectors.active, ".chapter-content-second.current")
        self.assertEqual(selectors.finish, ".finish-icon")

    def test_new_version_active_class_is_current(self):
        self.assertEqual(self.navigation.get_active_class(True, False), "current")

    def test_hike_active_class_is_active(self):
        self.assertEqual(self.navigation.get_active_class(False, True), "active")

    def test_class_match_requires_whole_class_name(self):
        self.assertTrue(self.navigation.has_class("chapter-content-second current", "current"))
        self.assertFalse(self.navigation.has_class("chapter-content-second not-current", "current"))

    def test_parse_progress_value_clamps_to_percent_range(self):
        self.assertEqual(self.navigation.parse_progress_value("13"), 13)
        self.assertEqual(self.navigation.parse_progress_value("99.8"), 99)
        self.assertEqual(self.navigation.parse_progress_value("-5"), 0)
        self.assertEqual(self.navigation.parse_progress_value("120"), 100)
        self.assertEqual(self.navigation.parse_progress_value(None), 0)


if __name__ == "__main__":
    unittest.main()
