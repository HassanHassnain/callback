"""Keycloak runs as UID 1000, separate from agent tools (1100)."""

import json
import os
import subprocess
import time
from pathlib import Path

import httpx

config = json.loads(Path("/tmp/callback/server-bootstrap.json").read_text())
Path("/opt/keycloak/data/import").mkdir(parents=True, exist_ok=True)
Path("/opt/keycloak/data/import/" + config["realm"] + "-realm.json").write_text(json.dumps(config["realm_import"]))
env = {**os.environ, "KC_BOOTSTRAP_ADMIN_USERNAME": "callback-twin",
       "KC_BOOTSTRAP_ADMIN_PASSWORD": config["admin_password"]}
server = subprocess.Popen(["/opt/keycloak/bin/kc.sh", "start", "--optimized", "--http-enabled=true",
    "--hostname-strict=false", "--cache=local", "--import-realm"], env=env, stdout=Path("/tmp/callback/server.log").open("w"), stderr=subprocess.STDOUT)
try:
    with httpx.Client(trust_env=False, timeout=2) as client:
        for _ in range(1200):
            if server.poll() is not None:
                raise SystemExit(server.returncode)
            try:
                response = client.get("http://127.0.0.1:8080/realms/" + config["realm"])
                if response.is_success:
                    break
            except httpx.HTTPError:
                pass
            time.sleep(0.1)
        else:
            raise SystemExit("Twin Keycloak did not become ready")
    with httpx.Client(base_url="http://127.0.0.1:8080", trust_env=False, timeout=20) as client:
        response = client.post("/realms/master/protocol/openid-connect/token", data={
            "grant_type": "password", "client_id": "admin-cli", "username": "callback-twin",
            "password": config["admin_password"]})
        response.raise_for_status()
        response = client.put("/admin/realms/" + config["realm"] + "/users/profile",
            headers={"Authorization": "Bearer " + response.json()["access_token"]}, json=config["user_profile"])
        response.raise_for_status()
    Path("/tmp/callback/server-ready").touch()
    raise SystemExit(server.wait())
finally:
    if server.poll() is None:
        server.terminate()
