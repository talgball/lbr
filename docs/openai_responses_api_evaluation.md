# OpenAI Responses API Evaluation for lbr AI Service

**Date:** 2026-03-14
**Current implementation:** Chat Completions API with function calling (`robaiservice.py`)
**Current model:** gpt-5.2 (configurable via `ROBOT_OPENAI_MODEL`)

## Summary

The Responses API is OpenAI's recommended successor to Chat Completions, launched
March 2025. It supports all the same capabilities we use today (custom function
calling, multimodal input) plus server-side conversation state, better caching,
and a cleaner tool-calling interface. Chat Completions is NOT deprecated and
remains fully supported, so there is no urgency.

**Recommendation:** Upgrade. The multi-turn conversation state and improved
caching are directly valuable for the robot's AI service, and the migration is
straightforward.

## What We Gain

### 1. Server-side conversation state (`previous_response_id`)

Currently `_call_openai()` manually manages `self.conversation` — a list of
message dicts that we slice (last 10 entries), sanitize (strip tool-only
prefixes), and re-send with every request. This is fragile and wastes tokens
re-transmitting history.

With the Responses API, we pass `previous_response_id=<last_response_id>` and
OpenAI maintains the full conversation chain server-side. We'd replace
`self.conversation` with a single `self.last_response_id` string.

Benefits:
- Eliminates our conversation history slicing/sanitization code
- Reasoning model traces persist across turns (not exposed to us, but used by
  the model internally — improves multi-step task performance)
- 40-80% improved cache hit rates → lower cost for multi-turn interactions
- Previous input tokens are still billed but at discounted cached-token rates

For longer-lived sessions there is also a Conversations API where a conversation
object is not subject to the 30-day stored response TTL. This could be useful
if we want persistent robot "memory" across sessions.

### 2. Cleaner tool definition format

Current (Chat Completions):
```python
{
    "type": "function",
    "function": {
        "name": "move",
        "description": "Move the robot...",
        "parameters": {...}
    }
}
```

Responses API:
```python
{
    "type": "function",
    "name": "move",
    "description": "Move the robot...",
    "parameters": {...},
    "strict": True
}
```

The nested `"function": {}` wrapper is removed. `strict: True` is available
(and the default), which guarantees the model's function call arguments conform
exactly to our JSON schema — useful for safety-critical robot commands.

### 3. Native agentic loop support

The Responses API is designed for multi-step tool use. The model can issue
multiple tool calls in a single response, and the SDK supports a natural loop
pattern:

```python
input_list += response.output  # carry forward all items including reasoning
for item in response.output:
    if item.type == "function_call":
        result = execute_function(item.name, json.loads(item.arguments))
        input_list.append({
            "type": "function_call_output",
            "call_id": item.call_id,
            "output": json.dumps(result),
        })
# Send results back for another round of reasoning
response = client.responses.create(model=..., input=input_list, tools=...)
```

This enables the model to reason about tool results and issue follow-up commands
in a loop — e.g., "move forward, check range sensors, if obstacle detected then
turn and try again." Currently our service executes tool calls but doesn't feed
results back to the model for follow-up reasoning.

### 4. Built-in tools (future)

The Responses API has built-in tools (web search, code interpreter, file search,
computer use, remote MCP) that we could potentially use to extend the robot's
capabilities without writing custom tool handlers. Not immediately needed but
opens doors.

## Migration Scope

The migration is localized to `robaiservice.py`. No changes needed to the
queue infrastructure, message types, or `execute_tool_call()`.

### Changes required:

| Area | Current (Chat Completions) | New (Responses API) |
|------|---------------------------|-------------------|
| API call | `client.chat.completions.create()` | `client.responses.create()` |
| System prompt | `{"role": "system", ...}` in messages | `instructions=` param |
| User input | `messages=[...]` | `input=[...]` or `input="..."` |
| Response text | `response.choices[0].message.content` | `response.output_text` |
| Tool calls | `response.choices[0].message.tool_calls` | `[item for item in response.output if item.type == "function_call"]` |
| Tool results | `{"role": "tool", "tool_call_id": id}` | `{"type": "function_call_output", "call_id": call_id}` |
| Conversation | `self.conversation` list + slicing | `self.last_response_id` string |
| Tool defs | Nested `"function": {}` wrapper | Flat, top-level properties |

### Key implementation notes:

- **SDK version:** Requires `openai >= 1.68`. Check with `pip show openai`.
- **`store=True`** (default) enables caching benefits. Use for our case.
- **Reasoning items:** When the model returns reasoning items alongside
  function_call items, they must be passed back in the input. The pattern
  `input_list += response.output` handles this automatically.
