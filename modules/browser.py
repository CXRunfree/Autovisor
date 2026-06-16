import os


def get_effective_driver(config_driver: str, env=None) -> str:
    env = os.environ if env is None else env
    driver = env.get("AUTOVISOR_DRIVER", config_driver)
    return driver.strip().lower()


def resolve_browser_channel(driver: str) -> str | None:
    driver = driver.lower()
    if driver == "edge":
        return "msedge"
    if driver == "chromium":
        return None
    return driver


def resolve_executable_path(driver: str, configured_path: str) -> str | None:
    path = configured_path.strip().strip("\"'")
    if not path or driver == "chromium":
        return None
    if path.endswith(".app"):
        app_name = os.path.splitext(os.path.basename(path))[0]
        return os.path.join(path, "Contents", "MacOS", app_name)
    return path
