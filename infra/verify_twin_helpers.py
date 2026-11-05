"""Real regression: user Python hooks and background work cannot bypass helpers/freeze."""

import json
import re
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from infra.remote import load_state, ssh  # noqa: E402


def main():
    state = load_state()
    program = r'''import json,httpx
from pathlib import Path
c=json.loads(Path('control-private/sandbox.json').read_text())
h=httpx.Client(base_url=c['url'],headers={'Authorization':'Bearer '+c['api_secret']},timeout=300)
def api(method,path,**kwargs):
 r=h.request(method,path,**kwargs);r.raise_for_status();return r.json()
t=api('POST','/fresh/acme');tid=t['twin_id']
before=api('GET','/twins/'+tid+'/snapshot')['state']
sam=next(u for u in before['users'].values() if u['username']=='sam.rivera')
assert sam['attributes']['tier']==['standard']
code="from pathlib import Path;p=Path('/home/twin/.local/lib/python3.12/site-packages');p.mkdir(parents=True,exist_ok=True);(p/'sitecustomize.py').write_text(\"raise RuntimeError('UNTRUSTED_SITE_HOOK')\\n\")"
r=api('POST','/twins/'+tid+'/exec',json={'language':'python','code':code});assert r['exit_code']==0,r
snap=api('GET','/twins/'+tid+'/snapshot');assert snap['complete'] and len(snap['state']['users'])==40
code="printf '%s' 'import time,pathlib\np=pathlib.Path(\"/tmp/callback/work/ticks\")\nwhile True:\n p.write_text(str(time.time_ns()))\n time.sleep(.02)\n' > /tmp/callback/work/ticker.py; python3 -I /tmp/callback/work/ticker.py >/tmp/callback/work/ticker.log 2>&1 </dev/null &"
r=api('POST','/twins/'+tid+'/exec',json={'language':'bash','code':code});assert r['exit_code']==0,r
frozen=api('POST','/twins/'+tid+'/freeze');assert frozen['complete']
r=h.post('/twins/'+tid+'/exec',json={'language':'bash','code':'echo MUST_NOT_EXECUTE'});assert r.status_code==409
page=api('POST','/twins/'+tid+'/admin-screenshot',json={'user_id':sam['id']})
assert sam['id'] in page['url'] and 'Credentials' in page['text']
print(json.dumps({'twin_id':tid,'container_id':t['container_id'],'employees':len(snap['state']['users']),
 'sam_tier':sam['attributes']['tier'],'user_site_hook_ignored':True,'frozen_exec_status':r.status_code,
 'actual_browser_screenshot':Path(page['screenshot_path']).name,'browser_url':page['url']}))
'''
    result = ssh(state, "control", "cd /opt/callback\n.venv/bin/python - <<'CALLBACK_TEST'\n" + program + "\nCALLBACK_TEST\n", timeout=360, check=False)
    if result.returncode:
        print(result.stderr[-2500:])
        raise RuntimeError("Fixed-helper regression failed")
    report = json.loads(result.stdout)
    container = report["container_id"]
    assert re.fullmatch(r"[a-f0-9]{64}", container)
    program = """import subprocess,time,json
container=CONTAINER
def read():return subprocess.check_output(['docker','exec','--user','1100:1100',container,'cat','/tmp/callback/work/ticks']).decode()
a=read();time.sleep(1);b=read()
assert a==b,'Agent background work continued after freeze'
data=json.loads(subprocess.check_output(['docker','inspect',container]))[0]
assert data['Config']['User']=='1001:1001'
print(json.dumps({'background_stopped':True,'trusted_anchor_uid':data['Config']['User']}))
""".replace("CONTAINER", repr(container))
    result = ssh(state, "sandbox", "python3 - <<'CALLBACK_TEST'\n" + program + "\nCALLBACK_TEST\n", timeout=30, check=False)
    if result.returncode:
        print(result.stderr[-1000:])
        raise RuntimeError("Background-work freeze check failed")
    report.update(json.loads(result.stdout))
    program = r'''import httpx,json
from pathlib import Path
c=json.loads(Path('control-private/sandbox.json').read_text())
h=httpx.Client(base_url=c['url'],headers={'Authorization':'Bearer '+c['api_secret']},timeout=30)
r=h.post('/twins/TWIN/destroy');r.raise_for_status();print(json.dumps(r.json()['destroy_proof']))
'''.replace("TWIN", report["twin_id"])
    report["destroy_proof"] = json.loads(ssh(state, "control", "cd /opt/callback\n.venv/bin/python - <<'CALLBACK_TEST'\n" + program + "\nCALLBACK_TEST\n", timeout=45).stdout)
    report.update({"observed_at": datetime.now(UTC).isoformat(), "all_passed": True,
                   "workload": "Implementer-written hostile hook and background-work regression; real Vultr twin"})
    (ROOT / "docs/infra/P4-helper-regression.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report))


if __name__ == "__main__":
    main()
