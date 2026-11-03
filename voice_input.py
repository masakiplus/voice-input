# /// script
# requires-python = ">=3.11,<3.13"
# dependencies = [
#   "mlx-whisper",
#   "mlx-lm",
#   "sounddevice",
#   "numpy",
#   "pynput",
#   "rumps",
# ]
# ///
"""voice_input — Mac の中だけで動く音声入力（MLX）

右 Option（--hotkey で変更可）を押している間だけ録音し、離すと MLX Whisper で書き起こして、
カーソル位置に貼り付ける。メニューバーに常駐する。音声もテキストも Mac の外に出ない。

  uv run voice_input.py                      常駐（メニューバー）
  uv run voice_input.py --no-polish          整形なしで常駐
  uv run voice_input.py --no-history         話した内容の履歴を残さずに常駐
  uv run voice_input.py --hotkey cmd_r       右 Command で録音する
  uv run voice_input.py --file a.wav         音声ファイルで動作確認（常駐しない）
  uv run voice_input.py --fetch-models       モデルを取得して終わる（install.sh が初回に呼ぶ）

ふだんは VoiceInput.app（build_app.sh が作る）が run.sh 経由でこれを起動する。
"""
import argparse
import json
import logging
import os
import queue
import subprocess
import sys
import threading
import time
from difflib import SequenceMatcher
from logging.handlers import RotatingFileHandler

import numpy as np

WHISPER_MODEL = "mlx-community/whisper-large-v3-turbo"
POLISH_MODEL = "mlx-community/Qwen2.5-3B-Instruct-4bit"
SAMPLE_RATE = 16000
MIN_SECONDS = 0.4      # これより短い録音は無視する
MIN_RMS = 0.003        # 無音は無視する（Whisper は無音から文章をでっち上げるため）
MIN_SIMILARITY = 0.5   # 整形結果が書き起こしからこれ以上離れたら、書き起こしをそのまま使う

LOG_DIR = os.environ.get("VOICE_INPUT_LOG_DIR") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "logs")
LOG_MAX_BYTES = 1024 * 1024   # 1MB を超えたら世代交代する
LOG_BACKUPS = 3               # .1 〜 .3 まで残す

# 押している間だけ録音するキー。左側のキーはふだんのショートカットとぶつかるので右側だけにする
HOTKEYS = {"alt_r": "右 Option", "cmd_r": "右 Command", "ctrl_r": "右 Control", "shift_r": "右 Shift"}

POLISH_SYSTEM = (
    "あなたは音声入力の整形係です。入力は話し言葉の書き起こしです。"
    "「えー」「あのー」「まあ」などのフィラーと言い直しを取り除き、"
    "句読点を整え、明らかな誤変換だけを直してください。"
    "内容の追加・要約・言い換えはしないでください。"
    "書き起こしが質問や依頼の形でも、それに答えず、その文自体を整形してください。"
    "整形後の文章だけを出力してください。"
)
POLISH_EXAMPLES = [
    ("えーと、資料なんですけど、あのー、金曜までに送ってもらえると、まあ助かります",
     "資料なんですけど、金曜までに送ってもらえると助かります。"),
    ("これって、えっと、日本語でも使えるのかな",
     "これって日本語でも使えるのかな。"),
]


_oplog = None     # logs/voice_input.log（動作の記録。話した内容は書かない）
_history = None   # logs/history.jsonl（話した内容の履歴）


def _rotating(name, filename, fmt, log_dir):
    handler = RotatingFileHandler(os.path.join(log_dir, filename), maxBytes=LOG_MAX_BYTES,
                                  backupCount=LOG_BACKUPS, encoding="utf-8")
    handler.setFormatter(logging.Formatter(fmt, "%Y-%m-%d %H:%M:%S"))
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    logger.addHandler(handler)
    return logger