- **`previous_response_id` vs manual input:** Can use either. For our use case,
  `previous_response_id` is simpler since we want continuous conversation.
  Manual input assembly is needed when we want to inject telemetry updates
  between turns (which we do — state snapshot in system prompt). We may want
  a hybrid: use `previous_response_id` for conversation continuity but always
  pass fresh `instructions=` with current state.
- **Camera snapshots:** Multimodal input works the same way — include image
  content in the input items.

### What stays the same:

- `execute_tool_call()` — unchanged, it just translates tool names/args to
  command strings
- `ROBOT_TOOLS` definitions — content stays the same, just reformatted
- Queue infrastructure, message routing, telemetry accumulation
- Whisper transcription (`client.audio.transcriptions.create()` — separate API)

## Multi-turn Conversation Design

With `previous_response_id`, we can support genuine multi-turn conversations
where the robot maintains context across multiple voice commands:

1. User: "Hey Jarvis, go to the kitchen"
2. Robot navigates, reports arrival
3. User: "What do you see?" (model has context from turn 1)
4. Robot describes camera view, still aware it was asked to go to kitchen

The key design question is how to inject fresh telemetry state between turns.

**Chosen approach: Option C (Hybrid)**

Use Option A (fresh `instructions=` with current state + `previous_response_id`)
for routine user-initiated turns. Use Option B (telemetry injected as input
items) for state updates between tool-call steps during multi-step task
execution. This gives us the simplicity of A for normal interactions and the
real-time telemetry awareness of B when the model is actively navigating.

## Sense-Act Loop for Complex Tasks

The biggest capability unlock is the ability to feed tool results back to the
model for multi-step reasoning. The model operates in a **sense-act-sense-act
loop** where it decomposes complex tasks into steps small enough that telemetry
latency during the "blind window" (while the model is waiting for an API
response) won't cause problems.

### Example flow:

```
User: "Navigate to the front door and tell me if anyone is there"

Turn 1: Model sees current state
        → calls navigate(level=0.25, angle=0, range=200, sensor="Forward", duration=5)
        [robot executes for up to 5s or 200cm, then stops]
        [telemetry accumulates: ranges, heading, position]

Turn 2: We inject updated state (ranges, heading, position)
        → Model sees "moved 180cm, forward range now 95cm, heading 342°"
        → calls turn(angle=45)
        [robot executes turn, stops]

Turn 3: Updated state after turn
        → Model sees new heading, new ranges, clear path ahead
        → calls navigate(level=0.25, angle=0, range=300, sensor="Forward", duration=5)

...continues until model determines task is complete...

Turn N: Model sees it has arrived at estimated location
        → calls speak("I've arrived. Let me look around.")
        [camera snapshot attached on next turn]

Turn N+1: Model analyzes camera image
        → calls speak("I can see the front door. No one appears to be there.")
        → no further tool calls → loop exits
```

### Safety constraint (in system prompt):

The model must **always use bounded movements** — every `navigate()` call must
include a range and/or duration limit. This ensures the robot stops and waits
for the next decision rather than driving indefinitely during the blind window.

Default power level is **25%** (0.25) unless the operator specifies otherwise
or the model determines a lower level is warranted based on environmental
concerns (e.g., tight spaces, nearby obstacles, low visibility).

### Detecting movement completion:

The most reliable indicator that the robot has stopped moving is **zero current
on both motors**. Motor current is reported directly from the RoboteQ SDC2130
motor controller and is highly reliable. The gear ratio makes the wheels very
stiff externally — they will not move except when driven by the motors. This
avoids sensor jitter or drift issues: range sensor readings can change when
the robot is stationary (e.g., something moved nearby), but motor current is
unambiguous.

For now, we detect this from the standard telemetry stream rather than
subscribing directly to opsmgr or motion processing events. Direct event
subscription is available in the architecture but near-real-time operations
are not suitable for direct LLM management — the sense-act loop should operate
at a pace where telemetry polling is sufficient.

### Telemetry update triggers:

Three categories with different triggering mechanisms:

1. **After tool-call completion** (navigate finishes, turn completes): Watch
   the telemetry stream for zero current on both motors, then inject current
   state and send the next turn to the model. This is the primary trigger for
   the sense-act loop.

2. **During long-running commands** (if longer durations are used): A periodic
   timer (every 2-3 seconds) injects intermediate state so the model can issue
   `stop()` if something looks concerning.

3. **Significant events** (obstacle proximity alert, battery critical, bump
   sensor): Inject immediately regardless of what the model is doing. These
   are interrupt-level and should cause the model to reassess.

### Implementation in `_call_openai()`:

The worker thread enters a loop after the initial API call. After executing
tool calls, it waits for execution to complete (signaled via a
`threading.Event` that the main loop sets when it sees the relevant telemetry
transition — specifically zero motor current on both channels), then injects
updated state as input items and sends the next turn. The loop exits when:

