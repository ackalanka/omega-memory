# OMEGA Installers

One-click installers for non-technical Claude Desktop users.

- **macOS**: `.pkg` installer (arm64 + Intel)
- **Windows**: `.exe` installer (64-bit)

---

# macOS Installer (.pkg)

## What it does

1. Installs bundled Python 3.12 (python-build-standalone) + omega-memory to `~/Library/OMEGA`
2. Configures Claude Desktop to use OMEGA as an MCP server
3. No admin privileges required (per-user install)

## Prerequisites

- macOS 12 (Monterey) or later
- Apple Silicon (M1+) or Intel Mac
- Claude Desktop installed
- Internet connection (for embedding model download on first use)

## Building locally

### Requirements

- macOS machine
- Internet connection (downloads ~60 MB python-build-standalone)
- No additional tools needed (uses built-in `pkgbuild`/`productbuild`)

### Steps

```bash
cd installer
./build-macos-pkg.sh
```

Output: `build/macos/dist/OMEGA-Memory.pkg`

### Automated build

Push a release tag or trigger the `Build macOS Installer` workflow manually in GitHub Actions. The workflow runs on `macos-latest` and handles everything automatically.

## Testing checklist

- [ ] Run `OMEGA-Memory.pkg` on a clean macOS install (no Python installed)
- [ ] Verify install completes without errors
- [ ] Check `~/Library/OMEGA/python/bin/python3` exists
- [ ] Check `~/Library/Application Support/Claude/claude_desktop_config.json` has `omega-memory` entry
- [ ] Check `.json.bak` backup exists
- [ ] Restart Claude Desktop, verify OMEGA tools appear
- [ ] Say "hello" to Claude, verify `omega_welcome` works
- [ ] Run `~/Library/OMEGA/uninstall-omega.sh`, verify `omega-memory` entry removed
- [ ] Verify `~/.omega` data directory is preserved after uninstall

## Architecture

```
~/Library/OMEGA/                    <- install directory
  python/                           <- python-build-standalone 3.12
    bin/python3
    lib/python3.12/site-packages/   <- omega-memory package
  configure_claude.py               <- post-install/uninstall config script
  uninstall-omega.sh                <- uninstall script

~/.omega/                           <- data directory (preserved on uninstall)
  omega.db                          <- memory database
  models/                           <- ONNX embedding model (downloaded on first use)

~/Library/Application Support/Claude/
  claude_desktop_config.json        <- Claude Desktop config (OMEGA entry injected)
  claude_desktop_config.json.bak    <- backup of original config
```

---

# Windows Installer (.exe)

One-click installer (.exe) for non-technical Claude Desktop users on Windows.

## What it does

1. Installs a bundled Python 3.12 + omega-memory to `%LOCALAPPDATA%\OMEGA`
2. Configures Claude Desktop to use OMEGA as an MCP server
3. No admin privileges required

## Prerequisites

- Windows 10/11 (64-bit)
- Claude Desktop installed
- Internet connection (for embedding model download on first use)

## Building locally

### Requirements

- Windows machine (or VM)
- [Inno Setup 6](https://jrsoftware.org/isinfo.php) installed
- Internet connection

### Steps

```powershell
# 1. Download Python 3.12 embeddable
mkdir build\python
Invoke-WebRequest -Uri "https://www.python.org/ftp/python/3.12.8/python-3.12.8-embed-amd64.zip" -OutFile build\python.zip
Expand-Archive build\python.zip -DestinationPath build\python -Force
Remove-Item build\python.zip

# 2. Download get-pip.py
Invoke-WebRequest -Uri "https://bootstrap.pypa.io/get-pip.py" -OutFile build\get-pip.py

# 3. Build installer
& "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" omega-setup.iss
```

Output: `dist\omega-setup.exe`

### Automated build

Push a release tag or trigger the `Build Windows Installer` workflow manually in GitHub Actions. The workflow handles all download and build steps automatically.

## Testing checklist

- [ ] Run `omega-setup.exe` on a clean Windows VM (no Python installed)
- [ ] Verify install completes without errors
- [ ] Check `%LOCALAPPDATA%\OMEGA\python\python.exe` exists
- [ ] Check `%APPDATA%\Claude\claude_desktop_config.json` has `omega-memory` entry
- [ ] Check `%APPDATA%\Claude\claude_desktop_config.json.bak` backup exists
- [ ] Restart Claude Desktop, verify OMEGA tools appear
- [ ] Say "hello" to Claude, verify `omega_welcome` works
- [ ] Run uninstaller, verify `omega-memory` entry removed from Claude Desktop config
- [ ] Verify `%USERPROFILE%\.omega` data directory is preserved after uninstall

## Architecture

```
%LOCALAPPDATA%\OMEGA\           <- install directory
  python\                       <- Python 3.12 embeddable + site-packages
    python.exe
    Lib\site-packages\omega\    <- omega-memory package
  configure_claude.py           <- post-install/uninstall config script
  get-pip.py                    <- pip bootstrapper (used during install)

%USERPROFILE%\.omega\           <- data directory (preserved on uninstall)
  omega.db                      <- memory database
  models\                       <- ONNX embedding model (downloaded on first use)

%APPDATA%\Claude\
  claude_desktop_config.json    <- Claude Desktop config (OMEGA entry injected)
  claude_desktop_config.json.bak <- backup of original config
```

## Transport

On Windows, the hook server uses TCP `127.0.0.1:19876` instead of Unix domain sockets. The embedding daemon is not used; ONNX models load in-process instead.
