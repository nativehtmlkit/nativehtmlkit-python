#!/usr/bin/env bash
# One-command Linux qualification of the Python SDK against ONE exact Core host.
#
#   tests/native/qualify-linuxdev.sh HOST_PATH HOST_SHA256 EVIDENCE_DIR [CORE_RELEASE_DIR]
#
# 1. On this workstation (headless): unit (3.10 + 3.14), contract, real-host integration,
#    wheel + sdist packaging, clean offline install smoke.
# 2. On the KDE Plasma Wayland lab session ($NHK_LINUX_LAB, default linuxDEV): the same
#    integration suite with REAL windows, the installed wheel with real windows, and the
#    native GUI driver (real ydotool input, KWin, AT-SPI). Optional $NHK_GUI_LOCK is a flock
#    file serialising use of the shared desktop.
# Results merge into EVIDENCE_DIR/results.json (PASS/FAIL/BLOCKED per check).
# CORE_RELEASE_DIR (LICENSE, THIRD_PARTY_NOTICES.md, protocol/) defaults to the host's directory.
# NHK_PYTHONS: interpreter versions (default "3.10 3.14"). NHK_WHEEL: smoke-test this prebuilt
# wheel instead of building one here (so the shipped artifact is the one qualified).
set -uo pipefail
[[ $# -ge 3 ]] || { sed -n '2,15p' "$0"; exit 2; }
REPO=$(cd "$(dirname "$0")/../.." && pwd)
HOST=$(readlink -f "$1"); SHA=$2; EVID=$(mkdir -p "$3" && cd "$3" && pwd)
RELEASE=$(readlink -f "${4:-$(dirname "$HOST")}")
LAB=${NHK_LINUX_LAB:-linuxDEV}
RDIR=${NHK_LINUX_LAB_DIR:-/home/dev/projects/nhk-python-a3bc}
VERSION=$("$HOST" --version 2>/dev/null | awk '{print $2}')
cd "$REPO"
status=0
PYARGS=(); for v in ${NHK_PYTHONS:-3.10 3.14}; do PYARGS+=(--python "$v"); done
if [[ -n ${NHK_WHEEL:-} ]]; then
  STAGES=unit,contract,integration,smoke; WHEEL=$(readlink -f "$NHK_WHEEL"); EXTRA=(--wheel-path "$WHEEL")
else
  STAGES=unit,contract,integration,package,smoke; EXTRA=(--sdist)
fi
python3 scripts/qualify.py --host "$HOST" --host-sha256 "$SHA" --evidence "$EVID" --label linux-x64-headless \
  "${PYARGS[@]}" --stages "$STAGES" "${EXTRA[@]}" \
  --core-notices "$RELEASE" --core-protocol "$RELEASE/protocol" --core-version "$VERSION" || status=1
[[ -n ${WHEEL:-} ]] || WHEEL=$(ls "$EVID"/dist-linux-x64-headless/*.whl 2>/dev/null | head -1)

# Desktop stages on the lab session.
ssh -o BatchMode=yes "$LAB" "mkdir -p $RDIR/host-$SHA $RDIR/wheel && rm -rf $RDIR/evidence-run" || exit 1
rsync -a --delete --exclude __pycache__ --exclude .pytest_cache "$REPO/" "$LAB:$RDIR/src-tree/"
rsync -a "$HOST" "$LAB:$RDIR/host-$SHA/nativehtmlkit-host"
[[ -d $RELEASE/protocol ]] && rsync -a "$RELEASE/protocol" "$LAB:$RDIR/host-$SHA/"
[[ -n $WHEEL ]] && rsync -a "$WHEEL" "$LAB:$RDIR/wheel/"
REMOTE="source ~/lab/bin/gui-env; export QT_QPA_PLATFORM=wayland GDK_BACKEND=wayland; unset DISPLAY;
cd $RDIR/src-tree && python3 scripts/qualify.py --host $RDIR/host-$SHA/nativehtmlkit-host --host-sha256 $SHA \
  --evidence $RDIR/evidence-run --label linux-kde-wayland --desktop --python 3.14 \
  --stages integration,smoke,gui --wheel-path $RDIR/wheel/$(basename "${WHEEL:-none}")"
if [[ -n ${NHK_GUI_LOCK:-} ]]; then
  flock "$NHK_GUI_LOCK" ssh -o BatchMode=yes "$LAB" "$REMOTE" || status=1
else
  ssh -o BatchMode=yes "$LAB" "$REMOTE" || status=1
fi
mkdir -p "$EVID/linux-kde-wayland"
rsync -a "$LAB:$RDIR/evidence-run/" "$EVID/linux-kde-wayland/"
python3 - "$EVID/results.json" "$EVID/linux-kde-wayland/results.json" <<'EOF'
import json, sys
from pathlib import Path
main, extra = Path(sys.argv[1]), Path(sys.argv[2])
entries = json.loads(main.read_text()) if main.exists() else []
for entry in json.loads(extra.read_text()) if extra.exists() else []:
    if entry.get("log"):
        entry["log"] = "linux-kde-wayland/" + entry["log"]
    entries = [e for e in entries if e["id"] != entry["id"]] + [entry]
main.write_text(json.dumps(entries, indent=2))
print({s: sum(1 for e in entries if e["status"] == s and e["platform"].startswith("linux")) for s in ("PASS", "FAIL", "BLOCKED")})
EOF
exit $status
