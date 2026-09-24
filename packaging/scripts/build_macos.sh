#!/usr/bin/env bash
set -euo pipefail

VERSION="${APP_VERSION:-$(python3 -c 'import tomllib; print(tomllib.load(open("pyproject.toml", "rb"))["project"]["version"])')}"
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

sign_with_timestamp() {
  # Apple's timestamp service rate-limits, and refused partway through the
  # first real run of this script after the hundreds of signatures inside
  # the bundle. A signature without a trusted timestamp is no good to
  # notarization, so a refusal is waited out rather than accepted.
  local target="$1" attempt
  for attempt in 1 2 3 4 5; do
    if codesign --force --timestamp --sign "${APPLE_SIGNING_IDENTITY}" "${target}"; then
      return 0
    fi
    echo "Timestamp service refused; retrying in $((attempt * 15))s" >&2
    sleep $((attempt * 15))
  done
  echo "Could not obtain a trusted timestamp for ${target}." >&2
  return 1
}

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
  # Captured first rather than piped: grep -q closes the pipe on its first
  # match, codesign dies of SIGPIPE, and pipefail then reports the whole
  # pipeline as failed precisely when the match succeeded.
  SIGNATURE="$(codesign --display --verbose=4 "${APP}" 2>&1)"
  if ! grep -qE 'flags=0x[0-9a-f]+\(runtime\)' <<< "${SIGNATURE}"; then
    echo "The bundle is signed but without the hardened runtime." >&2
    exit 1
  fi
fi

cp -R "${APP}" dmg-root/
ln -s /Applications dmg-root/Applications
create-dmg --overwrite --skip-jenkins \
  --volname "MTGA Constructed Testing" \
  "${ARTIFACT}" dmg-root

if [[ "${SIGNED}" == "yes" ]]; then
  # The image is signed too: it is the file the tester downloads, and it
  # is what carries the stapled notarization ticket.
  sign_with_timestamp "${ARTIFACT}"
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
