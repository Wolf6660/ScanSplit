#!/bin/sh
set -eu

ROOT="${SCANSPLIT_RUNTIME_DIR:-/runtime}"
REPO="${SOURCE_REPO:-https://github.com/Wolf6660/ScanSplit.git}"
REF="${SOURCE_REF:-main}"
PYTHON="${SCANSPLIT_BOOTSTRAP_PYTHON:-python3}"
export GIT_TERMINAL_PROMPT=0
export PIP_CACHE_DIR="$ROOT/pip-cache"
export PYTHONUNBUFFERED=1
mkdir -p "$ROOT/releases" "$PIP_CACHE_DIR"
staging=""
cleanup() { if [ -n "$staging" ] && [ -d "$staging" ]; then rm -rf "$staging"; fi; }
trap cleanup EXIT HUP INT TERM

update_release() {
    staging="$(mktemp -d "$ROOT/releases/.fetch-XXXXXX")"
    echo "ScanSplit: Lade $REF von GitHub …"
    if ! git -c http.lowSpeedLimit=1000 -c http.lowSpeedTime=45 clone --quiet --depth 1 --branch "$REF" "$REPO" "$staging/source"; then
        echo "ScanSplit: Git-Download fehlgeschlagen." >&2
        return 1
    fi
    revision="$(git -C "$staging/source" rev-parse HEAD)"
    release="$ROOT/releases/$revision"
    if [ ! -d "$release" ]; then mv "$staging/source" "$release"; fi
    if [ ! -f "$release/requirements.txt" ] || [ ! -f "$release/scansplit/server.py" ]; then
        echo "ScanSplit: Die geladene Version ist unvollständig." >&2
        return 1
    fi
    if [ ! -f "$release/.ready" ]; then
        if ! "$PYTHON" -m venv "$release/.venv"; then return 1; fi
        echo "ScanSplit: Installiere mitgelieferte Python-Pakete ohne PyPI-Zugriff …"
        if ! "$release/.venv/bin/python" -m pip install --disable-pip-version-check --no-index --find-links "$release/vendor" --require-hashes -r "$release/requirements.txt"; then
            echo "ScanSplit: Offline-Pakete fehlen oder ihre Prüfsummen stimmen nicht." >&2
            return 1
        fi
        if ! (cd "$release" && "$release/.venv/bin/python" -m scansplit --check); then return 1; fi
        touch "$release/.ready"
    fi
    if ! (cd "$release" && "$release/.venv/bin/python" -m scansplit --check); then return 1; fi
    "$PYTHON" -c 'import os,sys; target,release=sys.argv[1:]; tmp=target+".next."+str(os.getpid()); os.symlink(release,tmp); os.replace(tmp,target)' "$ROOT/current" "$release"
    cleanup; staging=""
    return 0
}

if [ "${AUTO_UPDATE:-true}" = "true" ] || [ ! -f "$ROOT/current/.ready" ]; then
    if ! update_release; then
        cleanup; staging=""
        if [ ! -f "$ROOT/current/.ready" ]; then
            echo "ScanSplit: Keine funktionierende Version im Cache. GitHub-Verbindung und mitgelieferte Offline-Pakete prüfen." >&2
            exit 1
        fi
        echo "ScanSplit: Starte die zuletzt erfolgreich geprüfte Version aus dem Cache." >&2
    fi
fi

cd "$ROOT/current"
export SCANSPLIT_REVISION="$(git rev-parse HEAD)"
echo "ScanSplit: Starte Version $SCANSPLIT_REVISION"
exec "$ROOT/current/.venv/bin/python" -m scansplit "$@"
