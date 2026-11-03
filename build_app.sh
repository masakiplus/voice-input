#!/bin/bash
# build_app.sh — ~/Applications/VoiceInput.app を作る（作り直すと許可の付け直しが要る）
#
# 使い方:  bash build_app.sh
set -eu
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP="$HOME/Applications/VoiceInput.app"
# 許可（マイク・アクセシビリティ）は macOS がこの識別子で覚える。変えると許可の付け直しが要る
BUNDLE_ID="${VOICE_INPUT_BUNDLE_ID:-local.voiceinput}"
mkdir -p "$APP/Contents/MacOS"
sed "s/__BUNDLE_ID__/$BUNDLE_ID/" "$HERE/app/Info.plist" > "$APP/Contents/Info.plist"
# run.sh の絶対パスを埋め込む。フォルダを動かしたらもう一度走らせる（許可の付け直しが要る）
/usr/bin/cc -O2 -DRUN_SH="\"$HERE/run.sh\"" -o "$APP/Contents/MacOS/VoiceInput" "$HERE/app/launcher.c"
/usr/bin/codesign --force --sign - --identifier "$BUNDLE_ID" "$APP"
echo "built: $APP"
