#!/bin/bash
# run.sh — VoiceInput.app から呼ばれて voice_input.py を常駐させる。
# ログは voice_input.py が自分で書いて世代交代させる（logs/voice_input.log と logs/history.jsonl）。
# ここで受けるのは起動時のエラーなど標準出力に出たものだけで、起動のたびに上書きする。
# モデルは取得済みのものだけを使い、起動時にネットへ出ない（HF_HUB_OFFLINE）。
# モデルを差し替えるときは、一度 HF_HUB_OFFLINE を外して手で起動し、取得させる。
set -u
export PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/bin:/bin"
export HF_HUB_OFFLINE=1
export HF_HUB_DISABLE_PROGRESS_BARS=1
export PYTHONUNBUFFERED=1
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# 設定（VOICE_INPUT_HOTKEY など）は config.env に書く。.app 経由の起動では環境変数を渡せないため
[ -f "$HERE/config.env" ] && . "$HERE/config.env"
LOG_DIR="${VOICE_INPUT_LOG_DIR:-$HERE/logs}"
mkdir -p "$LOG_DIR"
cd "$HERE" || exit 1
exec uv run --quiet voice_input.py "$@" > "$LOG_DIR/stderr.log" 2>&1
