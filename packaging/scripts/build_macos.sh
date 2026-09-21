#!/usr/bin/env bash
set -euo pipefail

VERSION="${APP_VERSION:-0.1.0}"
ARCH="${TARGET_ARCH:-$(uname -m)}"
APP="dist/MTGA Constructed Testing.app"
ARTIFACT="artifacts/MTGA-Constructed-Testing-${VERSION}-macos-${ARCH}.dmg"

rm -rf build dist artifacts dmg-root
mkdir -p artifacts dmg-root
python -m PyInstaller --clean --noconfirm packaging/pyinstaller/client.spec
"${APP}/Contents/MacOS/MTGA Constructed Testing" --self-test

if [[ -n "${APPLE_SIGNING_IDENTITY:-}" ]]; then
  codesign --force --deep --options runtime --timestamp \
    --sign "${APPLE_SIGNING_IDENTITY}" "${APP}"
  codesign --verify --deep --strict "${APP}"
fi

cp -R "${APP}" dmg-root/
ln -s /Applications dmg-root/Applications
create-dmg --overwrite --no-code-sign \
  --volname "MTGA Constructed Testing" \
  "${ARTIFACT}" dmg-root

if [[ -n "${APPLE_ID:-}" && -n "${APPLE_TEAM_ID:-}" && -n "${APPLE_APP_PASSWORD:-}" ]]; then
  xcrun notarytool submit "${ARTIFACT}" --wait \
    --apple-id "${APPLE_ID}" \
    --team-id "${APPLE_TEAM_ID}" \
    --password "${APPLE_APP_PASSWORD}"
  xcrun stapler staple "${ARTIFACT}"
fi

shasum -a 256 "${ARTIFACT}" |
  awk '{print $1 "  " substr($0, index($0,$2))}' \
  > "artifacts/SHA256SUMS-macos-${ARCH}.txt"
