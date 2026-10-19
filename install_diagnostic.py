"""Install only the diagnostic in its own user directory; never touch the agent."""
import os
import shutil
import subprocess
import tempfile
from pathlib import Path


def install(source, localappdata):
    source = Path(source)
    # Validate all inputs before creating a destination. Existing agent untouched.
    for name in ('runtime/python.exe', 'lib/pymysql/__init__.py', 'diagnostic.py', 'targeted_z.py', 'pos_discovery.py'):
        if not (source / name).is_file():
            raise FileNotFoundError('Pachet incomplet: extrage intreaga arhiva.')
    parent = Path(localappdata) / 'SnackYouDiagnostic'
    parent.mkdir(parents=True, exist_ok=True)
    target = Path(tempfile.mkdtemp(prefix='diagnostic-1.1-', dir=parent))
    for name in ('runtime', 'lib'):
        shutil.copytree(source / name, target / name)
    for name in ('diagnostic.py', 'targeted_z.py', 'pos_discovery.py'):
        shutil.copyfile(source / name, target / name)
    for name in ('PyMySQL-LICENSE.txt', 'CITESTE-MA.txt'):
        if (source / name).is_file(): shutil.copyfile(source / name, target / name)
    return target


if __name__ == '__main__':
    try:
        target = install(Path(__file__).resolve().parent, os.environ['LOCALAPPDATA'])
        print('Diagnostic instalat separat. Agentul de bonuri ramane pornit.')
        result = subprocess.run([str(target / 'runtime/python.exe'), '-B', str(target / 'diagnostic.py')], cwd=target)
        raise SystemExit(result.returncode)
    except Exception as exc:
        print('Instalarea diagnosticului nu a reusit: ' + type(exc).__name__)
        print('Agentul existent nu a fost modificat. Trimite fotografia acestui mesaj.')
        raise SystemExit(1)
