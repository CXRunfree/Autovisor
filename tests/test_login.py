import unittest

from modules.login import is_login_page
from modules.slider import image_to_display_point
from Autovisor import init_page


class LoginUrlTests(unittest.TestCase):
    def test_recognizes_current_and_legacy_login_hosts(self):
        self.assertTrue(is_login_page("https://login.zhihuishu.com/?origin=zhs"))
        self.assertTrue(is_login_page("https://passport.zhihuishu.com/login"))

    def test_rejects_authenticated_destination_hosts(self):
        self.assertFalse(is_login_page("https://www.zhihuishu.com/"))
        self.assertFalse(is_login_page("https://onlineweb.zhihuishu.com/"))

    def test_does_not_match_login_text_outside_the_hostname(self):
        self.assertFalse(is_login_page("https://example.com/login.zhihuishu.com"))

    def test_converts_opencv_point_to_display_coordinates(self):
        self.assertEqual(
            image_to_display_point((240, 120), 480, 240, 400, 200),
            (200, 100),
        )

    def test_browser_starts_maximized(self):
        args = init_page.__code__.co_consts
        self.assertIn("--start-maximized", args)
        self.assertIn("--window-position=0,0", args)
        self.assertIn(("viewport",), args)


if __name__ == "__main__":
    unittest.main()
