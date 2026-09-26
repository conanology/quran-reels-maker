"""Validate copied current source with disposable stores and no live services."""
import ast
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs/remediation"
SNAP = OUT / "sandbox"
OUT.mkdir(parents=True, exist_ok=True)
names = subprocess.check_output(
    ["git", "ls-files", "--cached", "--others", "--exclude-standard"], cwd=ROOT, text=True
).splitlines()
allowed_roots = {"core", "config", "database", "notifications", "youtube", "tiktok", "longform", "scripts",
                 "documentary", "quran_compiler", "tests", "assets", ".github"}
syntax = []
for name in sorted(set(names)):
    relative = Path(name)
    if relative.parts[0] not in allowed_roots and len(relative.parts) != 1:
        continue
    source = ROOT / relative
    if not source.is_file() or source.suffix not in {".py", ".ttf", ".html", ".js", ".css", ".yml"} and name != "pytest.ini":
        continue
    if source.suffix == ".py":
        try:
            ast.parse(source.read_text(encoding="utf-8-sig"), filename=name)
            syntax.append({"path": name, "status": "pass"})
        except Exception as exc:
            syntax.append({"path": name, "status": "fail", "error": str(exc)})
    destination = SNAP / relative
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, destination)
(OUT / "syntax.json").write_text(json.dumps(syntax, indent=2), encoding="utf-8")
db = ROOT / "database/quran_reels.db"
db_hash = hashlib.sha256(db.read_bytes()).hexdigest()
(OUT / "production-db-before.sha256").write_text(db_hash, encoding="ascii")
env = {key: value for key, value in os.environ.items() if key.upper() in {
    "SYSTEMROOT", "WINDIR", "PATH", "COMSPEC", "PATHEXT", "TEMP", "TMP", "LOCALAPPDATA",
    "APPDATA", "USERPROFILE", "PROGRAMFILES", "PROGRAMFILES(X86)"}}
env.update(PYTHONDONTWRITEBYTECODE="1", PYTEST_DISABLE_PLUGIN_AUTOLOAD="1", PYTHONIOENCODING="utf-8",
           VIDEO_ENCODER="libx264", OPENROUTER_API_KEY="", PEXELS_API_KEY="", TELEGRAM_BOT_TOKEN="",
           TELEGRAM_CHAT_ID="", TIKTOK_CLIENT_KEY="", TIKTOK_CLIENT_SECRET="", PYTHON_DOTENV_DISABLED="1",
           QRM_OUTPUTS_DIR=str(SNAP / "outputs"), QRM_DATABASE_DIR=str(SNAP / "database"),
           QRM_DATABASE_PATH=str(SNAP / "database/test-suite.db"), QRM_LOG_FILE=str(SNAP / "outputs/test.log"))
dependency_path = OUT / "web/site-packages"
env["PYTHONPATH"] = os.pathsep.join([str(SNAP), str(dependency_path)])
bootstrap = '''import socket, sys, pytest
def denied(*args, **kwargs):
    raise RuntimeError("REMEDIATION TEST: external network blocked")
socket.create_connection = denied
original = socket.socket.connect
def local_connect(self, address):
    if isinstance(address, tuple) and address[0] in ("127.0.0.1", "::1", "localhost"):
        return original(self, address)
    return denied()
socket.socket.connect = local_connect
import dotenv
dotenv.load_dotenv = lambda *a, **kw: False
sys.exit(pytest.main(sys.argv[1:]))
'''
(SNAP / "remediation_bootstrap.py").write_text(bootstrap, encoding="utf-8")
selection = sys.argv[1:] or ["tests"]
command = [sys.executable, "-B", str(SNAP / "remediation_bootstrap.py"), *selection,
           "-p", "pytest_mock", "-p", "no:cacheprovider", "--tb=short"]
start = time.monotonic()
result = subprocess.run(command, cwd=SNAP, env=env, capture_output=True, text=True,
                        encoding="utf-8", timeout=240)
elapsed = time.monotonic() - start
db_preserved = hashlib.sha256(db.read_bytes()).hexdigest() == db_hash
(OUT / "pytest-latest.txt").write_text(
    "COMMAND: " + subprocess.list2cmdline(command) + "\n" + result.stdout + "\nSTDERR:\n" + result.stderr,
    encoding="utf-8")
summary = {"python_files": len(syntax), "syntax_failures": sum(x["status"] == "fail" for x in syntax),
           "test_exit": result.returncode, "elapsed_seconds": round(elapsed, 2),
           "production_database_unchanged": db_preserved, "selection": selection}
(OUT / "check-results.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
print(result.stdout[-12000:])
print(result.stderr[-1500:])
print(json.dumps(summary, indent=2))
sys.exit(result.returncode or (1 if not db_preserved or summary["syntax_failures"] else 0))
