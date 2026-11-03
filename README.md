# voice-input — Mac の中だけで動く音声入力

右 Option を押している間だけ録音し、離すと書き起こしてカーソル位置に貼り付ける、メニューバー常駐の音声入力です。
書き起こしも整形（フィラー除去・句読点）も Apple Silicon の MLX でこの Mac の中で行い、音声もテキストも外に出ません。

Push-to-talk dictation for Apple Silicon Macs. Whisper (MLX) transcribes, a small local LLM removes fillers, and the text is pasted at the cursor. Nothing leaves your Mac.

## できること

- **押している間だけ録音**。右 Option（`VOICE_INPUT_HOTKEY` で右 Command / Control / Shift にも変えられる）を押しながら話して離すと、テキスト欄に貼り付く
- **オフラインで動く**。初回にモデルを取得したあとは、起動時もネットへ出ない（`HF_HUB_OFFLINE=1`）
- **話し言葉を整える**。「えー」「あのー」と言い直しを、ローカル LLM が取り除いて句読点を付ける。整形結果が元の書き起こしから離れすぎたとき（質問に答えてしまった等）は、書き起こしをそのまま貼る
- **無音から文章をでっち上げない**。無音と 0.4 秒未満の録音は捨てる（Whisper は無音から文章を作ることがあるため）
- **貼り付け後にクリップボードを戻す**。クリップボード経由で貼るが、元のテキストは戻す
- **話した内容の履歴を手元に残す（既定で入）**。貼り付けに失敗したときの救出用。残したくなければ `VOICE_INPUT_HISTORY=0` かメニューで切る

## 必要なもの

