import unittest

from modules.lesson_navigation import (
    FUSION_CATALOG,
    HIKE_CATALOG,
    WISDOM_CATALOG,
    catalog_candidates,
    has_class,
    parse_progress_value,
)


class LessonNavigationTests(unittest.TestCase):
    def test_current_wisdom_selectors_match_live_catalog(self):
        self.assertEqual(WISDOM_CATALOG.item, ".child-info.hasvideo")
        self.assertEqual(WISDOM_CATALOG.active, ".child-info.hasvideo.current")
        self.assertEqual(WISDOM_CATALOG.finish, ".child-check")
        self.assertEqual(WISDOM_CATALOG.progress_attribute, "aria-valuenow")

    def test_catalog_url_hints_only_change_detection_priority(self):
        self.assertIs(
            catalog_candidates("https://fusioncourseh5.zhihuishu.com/x")[0],
            FUSION_CATALOG,
        )
        self.assertEqual(
            catalog_candidates("https://hike.zhihuishu.com/x"),
            (HIKE_CATALOG,),
        )

    def test_progress_parser_clamps_and_rejects_non_finite_values(self):
        cases = {
            None: 0,
            "": 0,
            "69.9": 69,
            "100": 100,
            "101": 100,
            "-3": 0,
            "nan": 0,
            "inf": 0,
        }
        for value, expected in cases.items():
            with self.subTest(value=value):
                self.assertEqual(parse_progress_value(value), expected)

    def test_active_class_is_token_aware(self):
        self.assertTrue(has_class("child-info current cur hasvideo", "current"))
        self.assertFalse(has_class("child-info current-next", "current"))


if __name__ == "__main__":
    unittest.main()
