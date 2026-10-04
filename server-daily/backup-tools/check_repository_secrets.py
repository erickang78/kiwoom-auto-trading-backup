"""Check staged Git blobs; print paths and reasons, never matched secrets."""
from pathlib import Path, PurePosixPath
import re, subprocess, sys
ROOT=Path(__file__).resolve().parents[1]
PATTERNS=[
    ('private key',rb'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----'),
    ('GitHub credential',rb'\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,})\b'),
    ('AWS access key',rb'\b(?:AKIA|ASIA)[A-Z0-9]{16}\b'),
]
def inspect(name,data,known_secrets=()):
    p=PurePosixPath(name);reasons=[]
    if any(x in p.parts for x in ('.private-backups','.git','.aws','.openai','secrets')):
        reasons.append('private directory')
    if p.name.startswith('.env') and p.name!='.env.example':reasons.append('environment credentials')
    if p.suffix in ('.db','.sqlite3','.pem','.key','.b64') or '-credentials.' in p.name or p.name=='AWS-대시보드-접속.html':
        reasons.append('private/generated file')
    if any(x in p.name for x in ('.before-','.bak')):reasons.append('legacy copy')
    if p.suffix in ('.png','.jpg','.jpeg') and p.parts[0] in ('server-sync','operations'):reasons.append('operation screenshot')
    for label,pattern in PATTERNS:
        if re.search(pattern,data):reasons.append(label)
    for secret in known_secrets:
        if secret and secret in data:reasons.append('known private credential');break
    # Production HTML must never contain a non-empty TOKEN assignment.
    if p.suffix=='.html' and re.search(rb'\bTOKEN\s*=\s*[\x27\x22][^\x27\x22]+[\x27\x22]',data):
        reasons.append('frontend token literal')
    return reasons

def main():
    private=ROOT/'.private-backups/20261004/dashboard-token-existing'
    known=[private.read_bytes().strip()] if private.exists() else []
    names=subprocess.check_output(['git','ls-files','-z'],cwd=ROOT).decode().split('\0')
    failed=[];count=0
    for name in filter(None,names):
        data=subprocess.check_output(['git','show',':'+name],cwd=ROOT)
        issues=inspect(name,data,known)
        if issues:failed.append((name,issues))
        count+=1
    for name,issues in failed:print(name+': '+', '.join(issues),file=sys.stderr)
    print('Staged secret scan:',count,'files;',len(failed),'blocked')
    return bool(failed)
if __name__=='__main__':sys.exit(main())
