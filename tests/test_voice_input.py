"""MLX もマイクも使わずに確かめられる部分のテスト（CI の Linux でも動く。要 numpy）。

  python3 tests/test_voice_input.py
"""
import json
import os
import sys
import tempfile

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import voice_input as vi  # noqa: E402


def test_is_speech_rejects_short_and_silent():
    sr = vi.SAMPLE_RATE
    tone = (0.1 * np.sin(np.linspace(0, 440 * 2 * np.pi, sr))).astype(np.float32)
    assert vi.is_speech(tone)[0]                                   # 1秒・十分な音量
    assert not vi.is_speech(tone[: int(sr * 0.2)])[0]              # 短すぎる
    assert not vi.is_speech(np.zeros(sr, dtype=np.float32))[0]     # 無音
    assert not vi.is_speech(np.zeros(0, dtype=np.float32))[0]      # 空


def test_accept_polish_keeps_close_result():
    raw = "えーと資料なんですけど金曜までに送ってもらえると助かります"
    out = "資料なんですけど、金曜までに送ってもらえると助かります。"
    assert vi.accept_polish(raw, out) == out


def test_accept_polish_falls_back_when_model_answers():
    raw = "これって日本語でも使えるのかな"
    answer = "はい、このツールは英語・中国語・韓国語など多くの言語に対応しています。"
    assert vi.accept_polish(raw, answer) == raw
    assert vi.accept_polish(raw, "") == raw
    assert vi.accept_polish(raw, None) == raw


def test_history_is_one_json_per_line():
    with tempfile.TemporaryDirectory() as d:
        vi.setup_logging(d)
        vi.write_history(1.234, "えーとテスト", "テスト。")
        vi.write_history(2.0, "二回目", "二回目。")
        for h in vi._history.handlers:
            h.flush()
        lines = open(os.path.join(d, "history.jsonl"), encoding="utf-8").read().splitlines()
        assert len(lines) == 2
        first = json.loads(lines[0])
        assert first["raw"] == "えーとテスト" and first["pasted"] == "テスト。"
        assert first["seconds"] == 1.2


def test_hotkey_labels():
    assert set(vi.HOTKEYS) == {"alt_r", "cmd_r", "ctrl_r", "shift_r"}
    assert all(label.startswith("右 ") for label in vi.HOTKEYS.values())


def test_bad_hotkey_env_is_rejected():
    import subprocess
    script = os.path.join(os.path.dirname(os.path.abspath(vi.__file__)), "voice_input.py")
    env = dict(os.environ, VOICE_INPUT_HOTKEY="alt_l")
    p = subprocess.run([sys.executable, script, "--file", "x.wav"], env=env, capture_output=True, text=True)
    assert p.returncode == 2 and "VOICE_INPUT_HOTKEY=alt_l" in p.stderr


if __name__ == "__main__":
    n = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("ok", name)
            n += 1
    print("%d tests passed" % n)
