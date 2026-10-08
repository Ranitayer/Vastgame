#!/usr/bin/env python3
"""Export private configuration separately; never publish the resulting account archive."""
import argparse
import io
import json
import os
from pathlib import Path
import subprocess
import tarfile


def add_bytes(archive, name, contents, mode=0o600):
    member=tarfile.TarInfo(name); member.size=len(contents); member.mode=mode
    archive.addfile(member, io.BytesIO(contents))

def account_files(home):
    # Do not export Tailscale machine state, instance IDs, cookies, game archives,
    # logs, host SSH caches, or unrelated credentials.
    required=['.config/vastai/vast_api_key', '.config/rclone/rclone.conf',
              '.config/vastgame/template_hash', '.ssh/id_ed25519', '.ssh/id_ed25519.pub']
    for relative in required:
        path=home/relative
        if path.is_symlink() or not path.is_file() or not path.stat().st_size:
            raise ValueError('Missing required personal configuration: '+relative)
        yield relative, path.read_bytes()
    bootstrap=home/'.config/vastgame/bootstrap.json'
    if bootstrap.is_file() and not bootstrap.is_symlink():
        settings=json.loads(bootstrap.read_text())
        if not isinstance(settings,dict) or set(settings)-{'TS_AUTHKEY','RCLONE_CONFIG_B64'} or any(not isinstance(v,str) for v in settings.values()):
            raise ValueError('Invalid private bootstrap configuration')
        yield '.config/vastgame/bootstrap.json',bootstrap.read_bytes()
    role=home/'.config/vastai/vast_role'
    if role.is_file() and not role.is_symlink(): yield '.config/vastai/vast_role',role.read_bytes()
    for path in sorted((home/'.config/vastgame/games').glob('*/manifest.json')):
        if path.is_symlink(): raise ValueError('Symlinked game manifest')
        manifest=json.loads(path.read_text())
        if manifest.get('id')!=path.parent.name: raise ValueError('Manifest ID mismatch')
        manifest.pop('source',None)  # Linux source folders are not Windows folders.
        yield '.config/vastgame/games/'+path.parent.name+'/manifest.json',json.dumps(manifest,indent=2).encode()


def export(home, output):
    status=json.loads(subprocess.check_output(['tailscale','status','--json']))
    tailnet=status.get('CurrentTailnet',{}).get('Name')
    if not tailnet: raise ValueError('Sign into the intended Tailscale account first')
    output.parent.mkdir(parents=True,exist_ok=True)
    fd=os.open(output,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    try:
        with os.fdopen(fd,'wb') as raw, tarfile.open(fileobj=raw,mode='w') as archive:
            for name, content in account_files(home): add_bytes(archive,name,content)
            add_bytes(archive,'identity.json',json.dumps(dict(tailnet=tailnet)).encode())
            moonlight=home/'.config/Moonlight Game Streaming Project/Moonlight.conf'
            if moonlight.is_file(): add_bytes(archive,'moonlight.ini',moonlight.read_bytes())
    except BaseException:
        output.unlink(missing_ok=True)
        raise
    print('Private account bundle:',output)
    print('Contains account keys. Transfer privately to your friend; never upload to GitHub.')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--home',type=Path,default=Path.home())
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    export(args.home,args.output)
