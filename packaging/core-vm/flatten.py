#!/usr/bin/env python3
"""Flatten a prepared KVM wrapper without losing its launch configuration."""
import json
import subprocess
import sys


def changes(config):
    if config.get('Healthcheck') or config.get('OnBuild') or config.get('Volumes'):
        raise ValueError('Unexpected wrapper hooks/volumes; refusing to discard them')
    result=[]
    for entry in config.get('Env') or []:
        name,value=entry.split('=',1)
        result += ['--change', 'ENV '+name+'='+json.dumps(value).replace('$', r'\$')]
    for key in ('Entrypoint', 'Cmd'):
        if config.get(key) is not None:
            result += ['--change', key.upper()+' '+json.dumps(config[key])]
    for key in ('User', 'WorkingDir', 'StopSignal'):
        if config.get(key):
            field={'User':'USER','WorkingDir':'WORKDIR','StopSignal':'STOPSIGNAL'}[key]
            result += ['--change', field+' '+json.dumps(config[key])]
    for port in config.get('ExposedPorts') or {}:
        result += ['--change', 'EXPOSE '+port]
    for name,value in (config.get('Labels') or {}).items():
        result += ['--change', 'LABEL '+name+'='+json.dumps(value)]
    result += ['--change', 'LABEL org.opencontainers.image.source="https://github.com/Ranitayer/Vastgame"']
    return result


def flatten(source, destination):
    original=json.loads(subprocess.check_output(['docker','image','inspect',source]))[0]['Config']
    options=changes(original)
    container=subprocess.check_output(['docker','create','--entrypoint','/bin/true',source],text=True).strip()
    try:
        export=subprocess.Popen(['docker','export',container],stdout=subprocess.PIPE)
        try:
            imported=subprocess.run(['docker','import','--platform','linux/amd64',*options,'-',destination],stdin=export.stdout)
            export.stdout.close()
            export_code=export.wait()
            if imported.returncode or export_code:
                raise RuntimeError('Wrapper export/import failed')
        finally:
            if export.poll() is None:
                export.terminate(); export.wait()
        restored=json.loads(subprocess.check_output(['docker','image','inspect',destination]))[0]['Config']
        if dict(item.split('=',1) for item in restored.get('Env') or []) != dict(item.split('=',1) for item in original.get('Env') or []):
            raise RuntimeError('Flattened wrapper changed environment')
        for key in ('Entrypoint','Cmd','User','WorkingDir','StopSignal','ExposedPorts'):
            if (restored.get(key) or None) != (original.get(key) or None):
                raise RuntimeError('Flattened wrapper changed '+key)
    finally:
        subprocess.run(['docker','rm',container],check=True,stdout=subprocess.DEVNULL)


if __name__ == '__main__':
    flatten(*sys.argv[1:])
