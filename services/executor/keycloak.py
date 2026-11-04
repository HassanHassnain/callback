"""Privileged Keycloak client. Imported only by executor-side code."""

import json
import ssl
import time
from pathlib import Path

import httpx


class KeycloakError(RuntimeError):
    pass


class Keycloak:
    def __init__(self, config, *, bootstrap=False):
        self.config = config
        self.credentials = json.loads(Path(config["credentials_path"]).read_text())
        self.bootstrap = bootstrap
        self.client = httpx.Client(base_url=config["prod_url"],
                                   verify=ssl.create_default_context(cafile=config["tls_ca"]),
                                   timeout=45, follow_redirects=False)
        self.tokens = {}

    def token(self, realm):
        realm = "master" if self.bootstrap else realm
        cached = self.tokens.get(realm)
        if cached and cached[1] > time.monotonic():
            return cached[0]
        body = {"grant_type": "password", "client_id": "admin-cli",
                "username": self.credentials["bootstrap_username"],
                "password": self.credentials["bootstrap_password"]} if self.bootstrap else {
                    "grant_type": "client_credentials", "client_id": "callback-executor",
                    "client_secret": self.credentials["client_secret"]}
        response = self.client.post(f"/realms/{realm}/protocol/openid-connect/token", data=body)
        if not response.is_success:
            raise KeycloakError(f"Keycloak authentication failed: HTTP {response.status_code}")
        data = response.json()
        self.tokens[realm] = (data["access_token"], time.monotonic() + data["expires_in"] - 20)
        return data["access_token"]

    def request(self, method, realm, endpoint="", *, body=None, params=None, missing=False):
        path = f"/admin/realms/{realm}" + ("/" + endpoint if endpoint else "")
        response = self.client.request(method, path, json=body, params=params,
                                       headers={"Authorization": "Bearer " + self.token(realm)})
        if missing and response.status_code == 404:
            return None
        if not response.is_success:
            raise KeycloakError(f"Keycloak {method} {endpoint or 'realm'}: HTTP {response.status_code}")
        return response.json() if response.content else None

    def list_all(self, realm, endpoint, **params):
        result = []
        first = 0
        while True:
            page = self.request("GET", realm, endpoint, params={"first": first, "max": 100, **params})
            if not isinstance(page, list):
                raise KeycloakError("Expected a list from paginated Keycloak endpoint")
            result.extend(page)
            if len(page) < 100:
                return result
            first += len(page)

    def create_realm(self, representation):
        response = self.client.post("/admin/realms", json=representation,
            headers={"Authorization": "Bearer " + self.token("master")})
        if not response.is_success:
            raise KeycloakError(f"Realm creation failed: HTTP {response.status_code}")


def config_from_file(path="/run/callback/config.json"):
    return json.loads(Path(path).read_text())
