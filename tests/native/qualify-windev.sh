#!/usr/bin/env bash
# One-command Windows qualification of the Python SDK against ONE exact Core host.
#
#   tests/native/qualify-windev.sh 'F:\path\to\nativehtmlkit-host.exe' HOST_SHA256 EVIDENCE_DIR
#
# Runs from the Linux workstation against the Windows lab VM ($NHK_WIN_LAB, default
# administrator@winDEV) in workspace $NHK_WIN_DIR:
# 1. admin SSH (no desktop): unit (3.10 + 3.14, real named pipes), contract, headless real-host
#    integration, wheel packaging, clean offline install smoke;
# 2. INSIDE the interactive RDP desktop of $NHK_WIN_USER (default nhk_gui) via start_interactive.ps1:
#    integration with real windows, installed wheel with real windows, native GUI driver
#    (SendInput, Win32 windows, UI Automation). SSH-only results are never counted as GUI evidence.
# The host directory should be a Core release (LICENSE, THIRD_PARTY_NOTICES.md, protocol/).
# Optional $NHK_GUI_LOCK is a flock file serialising use of the shared desktop.
# NHK_PYTHONS: interpreter versions (default "3.10 3.14"). NHK_WHEEL: a prebuilt windows-x64 wheel
# (local path) to smoke-test instead of building one on the VM.
set -uo pipefail
[[ $# -ge 3 ]] || { sed -n '2,15p' "$0"; exit 2; }
REPO=$(cd "$(dirname "$0")/../.." && pwd)
HOSTW=$1; SHA=$2; EVID=$(mkdir -p "$3" && cd "$3" && pwd)
LAB=${NHK_WIN_LAB:-administrator@winDEV}
W=${NHK_WIN_DIR:-'F:\agent-workspaces\nativehtmlkit\python-a3bc7de8'}
WU=${W//\\//}
USER_=${NHK_WIN_USER:-nhk_gui}
INTERACTIVE=${NHK_WIN_INTERACTIVE:-'F:\agent-workspaces\nativehtmlkit\claude-2d6993f4\start_interactive.ps1'}
TMP=$(mktemp -d)
PYARGS=""; for v in ${NHK_PYTHONS:-3.10 3.14}; do PYARGS+=" --python $v"; done
if [[ -n ${NHK_WHEEL:-} ]]; then
  STAGES=unit,contract,integration,smoke; WHEELARG="--wheel-path \"\$W\\wheel-prebuilt\\$(basename "$NHK_WHEEL")\""
else
  STAGES=unit,contract,integration,package,smoke; WHEELARG=""
fi
trap 'rm -rf "$TMP"' EXIT
tar -C "$(dirname "$REPO")" --exclude __pycache__ --exclude .pytest_cache -cf "$TMP/src.tar" "$(basename "$REPO")"
cat > "$TMP/common.ps1" <<EOF
\$W = '$W'
\$ErrorActionPreference = 'Continue'
\$env:UV_CACHE_DIR = "\$W\uvcache"; \$env:UV_PYTHON_INSTALL_DIR = "\$W\pythons"
\$env:PATH = "\$W\bin;" + \$env:PATH
\$python = (Get-ChildItem "\$W\pythons\cpython-3.13*\python.exe" | Select-Object -First 1).FullName
\$hostExe = '$HOSTW'
\$release = Split-Path -Parent \$hostExe
Set-Location "\$W\src\\$(basename "$REPO")"
EOF
cat > "$TMP/headless.ps1" <<EOF
. '$W\qualify-common.ps1'
if (Test-Path "\$W\evidence-headless") { Remove-Item -Recurse -Force "\$W\evidence-headless" }
& \$python scripts\qualify.py --host \$hostExe --host-sha256 $SHA --evidence "\$W\evidence-headless" --label windows-x64-headless $PYARGS --stages $STAGES $WHEELARG --core-notices \$release --core-protocol "\$release\protocol"
exit \$LASTEXITCODE
EOF
cat > "$TMP/desktop.ps1" <<EOF
. '$W\qualify-common.ps1'
if (Test-Path "\$W\evidence-desktop") { Remove-Item -Recurse -Force "\$W\evidence-desktop" }
\$wheel = (Get-ChildItem "\$W\wheel-for-desktop\*.whl" -ErrorAction SilentlyContinue | Select-Object -First 1).FullName
& \$python scripts\qualify.py --host \$hostExe --host-sha256 $SHA --evidence "\$W\evidence-desktop" --label windows-interactive --desktop --python 3.13 --stages integration,smoke,gui --wheel-path "\$wheel" --gui-python \$python *> "\$W\evidence-desktop.log"
exit 0
EOF
cat > "$TMP/run-desktop.ps1" <<EOF
# Files the admin stage produced (wheel) do not always inherit the user's grant: copy the
# wheel into a fresh directory (Copy-Item does not preserve ACLs) and grant explicitly.
if (Test-Path '$W\wheel-for-desktop') { Remove-Item -Recurse -Force '$W\wheel-for-desktop' }
New-Item -ItemType Directory '$W\wheel-for-desktop' | Out-Null
Get-ChildItem '$W\evidence-headless\dist-windows-x64-headless\*.whl', '$W\wheel-prebuilt\*.whl' -ErrorAction SilentlyContinue | Copy-Item -Destination '$W\wheel-for-desktop'
icacls '$W' /grant "${USER_}:(OI)(CI)M" /T /C /Q | Out-Null
# -Hidden: no console window on the desktop that could cover the app or its native dialog
# (a visible console once took the driver's activating click and Alt+F4 and ended the run).
& '$INTERACTIVE' -UserName $USER_ -ScriptPath '$W\qualify-desktop.ps1' -TimeoutSeconds 2400 -Hidden
Get-Content '$W\evidence-desktop.log' -Tail 60
EOF
cat > "$TMP/unpack.ps1" <<EOF
\$W = '$W'
if (Test-Path "\$W\src") { Remove-Item -Recurse -Force "\$W\src" }
New-Item -ItemType Directory "\$W\src" | Out-Null
tar -xf "\$W\qualify-src.tar" -C "\$W\src"
EOF
scp -q "$TMP/src.tar" "$LAB:$WU/qualify-src.tar"
if [[ -n ${NHK_WHEEL:-} ]]; then
  ssh -o BatchMode=yes "$LAB" "powershell -NoProfile -Command \"if (Test-Path '$W\\wheel-prebuilt') { Remove-Item -Recurse -Force '$W\\wheel-prebuilt' }; New-Item -ItemType Directory '$W\\wheel-prebuilt' | Out-Null\""
  scp -q "$NHK_WHEEL" "$LAB:$WU/wheel-prebuilt/"
fi
for f in common headless desktop run-desktop unpack; do scp -q "$TMP/$f.ps1" "$LAB:$WU/qualify-$f.ps1"; done
ssh -o BatchMode=yes "$LAB" "powershell -NoProfile -ExecutionPolicy Bypass -File $W\\qualify-unpack.ps1" || exit 1
status=0
ssh -o BatchMode=yes "$LAB" "powershell -NoProfile -ExecutionPolicy Bypass -File $W\\qualify-headless.ps1" || status=1
if [[ -n ${NHK_GUI_LOCK:-} ]]; then
  flock "$NHK_GUI_LOCK" ssh -o BatchMode=yes "$LAB" "powershell -NoProfile -ExecutionPolicy Bypass -File $W\\qualify-run-desktop.ps1" || status=1
else
  ssh -o BatchMode=yes "$LAB" "powershell -NoProfile -ExecutionPolicy Bypass -File $W\\qualify-run-desktop.ps1" || status=1
fi
for part in headless desktop; do
  rm -rf "$EVID/windows-$part"
  scp -q -r "$LAB:$WU/evidence-$part" "$EVID/windows-$part" || status=1
done
python3 - "$EVID/results.json" "$EVID/windows-headless/results.json" "$EVID/windows-desktop/results.json" <<'EOF'
import json, sys
from pathlib import Path
main = Path(sys.argv[1])
entries = json.loads(main.read_text()) if main.exists() else []
for extra in map(Path, sys.argv[2:]):
    for entry in json.loads(extra.read_text()) if extra.exists() else []:
        if entry.get("log"):
            entry["log"] = extra.parent.name + "/" + entry["log"].replace("\\", "/")
        entries = [e for e in entries if e["id"] != entry["id"]] + [entry]
main.write_text(json.dumps(entries, indent=2))
print({s: sum(1 for e in entries if e["status"] == s and e["platform"].startswith("windows")) for s in ("PASS", "FAIL", "BLOCKED")})
EOF
exit $status
