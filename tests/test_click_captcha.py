import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGES = ROOT / "packages"
if PACKAGES.exists():
    sys.path.insert(0, str(PACKAGES))

from modules.click_captcha import find_click_point, parse_click_instruction
from modules.tasks import VERIFICATION_SELECTORS

try:
    import cv2
    import numpy as np
except ImportError:
    cv2 = None
    np = None

COLOR_FIXTURE = ROOT / "tests" / "fixtures" / "color_click_captcha.png"
SIDEWAYS_FIXTURE = ROOT / "tests" / "fixtures" / "sideways_b_captcha.png"
GRAY_FIXTURE = ROOT / "tests" / "fixtures" / "gray_v_captcha.png"


class ClickInstructionTests(unittest.TestCase):
    def test_parses_same_color_digit_prompt(self):
        parsed = parse_click_instruction("请点击大写W颜色一样的数字4")
        self.assertEqual(
            parsed,
            {"mode": "same_color", "ref": "W", "target": "4", "color": None},
        )

    def test_parses_named_color_prompt(self):
        parsed = parse_click_instruction("请点击红色的数字7")
        self.assertEqual(
            parsed,
            {"mode": "named_color", "ref": None, "target": "7", "color": "红色"},
        )

    def test_parses_gray_letter_prompt(self):
        parsed = parse_click_instruction("请点击灰色小写v")
        self.assertEqual(
            parsed,
            {"mode": "named_color", "ref": None, "target": "v", "color": "灰色"},
        )

    def test_parses_sideways_letter_prompt(self):
        parsed = parse_click_instruction("请点击侧向的小写b")
        self.assertEqual(
            parsed,
            {
                "mode": "orientation",
                "orientation": "sideways",
                "target": "b",
                "ref": None,
                "color": None,
            },
        )

    def test_ignores_unrelated_text(self):
        self.assertIsNone(parse_click_instruction("请完成安全验证"))

    def test_course_selectors_include_tencent_iframe(self):
        self.assertTrue(
            any("tcaptcha" in selector for selector in VERIFICATION_SELECTORS)
        )


@unittest.skipIf(cv2 is None or np is None, "opencv/numpy 未安装")
class ClickPointTests(unittest.TestCase):
    def _draw_puzzle(self):
        from PIL import Image, ImageDraw, ImageFont

        image = Image.new("RGB", (320, 160), (220, 220, 220))
        draw = ImageDraw.Draw(image)
        try:
            font = ImageFont.truetype(r"C:\Windows\Fonts\arialbd.ttf", 48)
        except OSError:
            font = ImageFont.load_default()
        draw.text((28, 28), "4", fill=(255, 210, 40), font=font)
        draw.text((118, 32), "W", fill=(255, 205, 35), font=font)
        draw.text((40, 92), "7", fill=(220, 50, 45), font=font)
        draw.text((128, 90), "4", fill=(235, 110, 145), font=font)
        draw.text((190, 88), "K", fill=(230, 120, 130), font=font)
        return cv2.cvtColor(np.array(image), cv2.COLOR_RGB2BGR)

    def test_picks_same_color_digit_on_synthetic_puzzle(self):
        image = self._draw_puzzle()
        point = find_click_point(
            image, "请点击大写W颜色一样的数字4", np, cv2
        )
        self.assertIsNotNone(point)
        x, y = point
        self.assertLess(x, 100, f"should click yellow 4 on the left, got {point}")
        self.assertLess(y, 85, f"should click the upper yellow 4, got {point}")

    def test_picks_yellow_four_on_live_tencent_screenshot(self):
        if not COLOR_FIXTURE.exists():
            self.skipTest("missing captcha fixture")
        image = cv2.imread(str(COLOR_FIXTURE))
        self.assertIsNotNone(image)
        point = find_click_point(
            image, "请点击大写W颜色一样的数字4", np, cv2
        )
        self.assertIsNotNone(point)
        x, y = point
        # Live sample: yellow 4 around (55, 58); pink 4 around (133, 118).
        self.assertLess(x, 90, f"clicked the wrong 4 at {point}")
        self.assertLess(y, 90, f"clicked the lower pink 4 at {point}")
        self.assertGreater(x, 35)
        self.assertGreater(y, 35)

    def test_picks_sideways_b_not_upright_b(self):
        if not SIDEWAYS_FIXTURE.exists():
            self.skipTest("missing captcha fixture")
        image = cv2.imread(str(SIDEWAYS_FIXTURE))
        self.assertIsNotNone(image)
        point = find_click_point(image, "请点击侧向的小写b", np, cv2)
        self.assertIsNotNone(point)
        x, y = point
        # Live sample: sideways blue b around (206, 86); upright green b around (252, 116).
        self.assertGreater(x, 170, f"should click the sideways b, got {point}")
        self.assertLess(x, 230, f"should not click the upright green b, got {point}")
        self.assertGreater(y, 60)
        self.assertLess(y, 110)

    def test_picks_gray_v_not_colored_v(self):
        if not GRAY_FIXTURE.exists():
            self.skipTest("missing captcha fixture")
        image = cv2.imread(str(GRAY_FIXTURE))
        self.assertIsNotNone(image)
        point = find_click_point(image, "请点击灰色小写v", np, cv2)
        self.assertIsNotNone(point)
        x, y = point
        # Live sample: gray v in the MV pair around (90, 109); colored V is on the right.
        self.assertLess(x, 140, f"should click the gray v, got {point}")
        self.assertGreater(y, 80, f"should click the lower gray v, got {point}")


if __name__ == "__main__":
    unittest.main()
