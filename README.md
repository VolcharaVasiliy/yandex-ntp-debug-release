[English](README.md) | [Russian](README_RU.md)

# Safe Release Patch Kit

This repository contains the safe release bundle for the Yandex Browser patch kit.

## Highlights
- `PatchKit Launcher.exe`
  - fully standalone: you can download a single `.exe` and run it without installing Python and without keeping adjacent `.ps1/.cmd` files
  - the internal `scripts/*.py` payload is embedded into the EXE
  - graphical launcher with proper labels
  - action buttons plus numeric action selection
  - warns when Yandex Browser is still open
  - dedicated browser-close action
  - scrollable actions list
- GitHub Release:
  - `https://github.com/VolcharaVasiliy/yandex-ntp-debug-release/releases/tag/v2026.03.06-standalone`

## Strong Recommendation
- We very strongly recommend installing [Ghostery Privacy Ad Blocker](https://chromewebstore.google.com/detail/ghostery-%D0%B0%D0%BD%D1%82%D0%B8%D0%B1%D0%B0%D0%BD%D0%BD%D0%B5%D1%80/mlomiejdfkolichcflejclcbmpeaniij).
- For this patch bundle, it is one of the most useful add-ons for a cleaner and more comfortable browsing setup.
- Many thanks to the Ghostery team for building and maintaining such a solid extension.

## Included Safe Layers
- `run_apply_context_safe.ps1`
  - Google for selected text
  - `Ask ChatGPT` in the popup
  - working Google/OpenAI popup icons
- `run_apply_ntp_link_only.ps1`
  - changes only the top Alice button link on the new tab page
  - does not change text, icons, `apps.json`, `resources.pak`, or locale chunks
- `run_disable_ntp_banner.ps1`
  - disables the promotional banner and widgets on the new tab page separately

## Not Included
- The old broad patch is not included. That old layer modified `ru.pak`, `resources.pak`, `apps.json`, locale chunks, and the web app config for the new tab page all at once.
- Old release entrypoint scripts were removed from this release.

## Quick Start
1. Download `PatchKit Launcher.exe`.
2. Run it on a PC where Yandex Browser is already installed.
3. If the browser is open, the launcher will warn you and can close it for you.
4. Choose the action you need.
5. For a full apply, choose action `1` in the launcher.
6. For a full verification, choose action `2` in the launcher.

## Requirements On A Clean PC
- Windows with PowerShell
- Yandex Browser installed in the regular user profile location
- nothing else needs to be installed

## Launcher Actions
1. Apply all
2. Verify all
3. Close Yandex Browser
4. Apply Context Safe
5. Apply NTP Link Only
6. Disable NTP Banner
7. Verify Context Safe
8. Verify NTP Link Only
9. Verify NTP Banner
10. Restore New Tab Backup
11. Restore Banner Backup
12. Restore all

## Manual Run Without The Launcher
```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\run_apply_context_safe.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File .\run_apply_ntp_link_only.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File .\run_disable_ntp_banner.ps1
```

Verification:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\run_verify_context_safe.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File .\run_verify_ntp_link_only.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File .\run_verify_ntp_banner.ps1
```

## Restore
- `restore_all.cmd`
- or individually:
  - `run_restore_newtab_backup.ps1`
  - `run_restore_ntp_banner.ps1`

## Building The Launcher From Python
```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\build_patchkit_launcher.ps1
```

Launcher source: `patchkit_launcher.py`.
