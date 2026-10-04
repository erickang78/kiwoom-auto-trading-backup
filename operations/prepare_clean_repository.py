"""Preserve the legacy nested Git repository privately before creating a clean root history."""
from pathlib import Path
import hashlib, json, os, subprocess
ROOT=Path(__file__).resolve().parents[1]
def main():
    os.umask(0o077)
    legacy=ROOT/'moa-site/.git'
    destination=ROOT/'.private-backups/20261004/git-history'
    assert legacy.is_dir() and not destination.exists(), 'Already prepared or unexpected repository'
    destination.mkdir(mode=0o700)
    bundle=destination/'moa-site-history.bundle'
    subprocess.run(['git','-C',str(ROOT/'moa-site'),'bundle','create',str(bundle),'--all'],check=True)
    subprocess.run(['git','-C',str(ROOT/'moa-site'),'bundle','verify',str(bundle)],check=True,stdout=subprocess.DEVNULL)
    commits=subprocess.check_output(['git','-C',str(ROOT/'moa-site'),'rev-list','--all']).splitlines()
    count=len(commits)
    report={'legacy_commits':count,'bundle_sha256':hashlib.sha256(bundle.read_bytes()).hexdigest(),'history_contains_legacy_credentials':True,'never_publish_legacy_history':True}
    (destination/'manifest.json').write_text(json.dumps(report,indent=2))
    # Preserve complete refs, index, reflogs and configuration as well as the bundle.
    legacy.rename(destination/'moa-site.git')
    assert not legacy.exists() and (destination/'moa-site.git/HEAD').exists()
    print('Legacy Git privately preserved:',count,'commits; bundle verified; working files retained')
if __name__=='__main__':main()
