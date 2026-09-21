# Releasing installers

1. Confirm `pytest` and the packaged `--self-test` both pass.
2. Set the repository variable `CTA_DEFAULT_SERVER_URL` once production hosting exists, so testers never type a URL.
3. Push a version tag such as `v0.1.0`.
4. The release workflow builds Windows x64, macOS arm64, and macOS x64 installers on native runners.
5. Review the draft GitHub Release, its checksums, and the build attestations, then publish.

Builds are unsigned until credentials are available, so installation requires the approval steps described in the README. To enable signing, provide the Windows PFX and password, or the Apple signing and notarization values, as GitHub Actions secrets. The platform build scripts skip signing when those values are absent.
