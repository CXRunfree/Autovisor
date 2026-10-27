import unittest

from modules.ai_smart import (
    build_targets,
    incomplete_targets,
    is_ai_smart_url,
    parse_clock,
    parse_percent,
    parse_segment_range,
)


class AiSmartTests(unittest.TestCase):
    def test_detects_only_the_ai_smart_host(self):
        self.assertTrue(
            is_ai_smart_url(
                "https://ai-smart-course-student-pro.zhihuishu.com/"
                "singleCourse/knowledgeStudy/1/2"
            )
        )
        self.assertFalse(
            is_ai_smart_url("https://example.com/ai-smart-course-student-pro.zhihuishu.com")
        )
        self.assertFalse(is_ai_smart_url("https://fusioncourseh5.zhihuishu.com/x"))
        self.assertFalse(is_ai_smart_url(None))

    def test_parses_progress_and_clock_values(self):
        self.assertEqual(parse_percent("学习进度 100%"), 100)
        self.assertEqual(parse_percent("学习进度 9.8%"), 9)
        self.assertEqual(parse_percent("not started"), 0)
        self.assertEqual(parse_clock("05:00"), 300)
        self.assertEqual(parse_clock("01:02:03"), 3723)
        self.assertIsNone(parse_clock("bad"))

    def test_parses_video_segment_range(self):
        self.assertEqual(parse_segment_range("00:00-05:00"), (0, 300))
        self.assertEqual(
            parse_segment_range("01:02:03 - 01:05:00"),
            (3723, 3900),
        )
        self.assertEqual(parse_segment_range("no range"), (None, None))

    def test_flattens_outline_and_filters_completed_targets(self):
        outline = {
            "modules": [
                {
                    "title": "导热基本定律及稳态导热",
                    "units": [
                        {
                            "title": "导热微分方程及定解条件",
                            "items": [
                                {
                                    "title": "直角坐标系中的导热微分方程",
                                    "progress": "学习进度 100%",
                                },
                                {
                                    "title": "导热微分方程",
                                    "progress": "学习进度 35%",
                                },
                            ],
                        }
                    ],
                }
            ]
        }
        targets = build_targets(outline)
        self.assertEqual(len(targets), 2)
        self.assertEqual(targets[0].progress, 100)
        self.assertEqual(targets[1].progress, 35)
        self.assertEqual(targets[1].label, "导热基本定律及稳态导热 / 导热微分方程及定解条件 / 导热微分方程")
        self.assertEqual(incomplete_targets(outline), [targets[1]])


if __name__ == "__main__":
    unittest.main()
