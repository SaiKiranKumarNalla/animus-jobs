#!/bin/zsh
# Installs Node.js (LTS) in ~/.local/node without admin rights, then the Codex and Gemini CLIs.
set -e
DEST="$HOME/.local/node"
mkdir -p "$HOME/.local" "$HOME/bin"
if [ ! -x "$DEST/bin/node" ]; then
  FILE=$(curl -fsSL https://nodejs.org/dist/latest-v22.x/SHASUMS256.txt | awk '/darwin-arm64.tar.gz$/{print $2}')
  echo "→ Downloading $FILE"
  TMP=$(mktemp -d)
  curl -fSL "https://nodejs.org/dist/latest-v22.x/$FILE" -o "$TMP/$FILE"
  curl -fsSL https://nodejs.org/dist/latest-v22.x/SHASUMS256.txt | grep " $FILE\$" | (cd "$TMP" && shasum -a 256 -c -)
  rm -rf "$DEST" && mkdir -p "$DEST"
  tar -xzf "$TMP/$FILE" -C "$DEST" --strip-components=1
  rm -rf "$TMP"
fi
export PATH="$DEST/bin:$PATH"
echo "→ node $(node -v), npm $(npm -v)"
npm config set prefix "$DEST"
npm install -g @openai/codex @google/gemini-cli
for b in node npm npx codex gemini; do ln -sf "$DEST/bin/$b" "$HOME/bin/$b"; done
echo
echo "✅ Installed. codex: $(command -v codex)  gemini: $(command -v gemini)"
echo "Next: run   codex login   (Sign in with ChatGPT), then   gemini   (Login with Google, then /quit)"
