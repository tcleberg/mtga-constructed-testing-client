# MTGA Constructed Testing Client

Uploads summarized MTG Arena match telemetry to your tournament testing group. It does not upload raw logs.

## Install

1. In Arena, open **Options → Account**, enable **Detailed Logs (Plugin Support)**, then restart Arena.
2. Open the latest [release](https://github.com/thomascleberg/mtga-constructed-testing-client/releases/latest).
3. Download and run:
   - Windows: `MTGA-Constructed-Testing-*-windows-x64-setup.exe`
   - Apple silicon Mac: `*-macos-arm64.dmg`
   - Intel Mac: `*-macos-x64.dmg`
4. Enter your group's server (for example `omaha.mtgtest.com`) and the username and password issued by its administrator.
5. Confirm the status says **Uploading**. Closing the window leaves the tray/menu-bar client running.

No Python or terminal is required.

## More than one testing group

A tester can belong to several groups. Choose **Add another group** and sign in again; each group keeps its own account, its own upload queue, and its own dashboard.

Every completed game is sent to all of them. The groups are independent, so one being down or ending your session there has no effect on the others: the client says how many are up, keeps the unsent work for the group that is offline, and delivers it when that group comes back.

## Your group's dashboard

Signing in opens your group's site once, in your browser, already signed in. After that you visit the dashboard normally and it recognises you; there is no second password to remember. The link that does this is single use and expires within a minute, and an administrator can end your dashboard access at any time.

If you ever land on the sign-in page, use **Open dashboard** in the client.

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

The CLI remains available. `cta-client --server … --username … --password …` signs in to a group and adds it; `cta-client` with no arguments uploads to every group already signed in.

## Privacy

Credentials are exchanged directly with each group's server, and nothing is shared between groups. Passwords are never stored. Session tokens use Windows Credential Locker or macOS Keychain, keyed per group. Local logs are rotated and exclude passwords, tokens, opening hands, and raw Arena payloads.
