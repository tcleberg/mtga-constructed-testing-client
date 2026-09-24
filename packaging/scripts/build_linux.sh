#!/usr/bin/env bash
set -euo pipefail

VERSION="${APP_VERSION:-$(python3 -c 'import tomllib; print(tomllib.load(open("pyproject.toml", "rb"))["project"]["version"])')}"
ARCH="${TARGET_ARCH:-$(uname -m)}"
NAME="MTGA Constructed Testing"
DIST="dist/${NAME}"
ARTIFACT="artifacts/MTGA-Constructed-Testing-${VERSION}-linux-${ARCH}.tar.gz"

rm -rf build dist artifacts
mkdir -p artifacts
python -m PyInstaller --clean --noconfirm packaging/pyinstaller/client.spec
"${DIST}/${NAME}" --self-test
tar -C dist -czf "${ARTIFACT}" "${NAME}"
(cd artifacts && sha256sum "$(basename "${ARTIFACT}")") \
  > "artifacts/SHA256SUMS-linux-${ARCH}.txt"
