#!/usr/bin/env python3
"""Run an authenticated HTTP smoke check against a real SocialFish process."""

from __future__ import annotations

import argparse
import os
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
from http.cookiejar import CookieJar
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import HTTPCookieProcessor, Request, build_opener

REPO_ROOT = Path(__file__).resolve().parents[1]
WORKING_ROOT = REPO_ROOT / ".maestro" / "playbooks" / "Working"
USERNAME = "ui-smoke-user"
PASSWORD = "ui-smoke-pass"
STARTUP_TIMEOUT_SECONDS = 30


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _request(opener, url: str, data: dict[str, str] | None = None) -> tuple[int, str]:
    body = None
    headers = {}
    if data is not None:
        body = urlencode(data).encode("utf-8")
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    request = Request(url, data=body, headers=headers)
    try:
        with opener.open(request, timeout=10) as response:
            return response.getcode(), response.read().decode("utf-8", errors="replace")
    except HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", errors="replace")


def _wait_for_app(opener, base_url: str, process: subprocess.Popen, timeout: int) -> None:
    deadline = time.time() + timeout
    last_error = None
    while time.time() < deadline:
        if process.poll() is not None:
            output = process.stdout.read() if process.stdout else ""
            raise RuntimeError(
                "SocialFish exited before startup completed with code {}.\n{}".format(
                    process.returncode,
                    output[-4000:],
                )
            )
        try:
            status, body = _request(opener, base_url + "/neptune")
            if status == 200 and 'name="email"' in body and 'name="password"' in body:
                return
        except (ConnectionError, TimeoutError, URLError, OSError) as exc:
            last_error = exc
        time.sleep(0.5)
    process.terminate()
    try:
        output, _ = process.communicate(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        output, _ = process.communicate(timeout=5)
    raise TimeoutError(
        "Timed out waiting for SocialFish startup. Last error: {}\n{}".format(
            last_error,
            (output or "")[-4000:],
        )
    )


def _demo_campaign_id(db_path: Path) -> int:
    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            "SELECT id FROM simulation_campaigns WHERE slug = ?",
            ("authorized-training-demo",),
        ).fetchone()
    if not row:
        raise AssertionError("Seeded authorized-training-demo campaign was not found.")
    return int(row[0])


def _assert_route(opener, base_url: str, path: str, expected_text: str) -> None:
    status, body = _request(opener, base_url + path)
    if status != 200:
        raise AssertionError("{} returned HTTP {}.".format(path, status))
    if expected_text not in body:
        excerpt = body[:500].replace("\n", " ")
        raise AssertionError(
            "{} did not contain expected text {!r}. Body starts with: {}".format(
                path,
                expected_text,
                excerpt,
            )
        )


def run_smoke() -> list[str]:
    WORKING_ROOT.mkdir(parents=True, exist_ok=True)
    port = _free_port()
    base_url = "http://127.0.0.1:{}".format(port)
    checked_routes: list[str] = []

    with tempfile.TemporaryDirectory(
        prefix="ui-smoke-",
        dir=str(WORKING_ROOT),
        ignore_cleanup_errors=True,
    ) as temp_dir:
        temp_path = Path(temp_dir)
        (temp_path / "templates" / "static" / "token").mkdir(parents=True, exist_ok=True)
        db_path = temp_path / "socialfish-ui-smoke.db"

        env = os.environ.copy()
        env.update(
            {
                "PYTHONUNBUFFERED": "1",
                "SOCIALFISH_DATABASE": str(db_path),
                "SOCIALFISH_HOST": "127.0.0.1",
                "SOCIALFISH_PORT": str(port),
                "SOCIALFISH_SECRET_KEY": "ui-smoke-secret-key",
            }
        )

        process = subprocess.Popen(
            [sys.executable, str(REPO_ROOT / "SocialFish.py"), USERNAME, PASSWORD],
            cwd=str(temp_path),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )

        try:
            opener = build_opener(HTTPCookieProcessor(CookieJar()))
            _wait_for_app(opener, base_url, process, STARTUP_TIMEOUT_SECONDS)

            status, body = _request(
                opener,
                base_url + "/neptune",
                {"email": USERNAME, "password": PASSWORD},
            )
            if status != 200 or "Unauthorized" in body:
                raise AssertionError("Login through /neptune failed with HTTP {}.".format(status))

            campaign_id = _demo_campaign_id(db_path)
            route_expectations = [
                ("/simulations", "Simulation Center"),
                ("/simulations/campaigns", "Campaign Management"),
                ("/simulations/campaigns/{}".format(campaign_id), "Campaign Metrics"),
                ("/simulations/ai-builder", "AI Scenario Builder"),
                ("/ai-settings", "AI Provider Configuration"),
                ("/simulations/metrics", "Simulation Metrics"),
                ("/integrations/directory", "Directory Provider Settings"),
                ("/audit-log", "Audit Log"),
            ]
            for path, expected_text in route_expectations:
                _assert_route(opener, base_url, path, expected_text)
                checked_routes.append(path)
            return checked_routes
        finally:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=10)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    checked_routes = run_smoke()
    print("UI smoke passed: checked {}".format(", ".join(checked_routes)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
