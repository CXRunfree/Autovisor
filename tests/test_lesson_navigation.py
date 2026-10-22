import unittest

from modules.lesson_navigation import (
    FUSION_CATALOG,
    HIKE_CATALOG,
    MOOC_CATALOG,
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
        self.assertIs(
            catalog_candidates(
                "https://wisdom-mooc.zhihuishu.com/study/index?recruitAndCourseId=4e5a"
            )[0],
            MOOC_CATALOG,
        )
        self.assertIs(
            catalog_candidates("https://studyvideoh5.zhihuishu.com/x")[0],
            WISDOM_CATALOG,
        )

    def test_wisdom_mooc_catalog_uses_leaf_lessons_and_skips_tests(self):
        self.assertEqual(MOOC_CATALOG.name, "wisdom-mooc")
        self.assertIn(".course-catalog .chapter-item", MOOC_CATALOG.item)
        self.assertIn(":not(:has(.chapter-content-second))", MOOC_CATALOG.item)
        self.assertIn(".chapter-content-second", MOOC_CATALOG.item)
        self.assertNotIn("test-box", MOOC_CATALOG.item)
        self.assertEqual(MOOC_CATALOG.finish, ".finish-icon")
        self.assertEqual(MOOC_CATALOG.active_class, "current")
        self.assertTrue(MOOC_CATALOG.needs_expand)
        self.assertTrue(MOOC_CATALOG.handles_ai_exercise)
        self.assertTrue(FUSION_CATALOG.needs_expand)
        self.assertFalse(WISDOM_CATALOG.handles_ai_exercise)

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
