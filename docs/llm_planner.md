# LLM Planner Epic — Buggsy v2

Integrate the server orchestrator with a local Ollama LLM so the user can speak
to Buggsy and the robot responds with both speech and pre-canned motion (dances,
poses). Replaces the v1 static greeting flow.

## Goal

Wake → utterance capture → STT → LLM planner → structured skill calls (say,
play_move, …) dispatched by the orchestrator → robot acts.

The LLM is constrained to a **tool/function schema** (skills), not free-form
output, so the orchestrator can validate and dispatch reliably.

## Scope

In:

- Robot-side post-wake utterance capture.
- A server-side STT service (faster-whisper).
- A skill/tool framework in the orchestrator.
- An LLM planner that calls Ollama with the skill schema.
- Two v1 skills: `say(text)` and `play_move(name)`.
- A new MQTT command topic for moves.
- Eval harness for the planner (mock Ollama).

Out (deferred):

- Multi-turn conversation memory.
- Streaming token-by-token speech.
- Custom wake word for "Buggsy".
- Cloud LLM fallback (Claude).

## Architecture

```
 ┌─────────────────────────────────────────┐         ┌───────────────────────────────────┐
 │ robot (Pi CM4)                          │         │ server (Ubuntu + RTX 4060 Ti 16G) │
 │                                         │         │                                   │
 │  wake_detector ─► utterance_capturer ───┼─MQTT───►│  orchestrator                     │
 │       ▲                  │              │ utter.  │     │                             │
 │       │                  ▼ inline audio │         │     ▼                             │
 │  audio_bus           buggsy/events/     │         │   stt_client ──HTTP──► stt svc   │
 │                       utterance         │         │     │            (faster-whisper) │
 │                                         │         │     ▼                             │
 │  speak_listener ◄───────buggsy/cmd/─────┼─MQTT────│  planner ──HTTP──► ollama         │
 │       │                 speak           │  speak  │     │            (qwen2.5:14b)    │
 │       ▼                                 │         │     │ (tool/JSON)                 │
 │  audio_out                              │         │     ▼                             │
 │                                         │         │   skill dispatcher                │
 │  move_listener  ◄───────buggsy/cmd/─────┼─MQTT────│     ├─► say   ──► tts svc ──►speak │
 │       │                 move            │   move  │     └─► play_move ───────►move    │
 │       ▼                                 │         │                                   │
 │  daemon /api/move/play/<name>           │         │                                   │
 └─────────────────────────────────────────┘         └───────────────────────────────────┘
```

## Components

### 1. Robot: utterance capture

New stage in `robot/agent`. When the agent transitions to `WOKEN`:

- Start recording from `audio_bus` (already fans out PCM frames).
- End on Silero VAD silence (~0.8s of non-speech) OR a hard cap (~8s) OR a
  second wake event.
- Wrap in a small WAV header, base64-encode, publish on `buggsy/events/utterance`.
- For larger payloads (>~256KB) fall back to writing to a tmp location and
  sending a URL — defer until we measure typical sizes.

Keep CPU light: reuse the Silero VAD already loaded by openWakeWord
(`vad_threshold` config) rather than spinning up a second model.

### 2. Server: STT service

New container under `server/stt/` mirroring `server/tts/` shape.

- `faster-whisper` on GPU. Model: `large-v3` (default) configurable.
- HTTP: `POST /transcribe` with `{audio_b64, language?}` → `{text, segments?, language}`.
- Loaded once at startup, kept resident. VRAM budget: ~3GB for large-v3
  (fp16) — comfortable alongside qwen2.5:14b (~9GB) on the 16GB card.

### 3. Server: skill/tool framework

New module `server/src/server/orchestrator/skills/`.

```python
class Skill(Protocol):
    name: str
    description: str
    schema: dict  # JSON schema for params

    async def run(self, params: dict, ctx: SkillContext) -> SkillResult: ...
```

- `SkillRegistry` holds the v1 skills and produces the Ollama tool spec.
- `SkillContext` carries the MQTT client, http client, config, and the
  current "turn" id so a skill can publish on the right topics and log
  coherently.
- Dispatcher: validates the tool call against the schema, executes, captures
  result, logs. Invalid tool calls → retry once with the validation error
  appended to the prompt; second failure → fall back to a polite `say(...)`.

#### v1 skills

- **`say(text: str)`** — publishes the existing `SpeakCommand` flow (TTS →
  inline audio → `buggsy/cmd/speak`). This wraps today's behavior as a
  skill so the dispatcher is exercised on every interaction.
- **`play_move(name: str)`** — publishes `MoveCommand{name}` on
  `buggsy/cmd/move`. Name validated against the catalog (see §5).

