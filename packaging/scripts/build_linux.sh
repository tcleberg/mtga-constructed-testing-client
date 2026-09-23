#!/usr/bin/env bash
set -euo pipefail

VERSION="${APP_VERSION:-0.3.0}"
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
