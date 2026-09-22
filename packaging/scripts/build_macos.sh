#!/usr/bin/env bash
set -euo pipefail

VERSION="${APP_VERSION:-0.2.0}"
ARCH="${TARGET_ARCH:-$(uname -m)}"
APP="dist/MTGA Constructed Testing.app"
ARTIFACT="artifacts/MTGA-Constructed-Testing-${VERSION}-macos-${ARCH}.dmg"

# Either every signing credential is present or none are. A half-configured
# release - a renamed secret, an expired cert - would otherwise quietly ship
# installers that warn every tester, which is the failure this exists to
# prevent, so it is refused up front instead.
CREDENTIALS=(APPLE_SIGNING_IDENTITY APPLE_API_KEY_PATH APPLE_API_KEY_ID APPLE_API_ISSUER)
present=()
missing=()
for name in "${CREDENTIALS[@]}"; do
  if [[ -n "${!name:-}" ]]; then present+=("${name}"); else missing+=("${name}"); fi
done
if [[ ${#present[@]} -gt 0 && ${#missing[@]} -gt 0 ]]; then
  echo "Signing is half configured. Present: ${present[*]}. Missing: ${missing[*]}." >&2
  exit 1
fi
SIGNED=$([[ ${#missing[@]} -eq 0 ]] && echo yes || echo no)
if [[ "${SIGNED}" == "no" ]]; then
  echo "WARNING: building unsigned. macOS will warn that Apple cannot verify this app." >&2
fi

rm -rf build dist artifacts dmg-root
mkdir -p artifacts dmg-root
# Signs the bundle as it is assembled when APPLE_SIGNING_IDENTITY is set.
python -m PyInstaller --clean --noconfirm packaging/pyinstaller/client.spec
"${APP}/Contents/MacOS/MTGA Constructed Testing" --self-test

if [[ "${SIGNED}" == "yes" ]]; then
  codesign --verify --strict --verbose=2 "${APP}"
  # The hardened runtime is what notarization is checking for, and it is
  # applied by PyInstaller rather than here, so confirm it actually landed
  # rather than finding out from a rejection minutes later.
  codesign --display --verbose=4 "${APP}" 2>&1 | grep -qE '^CodeDirectory .*flags=.*runtime' || {
    echo "The bundle is signed but without the hardened runtime." >&2
    exit 1
  }
fi

cp -R "${APP}" dmg-root/
ln -s /Applications dmg-root/Applications
create-dmg --overwrite --skip-jenkins \
  --volname "MTGA Constructed Testing" \
  "${ARTIFACT}" dmg-root

if [[ "${SIGNED}" == "yes" ]]; then
  # The image is signed too: it is the file the tester downloads, and it
  # is what carries the stapled notarization ticket.
  codesign --force --timestamp --sign "${APPLE_SIGNING_IDENTITY}" "${ARTIFACT}"
  # An API key rather than an Apple ID and app-specific password: it is
  # owned by the team, revocable, and unaffected by the account owner's 2FA.
  xcrun notarytool submit "${ARTIFACT}" --wait \
    --key "${APPLE_API_KEY_PATH}" \
    --key-id "${APPLE_API_KEY_ID}" \
    --issuer "${APPLE_API_ISSUER}"
  # Stapling is what lets a tester's Mac verify the app while offline.
  xcrun stapler staple "${ARTIFACT}"
  xcrun stapler validate "${ARTIFACT}"
  # The last word belongs to Gatekeeper itself, which is the thing the
  # tester will actually meet.
  spctl --assess --type open --context context:primary-signature -vv "${ARTIFACT}"
fi

(cd artifacts && shasum -a 256 "$(basename "${ARTIFACT}")") \
  > "artifacts/SHA256SUMS-macos-${ARCH}.txt"
