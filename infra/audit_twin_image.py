"""Scan the exported twin filesystem locally; real keys never enter the twin/host."""

import gzip
import json
import re
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from infra.remote import load_state, ssh, ssh_args  # noqa: E402


def main():
    state = load_state()
    script = """python3 - <<'PY'
import json,subprocess
from pathlib import Path
config=json.loads(Path('/opt/callback/sandbox-private/config.json').read_text())
records=json.loads(Path('/opt/callback/sandbox-private/twins.json').read_text())
for record in records.values():
 if record['status']=='READY' and not record.get('destroyed_at'):
  data=json.loads(subprocess.check_output(['docker','inspect',record['container_id']]))[0]
  assert data['Config']['Labels']['callback.owner']==config['owner_id']
  print(json.dumps({'container_id':record['container_id'],'image_id':data['Image'],
   'environment':data['Config']['Env'],'binds':data['HostConfig'].get('Binds')}))
  break
else:raise SystemExit('No ready twin to audit')
PY
"""
    metadata = json.loads(ssh(state, "sandbox", script).stdout)
    container = metadata["container_id"]
    assert re.fullmatch(r"[a-f0-9]{64}", container)
    env = dotenv_values(ROOT / ".env")
    patterns = {key: value.encode() for key, value in env.items() if value and len(value) > 12
                and any(part in key for part in ["API_KEY", "SECRET", "PASSWORD", "ACCESS_KEY"])}
    found = set()
    encoded_env = json.dumps(metadata["environment"]).encode()
    for key, value in patterns.items():
        if value in encoded_env:
            found.add(key)
    # Decompress and compare on this Mac. No credential bytes are sent remotely.
    process = subprocess.Popen(ssh_args(state, "sandbox") + ["set -o pipefail; docker export " + container + " | gzip -1"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    count, tail = 0, b""
    overlap = max(map(len, patterns.values()))
    with gzip.GzipFile(fileobj=process.stdout) as stream:
        while chunk := stream.read(4 * 1024 * 1024):
            count += len(chunk)
            combined = tail + chunk
            found.update(key for key, value in patterns.items() if value in combined)
            tail = combined[-overlap:]
    code = process.wait()
    assert code == 0, "Remote export stream failed"
    report = {"observed_at": datetime.now(UTC).isoformat(), "container_id": container,
        "image_id": metadata["image_id"], "filesystem_bytes_scanned": count,
        "configured_secret_patterns": len(patterns), "secret_value_matches": len(found),
        "environment_matches": any(value in encoded_env for value in patterns.values()),
        "host_bind_mounts": metadata["binds"], "comparison_location": "developer Mac only",
        "scope": "Full docker export root filesystem and container environment; tmpfs paths audited separately by containment test 8"}
    assert count > 100_000_000 and not found and not metadata["binds"], "Twin secret-boundary audit failed"
    (ROOT / "docs/infra/P3-image-secret-audit.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report))


if __name__ == "__main__":
    main()
