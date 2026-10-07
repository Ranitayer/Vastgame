from pathlib import Path
import re
ROOT = Path(__file__).resolve().parents[1]

def cli_source():
    entry = (ROOT / 'bin/vastgame').read_text()
    modules = re.findall(r'^source "\$APP_ROOT/(src/manager/[^"\n]+)"$', entry, re.M)
    modules += ['src/manager/hosts.sh', 'src/manager/launch.sh']
    return "\n".join((ROOT / module).read_text() for module in modules)