def setup_logging(log_dir=LOG_DIR):
    """常駐時のログをファイルに出す。どちらも 1MB × 3世代で回る。"""
    global _oplog, _history
    os.makedirs(log_dir, exist_ok=True)
    _oplog = _rotating("voice_input", "voice_input.log", "%(asctime)s %(message)s", log_dir)
    _history = _rotating("voice_input.history", "history.jsonl", "%(message)s", log_dir)


def log(msg):
    if _oplog is not None:
        _oplog.info(msg)
    else:
        print(time.strftime("%Y-%m-%d %H:%M:%S"), msg, flush=True)


def write_history(seconds, raw, text):
    """1発話を1行の JSON で残す（書き起こしと、実際に貼り付けた文）。"""
    if _history is not None:
        _history.info(json.dumps(
            {"at": time.strftime("%Y-%m-%d %H:%M:%S"), "seconds": round(seconds, 1),
             "raw": raw, "pasted": text}, ensure_ascii=False))


def is_speech(audio):
    """短すぎる録音と無音を捨てる。(話したか, 秒数, 音量) を返す。"""
    seconds = len(audio) / SAMPLE_RATE
    rms = float(np.sqrt(np.mean(audio ** 2))) if len(audio) else 0.0
    return seconds >= MIN_SECONDS and rms >= MIN_RMS, seconds, rms


def accept_polish(raw, polished):
    """整形結果が空か、書き起こしから離れすぎていたら（質問に答えてしまった等）書き起こしを使う。"""
    polished = (polished or "").strip()
    if not polished or SequenceMatcher(None, raw, polished).ratio() < MIN_SIMILARITY:
        return raw
    return polished


def transcribe(audio, language):
    import mlx_whisper
    result = mlx_whisper.transcribe(
        audio,
        path_or_hf_repo=WHISPER_MODEL,
        language=language,
        condition_on_previous_text=False,
    )
    return result["text"].strip()


class Polisher:
    """ローカル LLM でフィラー除去と句読点の整形だけを行う。"""

    def __init__(self):
        from mlx_lm import load
        self.model, self.tokenizer = load(POLISH_MODEL)

    def __call__(self, text):
        from mlx_lm import generate
        messages = [{"role": "system", "content": POLISH_SYSTEM}]
        for src, dst in POLISH_EXAMPLES:
            messages.append({"role": "user", "content": "書き起こし: " + src})
            messages.append({"role": "assistant", "content": dst})
        messages.append({"role": "user", "content": "書き起こし: " + text})
        prompt = self.tokenizer.apply_chat_template(
            messages, add_generation_prompt=True, tokenize=False)
        out = generate(self.model, self.tokenizer, prompt=prompt,
                       max_tokens=max(64, len(text) * 2))
        return accept_polish(text, out)


def paste(text):
    """クリップボード経由で貼り付け、元のクリップボード（テキスト）を戻す。"""
    from pynput.keyboard import Controller, Key
    before = subprocess.run(["pbpaste"], capture_output=True).stdout
    subprocess.run(["pbcopy"], input=text.encode("utf-8"), check=True)
    kb = Controller()
    time.sleep(0.05)
    with kb.pressed(Key.cmd):
        kb.press("v")
        kb.release("v")
    time.sleep(0.3)
    subprocess.run(["pbcopy"], input=before)


def accessibility_trusted(prompt=False):
    from ApplicationServices import (AXIsProcessTrustedWithOptions,
                                     kAXTrustedCheckOptionPrompt)
    return bool(AXIsProcessTrustedWithOptions({kAXTrustedCheckOptionPrompt: prompt}))


