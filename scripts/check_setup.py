"""Read-only account and local secret preflight. Never prints credentials."""

import asyncio
import os
import stat
import subprocess
from pathlib import Path

import httpx
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]


async def main() -> int:
    env_path = ROOT / ".env"
    if not env_path.is_file():
        print("FAIL .env is missing")
        return 1
    if stat.S_IMODE(env_path.stat().st_mode) & 0o077:
        print("FAIL .env must be readable only by its owner (chmod 600 .env)")
        return 1
    load_dotenv(env_path)
    if subprocess.run(["git", "check-ignore", "-q", ".env"], cwd=ROOT).returncode:
        print("FAIL .env is not gitignored")
        return 1
    tracked = subprocess.run(
        ["git", "ls-files", "--error-unmatch", ".env"], cwd=ROOT,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    ).returncode == 0
    if tracked:
        print("FAIL .env is tracked in git")
        return 1
    print("PASS .env owner-only permissions and git exclusion")

    async with httpx.AsyncClient(timeout=30, follow_redirects=False) as client:
        async def check(name, url, env_name):
            key = os.environ.get(env_name)
            if not key:
                print(f"FAIL {env_name} is missing")
                return False
            response = await client.get(url, headers={"Authorization": f"Bearer {key}"})
            print(f"{'PASS' if response.is_success else 'FAIL'} {name}: HTTP {response.status_code}")
            return response.is_success

        results = await asyncio.gather(
            check("Vultr account API", "https://api.vultr.com/v2/account", "VULTR_API_KEY"),
            check("Inference usage API", "https://api.vultrinference.com/v1/usage",
                  "VULTR_INFERENCE_API_KEY"),
        )
    return 0 if all(results) else 1


if __name__ == "__main__":
    try:
        raise SystemExit(asyncio.run(main()))
    except httpx.HTTPError as exc:
        # No request headers or response body: these can contain credentials.
        print(f"FAIL account preflight network error: {type(exc).__name__}")
        raise SystemExit(1)
