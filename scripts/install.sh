#!/usr/bin/env bash
# JobAgent installer for macOS and Linux.
#   • Python venv + `jobagent` command
#   • background service (launchd on macOS, systemd --user on Linux) so scans and alerts run on their own
#   • a launcher (JobAgent.app on macOS, a .desktop entry on Linux)
# Your data lives in ~/.jobagent (override with JOBAGENT_HOME), never inside this folder.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PY="$ROOT/.venv/bin/python"
PORT="${JOBAGENT_PORT:-8765}"
URL="http://127.0.0.1:$PORT"
OS="$(uname -s)"

command -v python3 >/dev/null || { echo "Python 3.10+ is required: https://www.python.org/downloads/"; exit 1; }
python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' || { echo "Python 3.10+ is required."; exit 1; }

echo "→ Python environment"
[ -x "$PY" ] || python3 -m venv "$ROOT/.venv"
"$ROOT/.venv/bin/pip" install -q --upgrade pip
"$ROOT/.venv/bin/pip" install -q -e "$ROOT"

echo "→ jobagent command"
mkdir -p "$HOME/.local/bin"
ln -sf "$ROOT/.venv/bin/jobagent" "$HOME/.local/bin/jobagent"
case ":$PATH:" in *":$HOME/.local/bin:"*) ;; *) echo "  (add ~/.local/bin to your PATH to use 'jobagent' everywhere)";; esac

SERVICE_PATH="$HOME/.local/bin:$HOME/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"
if [ "$OS" = "Darwin" ]; then
  echo "→ Background service (launchd)"
  LABEL="com.jobagent.server"; PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
  LOGDIR="${JOBAGENT_HOME:-$HOME/.jobagent}/logs"; mkdir -p "$HOME/Library/LaunchAgents" "$LOGDIR"
  cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key><array><string>$PY</string><string>-m</string><string>jobagent.cli</string><string>serve</string><string>--port</string><string>$PORT</string></array>
  <key>WorkingDirectory</key><string>$ROOT</string>
  <key>EnvironmentVariables</key><dict><key>PATH</key><string>$SERVICE_PATH</string>${JOBAGENT_HOME:+<key>JOBAGENT_HOME</key><string>$JOBAGENT_HOME</string>}</dict>
  <key>RunAtLoad</key><true/><key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>$LOGDIR/server.log</string><key>StandardErrorPath</key><string>$LOGDIR/server.err</string>
</dict></plist>
EOF
  launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
  launchctl bootstrap "gui/$(id -u)" "$PLIST"

  echo "→ JobAgent.app"
  APP="$HOME/Applications/JobAgent.app"; mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"
  cat > "$APP/Contents/Info.plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict><key>CFBundleName</key><string>JobAgent</string><key>CFBundleIdentifier</key><string>com.jobagent.app</string>
<key>CFBundleExecutable</key><string>JobAgent</string><key>CFBundleIconFile</key><string>icon</string><key>CFBundlePackageType</key><string>APPL</string></dict></plist>
EOF
  cat > "$APP/Contents/MacOS/JobAgent" <<EOF
#!/bin/bash
"$PY" -m jobagent.cli open --port $PORT
EOF
  chmod +x "$APP/Contents/MacOS/JobAgent"
  "$PY" "$ROOT/scripts/make_icon.py" "$APP/Contents/Resources/icon.icns" 2>/dev/null || true
else
  echo "→ Background service (systemd --user)"
  UNIT_DIR="$HOME/.config/systemd/user"; mkdir -p "$UNIT_DIR"
  cat > "$UNIT_DIR/jobagent.service" <<EOF
[Unit]
Description=JobAgent local server and scheduler
[Service]
ExecStart=$PY -m jobagent.cli serve --port $PORT
WorkingDirectory=$ROOT
Environment=PATH=$SERVICE_PATH
${JOBAGENT_HOME:+Environment=JOBAGENT_HOME=$JOBAGENT_HOME}
Restart=on-failure
[Install]
WantedBy=default.target
EOF
  if command -v systemctl >/dev/null && systemctl --user daemon-reload 2>/dev/null; then
    systemctl --user enable --now jobagent.service
  else
    echo "  systemd --user not available: start it with 'jobagent serve' (e.g. from your session autostart)."
  fi
  echo "→ Launcher"
  mkdir -p "$HOME/.local/share/applications"
  cat > "$HOME/.local/share/applications/jobagent.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=JobAgent
Exec=$PY -m jobagent.cli open --port $PORT
Terminal=false
Categories=Office;
EOF
fi

echo
echo "✅ Installed. Open $URL (or run: jobagent open) — the setup wizard starts on first launch."
echo "   Terminal setup instead: jobagent setup"