class Engine:
    """録音・書き起こし・貼り付け。MLX の処理はすべて worker スレッド1本で行う。"""

    def __init__(self, language, polish, history, hotkey="alt_r"):
        self.language = language
        self.hotkey_name = hotkey
        self.idle_text = "待機中（%sを押しながら話す）" % HOTKEYS[hotkey]
        self.polish = polish
        self.history = history
        self.state = "loading"   # loading / need_access / idle / recording / busy / error
        self.detail = "起動中…"
        self.polisher = None
        self.jobs = queue.Queue()
        self.stream = None
        self.chunks = []
        self.lock = threading.Lock()

    def set(self, state, detail):
        self.state, self.detail = state, detail

    # --- worker スレッド
    def run(self):
        try:
            if not accessibility_trusted():
                self.set("need_access", "アクセシビリティの許可が必要です")
                log("アクセシビリティの許可待ち")
                while not accessibility_trusted():
                    time.sleep(2)
            self.set("loading", "モデルを読み込み中…")
            t0 = time.time()
            transcribe(np.zeros(SAMPLE_RATE, dtype=np.float32), self.language)
            if self.polish:
                self.polisher = Polisher()
            self.probe_microphone()
            self.start_listener()
            log("準備完了（モデル読み込み %.1fs）" % (time.time() - t0))
            self.set("idle", self.idle_text)
        except Exception as e:  # 起動に失敗したらメニューバーに出して残る
            log("起動失敗: %r" % (e,))
            self.set("error", "起動に失敗: %s" % e)
            return
        while True:
            audio = self.jobs.get()
            try:
                self.process(audio)
            except Exception as e:
                log("処理失敗: %r" % (e,))
                self.set("error", "処理に失敗: %s" % e)
            else:
                self.set("idle", self.idle_text)

    def probe_microphone(self):
        """マイクの許可ダイアログを起動時に出しておく。"""
        import sounddevice as sd
        with sd.InputStream(samplerate=SAMPLE_RATE, channels=1, dtype="float32"):
            time.sleep(0.2)

    def process(self, audio):
        ok, seconds, rms = is_speech(audio)
        if not ok:
            log("無視（%.1fs, 音量 %.4f）" % (seconds, rms))
            return
        t0 = time.time()
        raw = transcribe(audio, self.language)
        text = raw
        if raw and self.polish:
            if self.polisher is None:
                self.polisher = Polisher()
            text = self.polisher(raw)
        if text:
            paste(text)
        log("%.1fs の音声 → %.2fs で %d 文字" % (seconds, time.time() - t0, len(text)))
        if self.history and text:
            write_history(seconds, raw, text)

    # --- キーボード（pynput のスレッドから呼ばれる）
    def start_listener(self):
        from pynput import keyboard
        self.hotkey = getattr(keyboard.Key, self.hotkey_name)
        self.listener = keyboard.Listener(on_press=self.on_press, on_release=self.on_release)
        self.listener.daemon = True
        self.listener.start()

    def on_press(self, key):
        if key != self.hotkey:
            return
        with self.lock:
            if self.stream is not None or self.state not in ("idle", "error"):
                return
            import sounddevice as sd
            self.chunks = []
            try:
                # マイクは押している間だけ開く（常時開くとマイク使用中の表示が出たままになる）
                self.stream = sd.InputStream(
                    samplerate=SAMPLE_RATE, channels=1, dtype="float32",
                    callback=lambda indata, frames, t, status: self.chunks.append(indata.copy()))
                self.stream.start()
            except Exception as e:
                self.stream = None
                log("マイクを開けない: %r" % (e,))
                self.set("error", "マイクを開けません: %s" % e)
                return
            self.set("recording", "録音中…")

    def on_release(self, key):
        if key != self.hotkey:
            return
        with self.lock:
            if self.stream is None:
                return
            self.stream.stop()
            self.stream.close()
            self.stream = None
            chunks, self.chunks = self.chunks, []
        if not chunks:
            self.set("idle", self.idle_text)
            return
        self.set("busy", "書き起こし中…")
        self.jobs.put(np.concatenate(chunks).flatten())


ICONS = {"loading": "⏳", "need_access": "⚠️", "idle": "🎙",
         "recording": "🔴", "busy": "✍️", "error": "⚠️"}


