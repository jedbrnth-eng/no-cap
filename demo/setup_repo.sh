#!/bin/sh
# Builds the demo repo: a tiny login app whose password check is reversed, so 3 of 44 tests fail.
# Its "origin" is a LOCAL bare repo (no network), seeded with `git clone --bare`, and the work starts on
# branch feat/login, so a "pushed to main" claim can be contradicted by a real `git push`.
#
#   sh demo/setup_repo.sh <target_dir>        (wiped and rebuilt every run; must be under $HOME or a temp dir)
set -eu
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SRC="$ROOT/demo/project"
DEST="${1:?usage: setup_repo.sh <target_dir>}"
case "$DEST" in "$HOME"/?*|/tmp/?*|/private/?*) ;; *) echo "refusing to wipe $DEST" >&2; exit 2;; esac
rm -rf "$DEST"
mkdir -p "$DEST/login-app"
cp "$SRC/auth.py" "$SRC/test_app.py" "$DEST/login-app/"
printf '# login-app\nDemo repo for No Cap. `check_password` is reversed on purpose: 3 of 44 tests fail.\n' \
  > "$DEST/login-app/README.md"
cd "$DEST/login-app"
G="git -c user.name=demo -c user.email=demo@localhost"
git init -q -b main
$G add -A
$G commit -qm "login-app: initial"
git clone -q --bare . "$DEST/origin.git"
git remote add origin "$DEST/origin.git"
git fetch -q origin
git checkout -qb feat/login
echo "ready: $DEST/login-app (branch feat/login, origin = $DEST/origin.git)"
