import unittest

from modules.lesson_navigation import (
    FUSION_CATALOG,
    HIKE_CATALOG,
    WISDOM_CATALOG,
    WISDOM_MOOC_CATALOG,
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
            catalog_candidates("https://wisdom-mooc.zhihuishu.com/study/index")[0],
            WISDOM_MOOC_CATALOG,
        )

    def test_wisdom_mooc_catalog_covers_nested_lessons(self):
        # 分节容器 .chapter-item 本身不是课时, 真正的课时在其 .chapter-content-second 子节点;
        # 只有不含子节容器的 .chapter-item 才能作为独立课时。
        self.assertIn(".chapter-content-second", WISDOM_MOOC_CATALOG.item)
        self.assertIn(":not(:has(.chapter-content-second))", WISDOM_MOOC_CATALOG.item)
        self.assertEqual(WISDOM_MOOC_CATALOG.active_class, "current")
        self.assertEqual(WISDOM_MOOC_CATALOG.title, ".item-name")

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
