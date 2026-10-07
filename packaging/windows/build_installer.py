#!/usr/bin/env python3
"""Build a password-encrypted personal installer from explicitly allowed files."""
import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import tarfile
import tempfile
import zipfile

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parents[1]
INNO_SHA = '9c73c3bae7ed48d44112a0f48e66742c00090bdb5bef71d9d3c056c66e97b732'
MOONLIGHT_SHA = '6f91d268b41ed5ca8066d9d7578dc403b8db190991ff48f00b1700465f8f7ebf'
TAILSCALE_SHA = '80eb007e39dfebe17299fa1a09c79a8e1d934f76e0246c0817ebe3af675b7ef6'
UBUNTU_SHA = '820311e238ea34d76a8ca2643d6c01065212e9417109e7397d70472a236df261'


def sha(path):
    with path.open('rb') as f:
        digest=hashlib.file_digest(f,'sha256')
    return digest.hexdigest()


def checked(path, expected):
    if not path.is_file() or sha(path)!=expected:
        raise ValueError(f'Missing or checksum-invalid dependency: {path.name}')


def wine_path(path):
    return 'Z:' + str(path.resolve()).replace('/', '\\')


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


def prepare_wsl_root(source, destination):
    # Cloud images expect systemd-resolved. WSL must generate its own DNS file
    # before apt/network checks run; retain every other official-image member.
    with tarfile.open(source, 'r|xz') as incoming, tarfile.open(destination, 'w|gz', compresslevel=3) as outgoing:
        for member in incoming:
            name=member.name.removeprefix('./')
            if name in ('etc/resolv.conf', 'etc/wsl.conf'):
                continue
            outgoing.addfile(member, incoming.extractfile(member) if member.isfile() else None)
        add_bytes(outgoing,'etc/wsl.conf',b'[network]\ngenerateResolvConf=true\n[interop]\nenabled=true\nappendWindowsPath=true\n[boot]\nsystemd=false\n',0o644)


def stage(home, assets, payload, tailnet, tailscale_key=None):
    payload.mkdir(mode=0o700)
    for filename,expected in [('moonlight.zip',MOONLIGHT_SHA),('tailscale.msi',TAILSCALE_SHA),('ubuntu-root.tar.xz',UBUNTU_SHA)]:
        checked(assets/filename, expected)
    (payload/'assets').mkdir()
    os.link(assets/'tailscale.msi',payload/'assets/tailscale.msi')
    prepare_wsl_root(assets/'ubuntu-root.tar.xz',payload/'assets/ubuntu-root.tar.gz')
    moonlight=payload/'Moonlight'; moonlight.mkdir()
    with zipfile.ZipFile(assets/'moonlight.zip') as archive:
        for member in archive.infolist():
            if '\\' in member.filename or '..' in Path(member.filename).parts or Path(member.filename).is_absolute():
                raise ValueError('Unsafe Moonlight archive member')
        archive.extractall(moonlight)
    if not (moonlight/'Moonlight.exe').is_file(): raise ValueError('Unexpected Moonlight portable layout')
    (moonlight/'portable.dat').touch()
    identity=home/'.config/Moonlight Game Streaming Project/Moonlight.conf'
    if not identity.is_file(): raise ValueError('Moonlight pairing configuration missing')
    location=moonlight/'Moonlight Game Streaming Project'; location.mkdir(exist_ok=True)
    shutil.copyfile(identity,location/'Moonlight.ini')
    (payload/'identity.json').write_text(json.dumps(dict(tailnet=tailnet)))
    with tarfile.open(payload/'accounts.tar','w') as archive:
        for name,contents in account_files(home): add_bytes(archive,name,contents)
    with tarfile.open(payload/'backend.tar','w') as archive:
        # The exact same modules and entry point ship on Linux and Windows.
        for path in [PROJECT/'bin/vastgame', *sorted((PROJECT/'src').rglob('*'))]:
            if path.is_file() and not path.is_symlink() and (
                path.suffix in ('.py','.sh','.cpp','.jq') or path.name in ('vastgame','ludusavi.json.gz','LUDUSAVI-LICENSE')
            ):
                relative=path.relative_to(PROJECT)
                add_bytes(archive,'.local/share/vastgame/app/'+relative.as_posix(),path.read_bytes(),0o755 if relative.as_posix()=='bin/vastgame' else 0o644)
    for filename in ('Complete-Setup.ps1','Prepare-WSL.ps1','prepare-network.sh','Native-Screen.ps1','Native-Ping.ps1','windows-bridge.sh','run-vastgame.sh','install-backend.sh','vastgame.cmd','WINDOWS-README.txt'):
        shutil.copyfile(HERE/filename,payload/filename)
    if tailscale_key:
        value=tailscale_key.read_text().strip()
        if not value.startswith('tskey-auth-') or any(c.isspace() for c in value):
            raise ValueError('Expected a Tailscale enrollment auth-key file')
        (payload/'tailscale-auth-key').write_text(value)


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--assets',type=Path,required=True)
    p.add_argument('--compiler',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--home',type=Path,default=Path.home())
    p.add_argument('--tailscale-key-file',type=Path)
    args=p.parse_args()
    args.output.mkdir(parents=True,exist_ok=True); args.output.chmod(0o700)
    private=args.home/'.local/state/vastgame/windows-build'; private.mkdir(parents=True,exist_ok=True); private.chmod(0o700)
    status=json.loads(subprocess.check_output(['tailscale','status','--json']))
    tailnet=status.get('CurrentTailnet',{}).get('Name')
    if status.get('BackendState')!='Running' or not tailnet: raise ValueError('Current Tailscale account is unavailable')
    password=secrets.token_urlsafe(24)
    password_file=args.output/'INSTALLER-PASSWORD.txt'
    fd=os.open(password_file,os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600)
    with os.fdopen(fd,'w') as output: output.write(password+'\n')
    with tempfile.TemporaryDirectory(prefix='private-',dir=private) as tmp:
        root=Path(tmp); payload=root/'payload'
        stage(args.home,args.assets,payload,tailnet,args.tailscale_key_file)
        spec=root/'personal.iss'
        spec.write_text('#define Payload "'+wine_path(payload)+'"\n#define Output "'+wine_path(args.output)+'"\n#define InstallerPassword "'+password+'"\n'+(HERE/'installer.iss').read_text())
        spec.chmod(0o600)
        # No password is passed on the command line or printed in build logs.
        log=args.output/'build.log'
        with log.open('w') as output:
            subprocess.run(['wine',str(args.compiler),'/Q',wine_path(spec)],stdout=output,stderr=subprocess.STDOUT,check=True)
    exe=args.output/'Vastgame-Setup-Personal.exe'
    if not exe.is_file(): raise ValueError('Installer compiler did not create the expected executable')
    (args.output/'Vastgame-Setup-Personal.exe.sha256').write_text(sha(exe)+'  '+exe.name+'\n')
    print('Built personal encrypted installer:',exe)
    print('Installer password is in a separate owner-only file:',password_file)


if __name__=='__main__': main()
