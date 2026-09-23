# Releasing installers

1. Confirm `pytest` and the packaged `--self-test` both pass.
2. Set the repository variable `CTA_DEFAULT_SERVER_URL` once production hosting exists, so testers never type a URL.
3. Push a version tag such as `v0.1.0`.
4. The release workflow builds Windows x64, macOS arm64, macOS x64, and Linux x64 installers on native runners.
5. Review the draft GitHub Release, its checksums, and the build attestations, then publish.

Builds are unsigned until credentials are available, so installation requires the approval steps described in the README.

## macOS signing and notarization

Without this, macOS tells every tester that "Apple could not verify this app is free of malware". Nothing short of notarization removes that message: ad-hoc signing, self-signed certificates and `codesign -s -` all still produce it, because Gatekeeper is asking whether Apple has seen the build, not whether it is signed.

That requires paid membership of the Apple Developer Program. Once enrolled, collect five values and add them as repository secrets:

| Secret | What it is |
| --- | --- |
| `APPLE_SIGNING_IDENTITY` | Full certificate name, e.g. `Developer ID Application: Your Name (TEAMID1234)` |
| `APPLE_CERTIFICATE` | The Developer ID Application certificate exported as `.p12`, then base64 encoded |
| `APPLE_CERTIFICATE_PASSWORD` | The password set when exporting that `.p12` |
| `APPLE_API_KEY` | App Store Connect API key `.p8` file, base64 encoded |
| `APPLE_API_KEY_ID` | The key's ID, shown next to it in App Store Connect |
| `APPLE_API_ISSUER` | The issuer UUID, shown above the key list |

Create the certificate under **Certificates, Identifiers & Profiles → Certificates** choosing **Developer ID Application** — not *Mac App Distribution*, which is for the App Store and cannot notarize. Export it from Keychain Access as `.p12`, then `base64 -i cert.p12 | pbcopy`.

Create the API key under **App Store Connect → Users and Access → Integrations → App Store Connect API** with the **Developer** role. The `.p8` downloads once and cannot be retrieved again. An API key is used rather than an Apple ID and app-specific password because it belongs to the team, is revocable on its own, and does not break when the account owner's 2FA changes.

The build refuses to run if some but not all of these are set, rather than quietly producing installers that warn every tester.

Signing happens inside PyInstaller rather than over the finished bundle: a frozen app contains hundreds of nested dylibs that must be signed innermost-first, and `codesign --deep` cannot apply entitlements to them. `packaging/macos/entitlements.plist` grants the two exemptions a frozen Python GUI needs under the hardened runtime — writable executable memory for CPython, and library validation disabled so Qt can load its plugins. Notarization requires the hardened runtime, and the hardened runtime denies both by default, so without that file the app would be notarized and then crash on launch.

Even when fully signed and notarized, the first launch still shows the ordinary "downloaded from the Internet" confirmation. That one cannot be removed and does not alarm testers.

## Windows signing

SmartScreen is a separate problem. It needs an Authenticode certificate, and a standard OV certificate still warns until the binary accumulates download reputation. Azure Trusted Signing or an EV certificate avoids that wait. Provide the PFX and its password as secrets; `build_windows.ps1` skips signing when they are absent.