- The model returns text with no tool calls (task complete)
- A max iteration limit is reached (safety bound)
- An interrupt-level event occurs that requires operator attention

### Request classification:

1. **Single-step requests** (speak, report, simple questions): One API call,
   no loop needed. The model responds with text or a single tool call.

2. **Multi-step tasks** (navigation, complex commands): The model issues tool
   calls with bounded parameters, we execute and feed back results. Loop
   continues until completion.

The model itself decides which category a request falls into based on the
task complexity and its assessment of the environment.

## Conversation State Management

Conversation state persists within a session using `previous_response_id`.
The `self.conversation` list is replaced by a single `self.last_response_id`.

**Reset policy:**
- Persist across turns within a session (the model remembers prior tasks
  and interactions)
- Reset on explicit command (`/ai/reset`)
- Reset on session end (service shutdown/restart)
- Future: more comprehensive memory management (out of scope for initial
  migration)

## Risks and Concerns

- **Server-side state dependency:** If OpenAI's stored responses expire (30-day
  TTL) or have an outage, conversation context is lost. Mitigation: the
  Conversations API has no TTL, or we can fall back to manual history.
- **Telemetry latency in sense-act loop:** Each round-trip (tool execution +
  API call) introduces a blind window. Mitigation: bounded movements (range/
  duration limits), conservative default speed (25% power), periodic telemetry
  injection during long commands, interrupt-level events for critical
  situations.
- **Cost:** Multi-step loops multiply API calls. Cached token pricing helps
  but complex tasks could get expensive. Mitigation: set a max iterations
  limit on the agentic loop.
- **Testing:** The Responses API is newer. Less community battle-testing than
  Chat Completions. Mitigation: we can keep the Chat Completions code path
  available behind a setting during transition.

## Robot-Specific AI Notes (config database)

Add a new table to `robot.sqlite3` for per-robot notes that are included in the
AI system prompt. This gives the model hardware-specific knowledge it needs to
interpret telemetry correctly. The pattern follows `get_move_config()` in
`lbrsys/__init__.py`, which already loads per-robot physical parameters from the
`move_config` table at startup.

Example notes for lbr6a:

- The Maxbotix MB1220 range sensors have a maximum range of 758cm. A reading of
  758 is reported both when the actual distance exceeds sensor range AND on
  sensor error — in either case, that reading is unreliable and should not be
  trusted as an actual distance measurement.
- (Other robot-specific quirks, limitations, or calibration notes as discovered.)

### Table design (preliminary):

```sql
CREATE TABLE ai_notes (
    note_id INTEGER PRIMARY KEY,
    robot_id INTEGER REFERENCES robot(robot_id),
    category TEXT,       -- e.g., 'sensor', 'motor', 'navigation', 'general'
    note TEXT,
    active INTEGER DEFAULT 1
);
```

Loaded at AI service startup via a `get_ai_notes(robot_id)` function, formatted
into the system prompt alongside the state snapshot.

## Move Configuration in AI Context

The `move_config` table (already in the database) contains physical parameters
the AI needs to interpret encoder telemetry:

- `wheel_diameter` (cm) — lbr6a default: 17.78
- `counts_per_rev` — lbr6a default: 130
- `m1_direction`, `m2_direction` — motor polarity

With wheel diameter and counts per revolution, the model can calculate distance
traveled from encoder counts:

```
distance = (counts / counts_per_rev) * pi * wheel_diameter
```

This data should be included in the system prompt or made available as a tool
so the model can reason about how far it has actually moved during navigation.

## Implementation Plan (when ready)

1. Verify `openai` SDK version (currently 2.26, requirement is >= 1.68)
2. Reformat `ROBOT_TOOLS` to flat Responses API format
3. Update system prompt: add bounded-movement safety constraint, 25% default
   power level guidance, move_config data, robot-specific AI notes
4. Create `ai_notes` table in `robot.sqlite3` and `get_ai_notes()` loader
   (following `get_move_config()` pattern in `lbrsys/__init__.py`)
5. Include `move_config` (wheel diameter, counts per rev) in system prompt
   so the model can calculate distance from encoder counts
6. Refactor `_call_openai()` to use `client.responses.create()` with
   `previous_response_id` and `instructions=`
7. Add sense-act loop: execute tools, wait for zero motor current on both
   channels (movement complete), inject telemetry, send next turn
8. Add `threading.Event` signaling between main loop (telemetry) and worker
   thread (API calls), triggered on zero motor current
9. Store `self.last_response_id` instead of `self.conversation`
10. Add conversation reset command (`/ai/reset`) and reset on session end
11. Test with existing voice command pipeline (wake word → Whisper → AI)
12. Test multi-step navigation tasks with telemetry feedback
