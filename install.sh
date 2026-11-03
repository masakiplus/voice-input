#!/bin/bash
# install.sh — 新しい Mac での初回セットアップ（どこに展開しても動く）
#
# 使い方:  bash install.sh
#   1. uv が無ければ入れる
#   2. モデルを取得する（初回だけネットへ出る。約 1.5GB + 2GB）
#   3. ~/Applications/VoiceInput.app を作る
#   4. ログイン時に自動で開くよう launchd に登録する
#   5. 起動する → マイク／アクセシビリティ／入力監視の許可を付ける
set -eu
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LABEL="${VOICE_INPUT_BUNDLE_ID:-local.voiceinput}"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"

echo "[1/5] uv"
if ! command -v uv >/dev/null 2>&1 && [ ! -x "$HOME/.local/bin/uv" ]; then
  curl -LsSf https://astral.sh/uv/install.sh | sh
fi
export PATH="$HOME/.local/bin:/opt/homebrew/bin:$PATH"

echo "[2/5] モデル取得（初回のみ。既にあれば一瞬で終わる）"
cd "$HERE"
HF_HUB_OFFLINE=0 uv run --quiet voice_input.py --fetch-models

echo "[3/5] VoiceInput.app"
bash "$HERE/build_app.sh"

echo "[4/5] launchd（ログイン時に自動起動）"
mkdir -p "$HOME/Library/LaunchAgents"
launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
cat > "$PLIST" <<PL
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key>
  <array><string>/usr/bin/open</string><string>-a</string><string>$HOME/Applications/VoiceInput.app</string></array>
  <key>RunAtLoad</key><true/>
</dict>
</plist>
PL
launchctl bootstrap "gui/$(id -u)" "$PLIST"

echo "[5/5] 起動"
open -a "$HOME/Applications/VoiceInput.app"
cat <<MSG

できました。システム設定 → プライバシーとセキュリティ で VoiceInput に許可を付けてください:
  - マイク（ダイアログが出る）
  - アクセシビリティ（案内が出る）
  - 入力監視（録音キーを押しても 🔴 にならないとき）
メニューバーが ⏳ → 🎙 になったら、テキスト欄で右 Option（config.env で変更可）を押しながら話してください。
MSG
