import unittest

from modules.login import is_login_page


class LoginUrlTests(unittest.TestCase):
    def test_recognizes_current_and_legacy_login_hosts(self):
        self.assertTrue(is_login_page("https://login.zhihuishu.com/?origin=zhs"))
        self.assertTrue(is_login_page("https://passport.zhihuishu.com/login"))

    def test_rejects_authenticated_destination_hosts(self):
        self.assertFalse(is_login_page("https://www.zhihuishu.com/"))
        self.assertFalse(is_login_page("https://onlineweb.zhihuishu.com/"))

    def test_does_not_match_login_text_outside_the_hostname(self):
        self.assertFalse(is_login_page("https://example.com/login.zhihuishu.com"))


if __name__ == "__main__":
    unittest.main()
