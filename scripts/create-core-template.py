#!/usr/bin/env python3
"""Create/verify the private official Ubuntu CLI VM template, then select it."""
import json
import os
from pathlib import Path
import shlex
import subprocess
import tempfile
import argparse

ROOT = Path(__file__).resolve().parents[1]


def cli(*arguments):
    result = subprocess.run(['vastai', *arguments, '--raw'], capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError('Vast CLI request failed: ' + ' '.join(arguments[:2]))
    try:
        return json.loads(result.stdout)
    except ValueError:
        # This CLI version prints a human response even with --raw on creation.
        # A successful authenticated search/readback remains mandatory below.
        if arguments[:2] in (('create', 'template'), ('update', 'template')):
            return {}
        raise RuntimeError('Vast CLI returned a non-JSON response') from None


def rows(response):
    if isinstance(response, list):
        return response
    return response.get('templates', [])


def atomic(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as output:
            output.write(value)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def options(environment):
    return '-p 22:22 ' + ' '.join('-e ' + shlex.quote(key + '=' + value)
                                for key, value in environment.items() if not key.startswith('-'))


def environment_fields(value):
    if isinstance(value, dict):
        return value
    try:
        parsed = json.loads(value)
        if isinstance(parsed, dict):
            return parsed
    except (ValueError, TypeError):
        pass
    fields = {}
    tokens = shlex.split(value or '')
    for index, token in enumerate(tokens[:-1]):
        if token == '-e' and '=' in tokens[index+1]:
            key, value = tokens[index+1].split('=', 1)
            fields[key] = value
    return fields


def main(update=False):
    config = Path(os.environ.get('XDG_CONFIG_HOME', str(Path.home()/'.config')))/'vastgame'
    selected = config/'template_hash'
    previous = selected.read_text().strip()
    current = rows(cli('search', 'templates', 'hash_id='+previous))
    if len(current) != 1:
        raise RuntimeError('Could not uniquely identify the current template')
    current = current[0]
    spec = json.loads((ROOT/'packaging/templates/core-vm.json').read_text())
    inherited = environment_fields(current.get('env'))
    environment = {'VASTGAME_TEMPLATE_PROFILE': spec['profile']}
    for key in ('TS_AUTHKEY', 'RCLONE_CONFIG_B64'):
        if not isinstance(inherited.get(key), str) or not inherited[key]:
            raise RuntimeError('Current private template is missing '+key)
        environment[key] = inherited[key]
    if inherited.get('NVIDIA_CONTAINER_TOOLKIT_VERSION'):
        environment['NVIDIA_CONTAINER_TOOLKIT_VERSION'] = inherited['NVIDIA_CONTAINER_TOOLKIT_VERSION']
    setup = '\n'.join((ROOT/'src/bootstrap/core-vm.sh').read_text().splitlines()[1:])
    onstart = '#!/usr/bin/env bash\nset -Eeuo pipefail\n' + setup + '''
source /etc/environment
prepare_core_vm
echo '[VASTGAME] Ubuntu CLI base ready. Use vastgame start <game-id> for the complete gaming startup.'
'''
    matches = rows(cli('search', 'templates', 'creator_id='+str(current['creator_id'])))
    # Reuse the previous private template when migrating its display name.
    matches = [t for t in matches if t.get('name') in (spec['name'], 'Vastgame Core VM')]
    if len(matches) > 1:
        raise RuntimeError('Multiple Core VM templates found; refusing to guess')
    if not matches or update or matches[0].get('name') != spec['name']:
        if matches and (not matches[0].get('private') or matches[0].get('creator_id') != current['creator_id']):
            raise RuntimeError('Refusing to update a non-private or unrelated template')
        operation = ('update', 'template', matches[0]['hash_id']) if matches else ('create', 'template')
        response = cli(*operation, '--name', spec['name'], '--image', spec['image'],
                       '--image_tag', spec['image_tag'], '--ssh', '--direct', '--no-default',
                       '--search_params', spec['search_params'], '--disk_space', str(spec['disk_space']),
                       '--desc', spec['desc'], '--env', options(environment), '--onstart-cmd', onstart)
        if response.get('success') is False:
            raise RuntimeError('Vast rejected template creation')
        matches = [t for t in rows(cli('search', 'templates', 'creator_id='+str(current['creator_id'])))
                   if t.get('name') == spec['name']]
    if len(matches) != 1:
        raise RuntimeError('Template creation could not be verified; old template remains selected')
    template = matches[0]
    returned_env = environment_fields(template.get('env'))
    if (template.get('name') != spec['name'] or not template.get('private') or template.get('runtype') != 'ssh'
            or template.get('image') != spec['image'] or template.get('tag') != spec['image_tag']
            or template.get('onstart') != onstart or not template.get('ssh_direct')
            or template.get('recommended_disk_space') != spec['disk_space']
            or any(returned_env.get(k) != v for k, v in environment.items())):
        raise RuntimeError('Template readback differs; old template remains selected')
    filters = template.get('extra_filters')
    if isinstance(filters, str):
        filters = json.loads(filters)
    if not isinstance(filters, dict) or filters.get('vms_enabled', {}).get('eq') is not True:
        raise RuntimeError('VM compatibility filter missing; old template remains selected')
    template_hash = template.get('hash_id')
    if not isinstance(template_hash, str) or not template_hash:
        raise RuntimeError('Verified template has no hash')
    backup = config/'template_hash.before-core-vm'
    if not backup.exists():
        atomic(backup, previous+'\n')
    receipt = {k: template[k] for k in ('id', 'hash_id', 'name', 'image', 'tag', 'private')}
    atomic(config/'core-vm-template.json', json.dumps(receipt, indent=2)+'\n')
    atomic(selected, template_hash+'\n')
    print('Created/verified and selected:', spec['name'])
    print('Template ID:', template['id'])
    print('Template hash:', template_hash)
    print('Previous template retained in:', backup)
    print('No VM rented or modified.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--update', action='store_true', help='Update the owned private template and verify it before selection')
    main(update=parser.parse_args().update)
