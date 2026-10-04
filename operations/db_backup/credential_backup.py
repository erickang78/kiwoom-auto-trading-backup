"""Archive private server credentials; outputs only encrypted artifacts or counts."""
import hashlib,io,json,os,stat,tarfile
from pathlib import Path
MAX_FILE_BYTES=1024*1024

def snapshot_credentials(source,destination):
    source=Path(source);destination=Path(destination)
    if source.is_symlink() or not source.is_dir():raise ValueError('invalid_credentials_directory')
    files=sorted(source.iterdir())
    if not files:raise ValueError('empty_credentials_directory')
    manifest={'format':1,'kind':'credentials','files':[]}
    archive=destination/'credentials.tar.gz'
    fd=os.open(archive,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(fd,'wb') as stream,tarfile.open(fileobj=stream,mode='w:gz') as tar:
        for path in files:
            # Fail closed for unexpected nested directories/symlinks or changing files.
            fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW)
            with os.fdopen(fd,'rb') as f:
                before=os.fstat(f.fileno())
                if not stat.S_ISREG(before.st_mode) or before.st_size>MAX_FILE_BYTES:raise ValueError('invalid_credential_file')
                data=f.read(MAX_FILE_BYTES+1);after=os.fstat(f.fileno())
            if (before.st_size,before.st_mtime_ns)!=(after.st_size,after.st_mtime_ns) or len(data)!=before.st_size:raise ValueError('credential_changed_during_snapshot')
            info=tarfile.TarInfo('secrets/'+path.name);info.size=len(data);info.mode=0o600
            tar.addfile(info,io.BytesIO(data))
            manifest['files'].append({'name':path.name,'bytes':len(data),'sha256':hashlib.sha256(data).hexdigest()})
        data=json.dumps(manifest,sort_keys=True).encode();info=tarfile.TarInfo('manifest.json');info.size=len(data);info.mode=0o600;tar.addfile(info,io.BytesIO(data))
    return archive,len(files)
