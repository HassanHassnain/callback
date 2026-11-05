"""Fixed read-only snapshot/browser helpers inside the untrusted twin."""

import argparse
import json
import sys
import uuid
from pathlib import Path

sys.path.insert(0, "/opt/callback")  # Fixed read-only source path, including under python -I.

import httpx
from playwright.sync_api import sync_playwright

from services.common.state import snapshot


class TwinKeycloak:
    def __init__(self):
        self.client = httpx.Client(base_url="http://127.0.0.1:8080", trust_env=False, timeout=20)
        creds = json.loads(Path("/audit/credentials.json").read_text())
        response = self.client.post("/realms/master/protocol/openid-connect/token", data={
            "grant_type": "password", "client_id": "admin-cli", "username": creds["username"],
            "password": creds["password"]})
        response.raise_for_status()
        self.token = response.json()["access_token"]
        self.realm = creds["realm"]

    def request(self, method, realm, endpoint="", *, params=None):
        response = self.client.request(method, f"/admin/realms/{realm}" + ("/" + endpoint if endpoint else ""),
            params=params, headers={"Authorization": "Bearer " + self.token})
        response.raise_for_status()
        return response.json()

    def list_all(self, realm, endpoint, **params):
        result, first = [], 0
        while True:
            page = self.request("GET", realm, endpoint, params={"first": first, "max": 100, **params})
            result.extend(page)
            if len(page) < 100:
                return result
            first += len(page)


def open_url(url):
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage",
            "--proxy-server=http://172.30.0.1:3128", "--proxy-bypass-list=localhost,127.0.0.1"])
        page = browser.new_page(viewport={"width": 1280, "height": 800})
        page.goto(url, timeout=20000, wait_until="domcontentloaded")
        path = "/tmp/callback/work/" + str(uuid.uuid4()) + ".png"
        page.screenshot(path=path)
        result = {"text": page.locator("body").inner_text()[:12000], "screenshot_path": path, "url": page.url}
        browser.close()
        return result


def admin_screenshot(config):
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage",
            "--proxy-server=http://172.30.0.1:3128", "--proxy-bypass-list=localhost,127.0.0.1"])
        page = browser.new_page(viewport={"width": 1440, "height": 960})
        url = "http://127.0.0.1:8080/admin/master/console/#/" + config["realm"] + "/users/" + config["user_id"] + "/credentials"
        page.goto(url, timeout=20000)
        page.locator("#username").fill("callback-twin")
        page.locator("#password").fill(config["password"])
        page.locator("#kc-login").click()
        page.get_by_text("Credentials", exact=True).first.wait_for(timeout=20000)
        path = "/tmp/callback/work/" + str(uuid.uuid4()) + ".png"
        page.screenshot(path=path)
        result = {"screenshot_path": path, "url": page.url, "text": page.locator("body").inner_text()[:12000]}
        browser.close()
        return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["snapshot", "open-url", "admin-screenshot"])
    parser.add_argument("--url")
    args = parser.parse_args()
    if args.command == "snapshot":
        kc = TwinKeycloak()
        print(json.dumps(snapshot(kc, kc.realm)))
    elif args.command == "open-url":
        print(json.dumps(open_url(args.url)))
    else:
        print(json.dumps(admin_screenshot(json.load(sys.stdin))))
