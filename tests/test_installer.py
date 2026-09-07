import unittest
from types import SimpleNamespace

from modules.installer import is_compatible_wheel, validate_python_version, wheel_tags


class InstallerTests(unittest.TestCase):
    def test_rejects_unsupported_python_version(self):
        with self.assertRaises(RuntimeError):
            validate_python_version(SimpleNamespace(major=3, minor=13))

    def test_accepts_supported_python_versions(self):
        for minor in (10, 11, 12):
            validate_python_version(SimpleNamespace(major=3, minor=minor))

    def test_parses_wheel_tags(self):
        self.assertEqual(
            wheel_tags("numpy-1.26.4-cp311-cp311-win_amd64.whl"),
            ("1.26.4", "cp311", "cp311", "win_amd64"),
        )

    def test_requires_matching_python_abi_and_platform(self):
        self.assertTrue(is_compatible_wheel(
            "numpy-1.26.4-cp311-cp311-win_amd64.whl",
            "numpy", "1.26.4", "cp311", "cp311", "win_amd64",
        ))
        self.assertFalse(is_compatible_wheel(
            "numpy-1.26.4-cp310-cp310-win_amd64.whl",
            "numpy", "1.26.4", "cp311", "cp311", "win_amd64",
        ))

    def test_accepts_opencv_abi3_wheel(self):
        self.assertTrue(is_compatible_wheel(
            "opencv_python-4.10.0.82-cp37-abi3-win_amd64.whl",
            "opencv-python", "4.10.0.82", "cp311", "cp311", "win_amd64",
        ))


if __name__ == "__main__":
    unittest.main()