- Apple Silicon の Mac（M1 以降）。MLX は Intel Mac では動きません
- [uv](https://docs.astral.sh/uv/)（`install.sh` が無ければ入れる）。依存は `voice_input.py` 冒頭のインラインメタデータにあり、uv が自動で用意する
- Xcode Command Line Tools（`cc` と `codesign`。小さなランチャーアプリを作るため）
- ディスク約 3.5GB（Whisper large-v3-turbo と Qwen2.5-3B 4bit）

## 入れ方

```bash
git clone https://github.com/masakiplus/voice-input.git
cd voice-input
bash install.sh
```

`install.sh` は次を順に行います。

1. uv が無ければ入れる
2. モデルを取得する（初回だけネットへ出る）
3. `~/Applications/VoiceInput.app` を作る
4. ログイン時に自動で開くよう launchd に登録する
5. 起動する

そのあと **システム設定 → プライバシーとセキュリティ** で VoiceInput に次を許可します。

- マイク（初回起動時にダイアログが出る）
- アクセシビリティ（初回起動時に案内が出る。貼り付けとキーの検知に使う）
- 入力監視（キーを押してもメニューバーが 🔴 にならないときに足す）
- フォルダへのアクセス（このフォルダを `~/Documents` や `~/Desktop` の下に置いた場合、初回にダイアログが出る）

メニューバーが ⏳ → 🎙 になったら使えます。

## 使い方

テキスト欄にカーソルを置き、右 Option を押しながら話して離します。

| 表示 | 状態 |
|---|---|
| ⏳ | モデルを読み込み中（起動から十数秒） |
| 🎙 | 待機中 |
| 🔴 | 録音中 |
| ✍️ | 書き起こし中 |
| ⚠️ | 許可が足りない、または失敗。メニューの1行目に理由が出る |

メニューの「整形する」でローカル LLM による整形を、「履歴を残す」で話した内容の履歴を入り切りできます。どちらも再起動すると `config.env` の設定（既定は入）に戻ります。

止めるときはメニューバーのアイコン → 終了。もう一度動かすときは `open -a VoiceInput`。

マイクを使わずに動作を確かめるとき:

```bash
uv run voice_input.py --file sample.wav            # 書き起こしと整形の結果を表示して終わる
uv run voice_input.py --file sample.wav --no-polish
```

## 設定

`cp config.env.example config.env` して書き換えます。`run.sh` が起動のたびに読みます（.app 経由の起動では環境変数を渡せないため）。

| 変数 | 既定 | 意味 |
|---|---|---|
| `VOICE_INPUT_HOTKEY` | `alt_r` | 押している間だけ録音するキー。`alt_r`（右 Option）/ `cmd_r` / `ctrl_r` / `shift_r` |
| `VOICE_INPUT_POLISH` | `1` | `0` で整形をしない |
| `VOICE_INPUT_HISTORY` | `1` | `0` で話した内容の履歴を残さない |
| `VOICE_INPUT_LOG_DIR` | このフォルダの `logs/` | ログの置き場（`stderr.log` も含む） |
| `VOICE_INPUT_BUNDLE_ID` | `local.voiceinput` | アプリの識別子と launchd のラベル。`build_app.sh` と `install.sh` を走らせるときに環境変数で渡す |

手で起動するときは同じことを引数でも渡せます: `uv run voice_input.py --hotkey cmd_r --no-polish --no-history`（`--help` で一覧）。

モデルやしきい値（最短の録音秒数・無音とみなす音量・整形結果をどこまで許すか）は `voice_input.py` 冒頭の定数で変えます。モデルを差し替えるときは `HF_HUB_OFFLINE=0 uv run voice_input.py --fetch-models` で取得してから再起動します。

## ログ

| ファイル | 中身 |
|---|---|
| `logs/voice_input.log` | 動作の記録。起動・録音の長さ・処理時間・文字数・失敗。話した内容は書かない |
| `logs/history.jsonl` | 話した内容の履歴。1発話1行で、書き起こし（`raw`）と実際に貼り付けた文（`pasted`） |
| `logs/stderr.log` | 起動時のエラーなど。起動のたびに上書きする |

上の2つは 1MB を超えると `.1` 〜 `.3` へ世代交代し、それより古いものは消えます。

履歴は貼り付けに失敗したときの救出と、整形がおかしかったときの原因調べに使います。`raw` が既におかしければ書き起こし、`pasted` だけおかしければ整形が原因です。パスワードなど残したくないものを話すときは、メニューの「履歴を残す」を切ってください。

## 仕組み

- 書き起こし: [`mlx-community/whisper-large-v3-turbo`](https://huggingface.co/mlx-community/whisper-large-v3-turbo)
- 整形: [`mlx-community/Qwen2.5-3B-Instruct-4bit`](https://huggingface.co/mlx-community/Qwen2.5-3B-Instruct-4bit)。フィラー除去と句読点だけを任せ、few-shot の例を2つ渡す
- 貼り付け: クリップボードに入れて Cmd+V を送り、元のクリップボード（テキスト）を戻す
- マイクはキーを押している間だけ開く。常時開くと、マイク使用中の表示が出たままになるため
- MLX の処理は worker スレッド1本に集め、キー入力とメニューバーは別スレッドで動かす

### VoiceInput.app を挟む理由

マイク・アクセシビリティ・入力監視の許可は、macOS がアプリ単位で持ちます。launchd から bash や python を直接起動すると、許可の対象が bash や python そのものになり、マイクの許可ダイアログも出ません。

そこで `app/launcher.c` を本体にした小さなアプリを作り、許可をそのアプリに持たせています。アプリは `run.sh` を子プロセスとして起動して待つだけなので、Python 側を直しても許可は残ります。アプリを作り直すと署名が変わるので、そのときは許可を付け直します。フォルダを動かしたら `bash build_app.sh` をもう一度走らせてください（アプリに `run.sh` の場所を埋め込んでいるため）。

## 制約

- 整形は 3B の小さなモデルなので、文頭の「えーと」が残ることがある
- キーを押してからマイクが開くまで一瞬かかる。押してすぐ話すと頭の音が欠けることがある
- 異常終了しても自動では立ち上がり直さない。メニューバーからアイコンが消えていたら `open -a VoiceInput`
- クリップボードの復元はテキストだけ。画像などをコピーしていた場合は失われる
- 日本語向けに調整している（`--language` で他の言語も書き起こせるが、整形のプロンプトは日本語）

## アンインストール

```bash
ID="${VOICE_INPUT_BUNDLE_ID:-local.voiceinput}"
launchctl bootout "gui/$(id -u)/$ID"
rm ~/Library/LaunchAgents/"$ID".plist
rm -rf ~/Applications/VoiceInput.app
tccutil reset All "$ID"          # マイク・アクセシビリティなどの許可を外す
rm -rf ~/.cache/huggingface/hub/models--mlx-community--whisper-large-v3-turbo \
       ~/.cache/huggingface/hub/models--mlx-community--Qwen2.5-3B-Instruct-4bit
```

最後に clone したフォルダ（`logs/` と `config.env` を含む）を消します。

## ライセンス

MIT
