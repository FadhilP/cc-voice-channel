# cc-voice-channel

Talk to a running Claude Code session from anywhere in Windows. Press a global hotkey, speak, and the transcript arrives in the session as a prompt. Claude can answer aloud through a `speak` tool.

Speech-to-text and text-to-speech run locally:

- STT: [Kyutai STT 2.6B](https://huggingface.co/kyutai/stt-2.6b-en) (English) on an NVIDIA GPU.
- TTS: [Kyutai Pocket TTS](https://github.com/kyutai-labs/pocket-tts) on the CPU.

It is built as a [Claude Code channel](https://code.claude.com/docs/en/channels-reference), so it runs inside the normal Claude Code CLI with your usual login.

## How it works

- `daemon.py` runs all the time. It listens for the hotkey, records the mic, transcribes the audio, and plays speech.
- `channel.ts` is an MCP server that Claude Code starts. It pushes transcripts into the session and gives Claude the `speak` tool.

The two processes talk over `127.0.0.1` on ports 8788 (daemon to channel) and 8789 (channel to daemon). Both share a random token in `~/.cc-voice-channel/token`. They reject requests that do not carry the token or that have an `Origin` header, so websites in your browser cannot call them.

## Requirements

- Windows. The daemon uses `winsound` and the `keyboard` package.
- An NVIDIA GPU with about 6 GB of free VRAM. `requirements.txt` installs PyTorch for CUDA 12.8.
- Python 3.10 or later.
- Node.js 22.18 or later. It runs `channel.ts` directly with Node's TypeScript support.
- Claude Code with channels support. Channels are in research preview. On Team and Enterprise plans, an admin must [enable them](https://code.claude.com/docs/en/channels#enterprise-controls).

Tested with Python 3.10, Node 24, Claude Code 2.1.306, and an RTX 5070.

## Setup

1. Install the dependencies:

   ```powershell
   git clone <this-repo-url> cc-voice-channel
   cd cc-voice-channel
   npm install
   python -m venv .venv
   .venv\Scripts\pip install -r requirements.txt
   ```

2. Make a folder for voice sessions, for example `C:\Users\<you>\voice-hub`. Create `.mcp.json` in it, with the absolute path to `channel.ts`:

   ```json
   {
     "mcpServers": {
       "voice": {
         "command": "node",
         "args": ["C:\\path\\to\\cc-voice-channel\\channel.ts"]
       }
     }
   }
   ```

   Do not register the server at user scope (`claude mcp add --scope user`). Then every Claude Code session would load it: each session would get the `speak` tool, and each would try to bind port 8788.

3. Optional: add a `CLAUDE.md` to the same folder to make the session work as an orchestrator. Claude then hands long tasks to background subagents and stays free for your next request. Example:

   ```markdown
   # Voice orchestrator

   I talk to you by voice and usually do not watch the screen. In this folder you are an orchestrator, not a worker.

   - Delegate every task that needs more than a quick answer to a background subagent. I am asking you to do this for all such tasks in this folder.
   - Do not do the work in the main session. Stay free for my next voice request.
   - Give each subagent a full brief: goal, paths, constraints, and what to report back.
   - My messages come from speech-to-text. If a message is not coherent, or you cannot tell what I want, do not guess. Ask me to clarify with the speak tool.
   - Answer quick questions yourself.
   - When a subagent reports back, give me a short summary with the speak tool.
   ```

## Run

1. Start the daemon from the repo folder. The first run downloads the models (about 6 GB). Loading takes about 30 seconds.

   ```powershell
   .venv\Scripts\python daemon.py
   ```

   Wait for `Ready`.

2. In a second terminal, start Claude Code from your voice-session folder. Custom channels need the development flag while channels are in research preview.

   ```powershell
   cd C:\Users\<you>\voice-hub
   claude --dangerously-load-development-channels server:voice
   ```

   On the first start, approve the `voice` MCP server, then confirm the development channel warning.

3. Press `Ctrl+Alt+Space`, speak, and press it again.
   - A high beep means recording started.
   - A low beep means recording stopped.
   - A long low beep means Claude Code was not reachable.

Claude speaks when it finishes a task, when a subagent reports back, or when it needs a decision. Short replies to small talk stay in the terminal as text.

## Configuration

Edit the constants at the top of `daemon.py`, then restart the daemon.

| Constant | Default | Meaning |
| - | - | - |
| `HOTKEY` | `ctrl+alt+space` | Starts and stops recording. Uses the [`keyboard`](https://github.com/boppreh/keyboard) hotkey format. |
| `TTS_VOICE` | `mary` | Pocket TTS voice. See below. |
| `SPEECH_RMS` | `0.01` | Loudness level that counts as speech. Depends on your mic. |
| `MIN_SPEECH_SECONDS` | `0.3` | Recordings with less speech than this are skipped. This stops the model from inventing words from silence. |

### Voices

Built-in English voices: `alba`, `marius`, `javert`, `jean`, `cosette`, `anna`, `vera`, `fantine`, `charles`, `paul`, `eponine`, `azelma`, `george`, `mary`, `jane`, `michael`, `eve`, `bill_boerst`, `peter_yearsley`, `stuart_bell`, `caro_davy`.

To hear a voice before you choose it:

```powershell
.venv\Scripts\python -X utf8 -m pocket_tts generate --voice marius --text "Hello, this is a test." --output-path marius.wav
```

`-X utf8` is necessary on Windows. Without it, pocket-tts reads its config file with the wrong encoding and fails. `daemon.py` has its own workaround for this.

To clone a voice from a WAV file, set `TTS_VOICE` to the file path. This needs the voice-cloning weights, which are gated. Accept the terms on the [`kyutai/pocket-tts`](https://huggingface.co/kyutai/pocket-tts) model page and run `hf auth login`.

## Tests

```powershell
npm test
.venv\Scripts\python test_daemon.py
```

## Troubleshooting

- **Real speech is skipped with `No speech detected`:** lower `SPEECH_RMS`, for example to `0.005`.
- **Silence still produces text:** raise `SPEECH_RMS`, for example to `0.02`.
- **CUDA errors:** check that your GPU has about 6 GB of free VRAM, and that your NVIDIA driver supports CUDA 12.8.
- **The channel does not register:** run `/mcp` in the session and check that `voice` is connected. If it is, restart Claude Code with the environment variable `MCP_PROTOCOL_NEGOTIATION=legacy`.
- **The hotkey does nothing in some windows:** the `keyboard` package cannot see key presses while an elevated (administrator) window has focus. Run the daemon as administrator too.

## Limits

- Windows only.
- English speech only.
- Run one voice session at a time. A second session cannot bind port 8788.
- Transcription starts after you stop recording. Expect a delay of a few seconds.
- Messages that arrive while Claude is busy wait in a queue. Claude handles them together on its next turn.
- Keep `@modelcontextprotocol/sdk` on 1.x. With the 2.x protocol revision, Claude Code does not deliver channel messages.