Skills are sequenced (LLM can request multiple in one turn, e.g.
`say("Sure!"), play_move("dance_happy")`); the dispatcher awaits each in
order so audio + motion line up.

### 4. Server: LLM planner

New module `server/src/server/orchestrator/planner.py`.

- HTTP client to Ollama (`/api/chat` with `tools=[...]`).
- System prompt builder: identity ("you are Buggsy, an office assistant
  robot"), available skills (auto-injected from the registry), available
  moves (auto-injected from the catalog), constraints ("keep `say` text
  under 2 sentences", "only call `play_move` when the user explicitly asks
  to dance or you want to express emotion").
- Returns an ordered list of `ToolCall(name, params)`.
- Pluggable model (config: `llm.model`). Default `qwen2.5:14b-instruct`.

#### Dual-model seam (deferred but designed in)

The planner takes an optional `fast_model` config. When set, the orchestrator
issues two calls on each utterance:

- `fast_model` → a single quick `say(...)` ack ("Sure, one sec…") — dispatched
  immediately.
- `model` → the full plan — dispatched when ready.

We won't implement the second pass in this epic, but the planner interface
and the dispatcher will support "stream of tool calls arriving in waves."

### 5. Move catalog

The Reachy daemon's recorded-move API (confirmed from the OpenAPI spec):

- `GET /api/move/recorded-move-datasets/list/{dataset_name}` → array of
  move-name strings. **No metadata** (no duration, description, or tags).
- `POST /api/move/play/recorded-move-dataset/{dataset_name}/{move_name}` →
  `{uuid}`.
- There is **no endpoint to enumerate datasets themselves**. Datasets must
  be configured.

Known datasets at time of writing:

- `pollen-robotics/reachy-mini-dances-library`
- `pollen-robotics/reachy-mini-emotions-library`

(Note: today's `wake_up` / `goto_sleep` use `/api/move/play/<name>` — a
different, built-in-move path, not the recorded-move-dataset path. Keep
those as-is; the new skill targets recorded moves.)

#### Catalog strategy: discover names, curate descriptions

Because the API gives names but not descriptions, neither pure discovery
nor pure static config works well. The hybrid:

1. **Config lists which datasets to load** (`moves.datasets: [...]`).
2. **Config holds a `descriptions` map** keyed by `{dataset}/{move}` →
   one-line description used in the LLM prompt.
3. **At orchestrator startup**, fetch each dataset's move list from the
   daemon, then build the LLM-facing catalog as the **intersection**:
   moves that exist on the robot *and* have a curated description.
4. **Log mismatches**: moves on the robot without descriptions (so we can
   fill them in), and descriptions in config with no matching move
   (stale entries to prune).
5. **Cache to disk** on each successful fetch (per dataset). Boot
   behavior:

   | Daemon       | Cache    | Result                                            |
   |--------------|----------|---------------------------------------------------|
   | reachable    | any      | fetch, replace cache, full capability             |
   | unreachable  | present  | load cache, full capability (logged as stale-OK)  |
   | unreachable  | absent   | `say`-only mode, retry daemon in background       |

   Cache path: `moves.cache_path` (default `~/.cache/buggsy/move_catalog.json`),
   keyed by dataset so a partial fetch failure doesn't clobber good
   entries. No expiry timer — refresh only on successful daemon contact
   at startup. (A `python -m server.tools.refresh_move_catalog` helper
   lets any machine with daemon access pre-warm the cache.)

This keeps the LLM's catalog accurate without us having to mirror every
move name in config — only the ones we've written descriptions for are
selectable, which is also a nice safety property.

```yaml
moves:
  datasets:
    - pollen-robotics/reachy-mini-dances-library
    - pollen-robotics/reachy-mini-emotions-library
  descriptions:
    "pollen-robotics/reachy-mini-dances-library/dance_happy":
      "Happy bouncy dance — full body, ~6s."
    "pollen-robotics/reachy-mini-emotions-library/curious":
      "Curious head tilt with antennae forward."
    # ... fill in as we audit each dataset
```

Spelunking the actual move names in each dataset (so we can write the
descriptions) is a small task in its own right — call it out as part of
the move-catalog child issue.

### 6. Protocol additions

In `shared/protocol/mqtt_topics.py`:

```python
TOPIC_UTTERANCE = "buggsy/events/utterance"
TOPIC_MOVE      = "buggsy/cmd/move"

class UtteranceEvent(BaseModel):
    ts: float
    audio_b64: str | None = None
    audio_url: str | None = None
    sample_rate: int = 16000

class MoveCommand(BaseModel):
    dataset: str     # e.g. "pollen-robotics/reachy-mini-dances-library"
    name: str        # move name within the dataset; must be in catalog
    turn_id: str | None = None
```

### 7. Robot: move listener

Symmetric to the existing `speak_listener` in `robot/agent/agent.py`.
Subscribes to `buggsy/cmd/move`, POSTs to:

```
POST /api/move/play/recorded-move-dataset/{dataset}/{name}
```

Daemon HTTP is the right transport here — recorded-move playback is
explicitly an HTTP API, the daemon owns the dataset cache, and it
matches the pattern we already use for `wake_up`/`goto_sleep`. The
held-open `ReachyMini` SDK object stays dedicated to fine-grained
`goto_target()` poses.

Returned `uuid` is logged but not currently used. Future: subscribe to a
daemon "move finished" event (if one exists) to publish a `MoveDoneEvent`
analogous to `SpokeDoneEvent`.

### 8. Config additions

```yaml
moves:
  datasets:
    - pollen-robotics/reachy-mini-dances-library
    - pollen-robotics/reachy-mini-emotions-library
  cache_path: ~/.cache/buggsy/move_catalog.json
  descriptions: {}              # see §5 — fill in per-move

llm:
  base_url: http://localhost:11434
  model: qwen2.5:14b-instruct
  fast_model: null              # e.g. llama3.1:8b — enables dual-pass
  temperature: 0.6
  request_timeout_s: 30

stt:
  url: http://localhost:8002
  model: large-v3
  language: en

utterance:
  max_seconds: 8.0
  silence_seconds: 0.8

moves:
```

Drop `greeting:` once the planner replaces `StaticGreetingSource`. Keep the
section in `buggsy.yaml` for one release with a deprecation comment so
existing deploys don't break.

## VRAM budget (RTX 4060 Ti 16GB)

| Component                         | VRAM     |
|-----------------------------------|----------|
| qwen2.5:14b-instruct (q4_K_M)     | ~9 GB    |
| faster-whisper large-v3 (fp16)    | ~3 GB    |
| llama3.1:8b (q4_K_M, optional)    | ~5 GB    |
| Headroom / KV cache               | balance  |

Comfortable with the 14B + Whisper coresident. Adding llama3.1:8b as the
fast model later would put us at ~17GB → would need Whisper-medium (~1.5GB)
or model unload-on-idle. Decide when we get there.

## Eval harness

`server/tests/planner/`:

- Fixture utterances → expected tool calls (golden file).
- Mock Ollama returning canned tool-call JSON to exercise the dispatcher.
- A "live" suite gated by `BUGGSY_LIVE_LLM=1` that hits the real Ollama and
  asserts on tool-call *shape* (not exact text) — runs nightly, not in PRs.

Goal: refactors to the planner / skills don't regress dispatch, and we can
add new skills with confidence.

## Phased rollout (proposed child issues)

1. **Skill framework + skill-ified `say`** — refactor today's static-greeting
   flow into a `SkillRegistry` + `say` skill, dispatched by a stub planner
   that always returns `say(static_phrase)`. No LLM yet. Pure refactor with
   tests — proves the seams.
2. **Move command protocol + robot listener** — add `TOPIC_MOVE`,
   `MoveCommand`, `play_move` skill, robot subscriber that posts to the
   daemon. Test with a hand-published MQTT message; no LLM yet.
3. **Move catalog loader** — fetch move names from configured datasets via
   the daemon's `recorded-move-datasets/list` endpoint, intersect with the
   curated `moves.descriptions` map, cache to disk (see §5), expose the
   resulting catalog to the planner and to `play_move` for validation.
   Includes a `refresh_move_catalog` helper script and a first-pass
   description seed for the two known datasets.
4. **STT service container** — `server/stt/` with faster-whisper, HTTP
   endpoint, compose entry.
5. **Robot utterance capture** — post-wake recorder, VAD-gated end,
   `buggsy/events/utterance` publish.
6. **LlmPlanner** — Ollama tool-calling client, system prompt builder,
   replace the stub planner. `llm.*` config. Eval fixtures + mock-Ollama
   tests.
7. **End-to-end demo + tuning** — measure latency, tune VAD/silence
   thresholds, prompt iteration. Update docs.

Each is a shippable PR. Order matters: 1 and 2 unblock everything; 4 and 5
can be parallel; 6 needs 1-5.

## Open questions

- Move catalog source: confirm whether the Reachy daemon can enumerate
  available moves (would change §5).
- Where does utterance audio live during transit — inline base64 on MQTT
  (simple) vs. a server-side staging endpoint the robot POSTs to (cleaner
  for >256KB payloads)? Measure with a real 8s clip before deciding.
- TTS latency vs. fast-model ack — at what total latency does the dual-pass
  become worth the extra Ollama load? Likely a question we answer after the
  end-to-end demo.
- Error UX: when STT returns empty / LLM times out / no valid tool calls —
  generic `say("Sorry, didn't catch that.")` vs. a richer set of fallbacks?