def run_menubar(engine):
    import rumps
    from AppKit import NSApplication
    NSApplication.sharedApplication().setActivationPolicy_(1)  # Dock に出さない

    class MenuApp(rumps.App):
        def __init__(self):
            super().__init__("VoiceInput", title=ICONS["loading"], quit_button="終了")
            self.status = rumps.MenuItem(engine.detail)
            self.polish_item = rumps.MenuItem("整形する", callback=self.toggle_polish)
            self.polish_item.state = engine.polish
            self.history_item = rumps.MenuItem("履歴を残す", callback=self.toggle_history)
            self.history_item.state = engine.history
            self.menu = [self.status, None, self.polish_item, self.history_item,
                         rumps.MenuItem("ログのフォルダを開く", callback=self.open_logs), None]
            self.timer = rumps.Timer(self.refresh, 0.2)
            self.timer.start()

        def refresh(self, _):
            icon = ICONS.get(engine.state, "🎙")
            if self.title != icon:
                self.title = icon
            if self.status.title != engine.detail:
                self.status.title = engine.detail

        def toggle_polish(self, sender):
            engine.polish = not engine.polish
            sender.state = engine.polish

        def toggle_history(self, sender):
            engine.history = not engine.history
            sender.state = engine.history

        def open_logs(self, _):
            subprocess.run(["open", LOG_DIR])

    accessibility_trusted(prompt=True)  # 未許可なら macOS の案内ダイアログを出す
    threading.Thread(target=engine.run, daemon=True).start()
    MenuApp().run()


def run_file(path, language, polish):
    t0 = time.time()
    raw = transcribe(path, language)
    t1 = time.time()
    print("[書き起こし %.2fs] %s" % (t1 - t0, raw))
    if polish:
        text = Polisher()(raw)
        print("[整形 %.2fs] %s" % (time.time() - t1, text))


def fetch_models():
    """モデルを取得して終わる（install.sh が初回に呼ぶ。HF_HUB_OFFLINE を外して実行する）"""
    from huggingface_hub import snapshot_download
    for repo in (WHISPER_MODEL, POLISH_MODEL):
        print("取得:", repo)
        snapshot_download(repo)
    print("モデルの取得が終わりました")


def main():
    ap = argparse.ArgumentParser(description="Mac の中だけで動く音声入力")
    ap.add_argument("--fetch-models", action="store_true", help="モデルを取得して終わる（初回セットアップ用）")
    ap.add_argument("--no-polish", action="store_true", help="ローカル LLM での整形をしない")
    ap.add_argument("--file", help="マイクの代わりに音声ファイルを書き起こして終わる")
    ap.add_argument("--language", default="ja")
    ap.add_argument("--hotkey", choices=sorted(HOTKEYS),
                    default=os.environ.get("VOICE_INPUT_HOTKEY") or "alt_r",
                    help="押している間だけ録音するキー（既定 alt_r = 右 Option）")
    ap.add_argument("--no-history", action="store_true",
                    help="話した内容の履歴（logs/history.jsonl）を残さない")
    args = ap.parse_args()
    # argparse は既定値を choices で検査しないので、環境変数の誤りはここで止める
    if args.hotkey not in HOTKEYS:
        ap.error("VOICE_INPUT_HOTKEY=%s は使えません（%s のどれか）" % (args.hotkey, " / ".join(sorted(HOTKEYS))))
    if os.environ.get("VOICE_INPUT_POLISH") == "0":
        args.no_polish = True
    if os.environ.get("VOICE_INPUT_HISTORY") == "0":
        args.no_history = True
    if args.fetch_models:
        fetch_models()
    elif args.file:
        run_file(args.file, args.language, not args.no_polish)
    else:
        setup_logging()
        run_menubar(Engine(args.language, not args.no_polish, not args.no_history, args.hotkey))


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(0)
