# MTGA Constructed Testing Client

Uploads summarized MTG Arena match telemetry to your tournament testing group. It does not upload raw logs.

## Install

1. In Arena, open **Options → Account**, enable **Detailed Logs (Plugin Support)**, then restart Arena.
2. Open the latest [release](https://github.com/thomascleberg/mtga-constructed-testing-client/releases/latest).
3. Download and run:
   - Windows: `MTGA-Constructed-Testing-*-windows-x64-setup.exe`
   - Apple silicon Mac: `*-macos-arm64.dmg`
   - Intel Mac: `*-macos-x64.dmg`
4. Enter the username and password issued by your testing administrator.
5. Expand **Advanced** once and enter the server URL. This disappears from normal setup once the production URL is embedded.
6. Confirm the status says **Uploading**. Closing the window leaves the tray/menu-bar client running.

No Python or terminal is required.

### Unsigned installer warnings

The initial installers are unsigned. On Windows, choose **More info → Run anyway** if SmartScreen appears. On macOS, try opening the app once, then use **System Settings → Privacy & Security → Open Anyway**. Signing hooks are included for later releases.

## Development

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev,build]"
pytest
cta-client-gui
```

The CLI remains available as `cta-client --server … --username … --password …`.

## Privacy

Credentials are exchanged directly with the configured server. Passwords are never stored. Session tokens use Windows Credential Locker or macOS Keychain. Local logs are rotated and exclude passwords, tokens, opening hands, and raw Arena payloads.
