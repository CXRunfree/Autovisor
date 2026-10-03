import io
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from PIL import Image
from playwright.async_api import TimeoutError

from modules import vision_verification as vision


class VisionPointTests(unittest.TestCase):
    def test_scaled_offset_image_coordinates(self):
        point = vision.parse_point('说明\n```json\n{"center_px":[500,250],"uncertain":false}\n```')
        self.assertEqual(vision.to_page_point(point, (1000, 1000), {
            "x": 600, "y": 300, "width": 400, "height": 200,
        }), (800, 350))

    def test_rejects_uncertain_outside_and_invalid_coordinates(self):
        for content in (
            '{"center_px":[100,50],"uncertain":true}',
            '{"center_px":[1000,50],"uncertain":false}',
            '{"center_px":[100,-1],"uncertain":false}',
            '{"center_px":[true,50],"uncertain":false}',
            '{"center_px":[NaN,50],"uncertain":false}',
            '{"center_px":null,"uncertain":false}',
            '{"center_px":[100,50]}',
        ):
            with self.subTest(content=content), self.assertRaises(ValueError):
                vision.parse_point(content)

    def test_cannot_click_edges_or_refresh_control(self):
        box = {"x": 10, "y": 20, "width": 320, "height": 160}
        self.assertEqual(vision.safe_image_point((500, 500), box), (170, 100))
        for point in ((1, 500), (990, 100), (999, 999)):
            with self.subTest(point=point), self.assertRaises(ValueError):
                vision.safe_image_point(point, box)


class VisionAttemptTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.page = MagicMock()
        self.page.mouse.click = AsyncMock()
        self.logger = MagicMock()
        self.dialog = MagicMock()
        self.dialog.inner_text = AsyncMock(return_value="请点击蓝色立方体")
        self.dialog.is_visible = AsyncMock(return_value=True)
        self.dialog.wait_for = AsyncMock()
        self.image = MagicMock()
        self.image.get_attribute = AsyncMock(return_value="https://image.example/challenge.png")
        self.image.bounding_box = AsyncMock(return_value={
            "x": 100, "y": 200, "width": 320, "height": 160,
        })
        png = io.BytesIO()
        Image.new("RGB", (320, 160), "white").save(png, format="PNG")
        self.image.screenshot = AsyncMock(return_value=png.getvalue())
        self.response = MagicMock(status_code=200)
        self.response.json.return_value = {"choices": [{"message": {
            "content": '{"center_px":[500,500],"uncertain":false}',
        }}]}
        self.client = MagicMock()
        self.client.post = AsyncMock(return_value=self.response)
        context = MagicMock()
        context.__aenter__ = AsyncMock(return_value=self.client)
        context.__aexit__ = AsyncMock(return_value=False)
        for patcher in (
            patch.object(vision, "api_key", AsyncMock(return_value="test-token")),
            patch.object(vision, "visible_locator", AsyncMock(
                side_effect=[self.dialog, self.image] * 3)),
            patch.object(vision.httpx, "AsyncClient", return_value=context),
            patch.object(vision.asyncio, "sleep", AsyncMock()),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    async def test_success_requires_dialog_to_disappear(self):
        self.assertTrue(await vision.attempt_course_verification(self.page, self.logger))
        self.page.mouse.click.assert_awaited_once_with(260, 280)
        self.dialog.wait_for.assert_awaited_once_with(state="hidden", timeout=6000)

    async def test_api_error_does_not_click_or_log_secret_response(self):
        self.response.status_code = 401
        self.response.text = "test-token private response"
        self.assertFalse(await vision.attempt_course_verification(self.page, self.logger))
        self.page.mouse.click.assert_not_awaited()
        self.assertNotIn("test-token", str(self.logger.mock_calls))
        self.assertNotIn("private response", str(self.logger.mock_calls))

    async def test_stale_image_is_never_clicked(self):
        self.image.get_attribute.side_effect = ["old", "new"] * 3
        self.assertFalse(await vision.attempt_course_verification(self.page, self.logger))
        self.page.mouse.click.assert_not_awaited()
        self.assertEqual(self.client.post.await_count, 3)

    async def test_failed_challenge_stops_after_three_attempts(self):
        self.dialog.wait_for.side_effect = TimeoutError("still visible")
        self.assertFalse(await vision.attempt_course_verification(self.page, self.logger))
        self.assertEqual(self.client.post.await_count, 3)
        self.assertEqual(self.page.mouse.click.await_count, 3)

    async def test_uncertain_model_response_never_clicks(self):
        self.response.json.return_value["choices"][0]["message"]["content"] = (
            '{"center_px":null,"uncertain":true}'
        )
        self.assertFalse(await vision.attempt_course_verification(self.page, self.logger))
        self.page.mouse.click.assert_not_awaited()


class CredentialsTests(unittest.IsolatedAsyncioTestCase):
    async def test_environment_key_does_not_access_keychain(self):
        with patch.dict(vision.os.environ, {"DEEPSEEK_API_KEY": "test-token"}), \
                patch.object(vision.asyncio, "create_subprocess_exec", AsyncMock()) as process:
            self.assertEqual(await vision.api_key(), "test-token")
            process.assert_not_awaited()

    async def test_missing_key_on_windows_falls_back_without_subprocess(self):
        with patch.dict(vision.os.environ, {}, clear=True), \
                patch.object(vision.sys, "platform", "win32"), \
                patch.object(vision.asyncio, "create_subprocess_exec", AsyncMock()) as process:
            with self.assertRaises(RuntimeError):
                await vision.api_key()
            process.assert_not_awaited()
