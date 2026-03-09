# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Running the System

```bash
# Start the robot (sets PYTHONPATH, activates venv, then runs robot.py)
bin/robot

# Or manually from the repo root:
source venv/bin/activate
python lbrsys/robexec/robot.py
```

Required environment variables must be set before starting:
- `ROBOT_CRED` - path to directory containing credentials files (required; used for `robauth.tokens`)
- `ROBOT_URL`, `ROBOT_CERT`, `ROBOT_KEY`, `ROBOT_CA` - for HTTPS and API access
- `ROBOT_USER`, `ROBOT_APITOKEN` - for authenticating the web client user
- `ROBOT_AWS_*` - for AWS IoT integration
- `ROBOT_DOCK` - lirc device for infrared docking signals

## Unit Testing

Each module's unit tests live under `if __name__ == '__main__':` at the bottom. Run them directly:

```bash
python lbrsys/robexec/robconfig.py
python lbrsys/robops/opsmgr.py
python lbrsys/robdrivers/sdc2130.py
# etc.
```

`robot.py` is the exception — it is always run as main.

## Installing Dependencies

```bash
pip install -r requirements.txt
```

Key packages: `pyquaternion`, `pyserial`, `smbus`, `pyttsx3`, `boto3`, `AWSIoTPythonSDK`, `awsiotsdk`, `pydub`, `PyRoboteq`, `numpy`, `matplotlib`.

## Architecture Overview

The system is a **multi-process robotics OS** where processes communicate via `multiprocessing.JoinableQueue` pairs. Process topology and inter-process channel wiring are defined in the SQLite3 database (`lbrsys/robot.sqlite3`) and loaded at startup by `Robconfig`.

### Package Structure

| Package | Purpose |
|---|---|
| `lbrsys/` | Top-level package; defines all message types and routing maps |
| `lbrsys/robexec/` | Executive: startup, console, config loading |
| `lbrsys/robops/` | Operations: main loop, motor control, sensors, observers |
| `lbrsys/robcom/` | Communications: HTTP service, pub/sub, speech, camera, auth |
| `lbrsys/robdrivers/` | Hardware drivers (user-space Python) |
| `lbrsys/robapps/` | Applications: FSM, navcam, AWS IoT, dance |

### Message Types and Routing

All inter-process messages are **named tuples** defined in `lbrsys/__init__.py` (e.g., `power`, `nav`, `speech`, `mpuData`, `executeTurn`). The `channelMap` dict in the same file maps channel types (`'Operations'`, `'Speech'`, `'Camera'`, etc.) to sets of named tuple types. When `robot.py` sends a command, it inspects the message type and routes it to matching channels.

### Key Files

- **`lbrsys/__init__.py`** — Defines all named tuple message types, `channelMap` (type→channel routing), and `command_map` (console command string→typed message parsing). Start here to understand the messaging contract.
- **`lbrsys/settings.py`** — Hardware port assignments, feature flags (`USE_SSL`, `LAUNCH_NAVCAM`, `SPEECH_SERVICE`), camera config, and all log file paths.
- **`lbrsys/robexec/robot.py`** — `Robot` class: reads config, creates `JoinableQueue` channels, spawns processes, runs the interactive command console, and routes messages.
- **`lbrsys/robexec/robconfig.py`** — `Robconfig`: reads `robot.sqlite3` to produce `processList`, `channelList`, `messageDict`, and `extcmds`.
- **`lbrsys/robops/opsmgr.py`** — `Opsmgr`: main 10ms operations loop, dispatches motor commands, gathers telemetry, coordinates observers.
- **`lbrsys/robcom/robhttpservice.py`** — Embedded threaded HTTP/HTTPS server on port 9145; REST API gateway between web clients and the robot's internal queue system.

### Configuration Database

`lbrsys/robot.sqlite3` is the source of truth for runtime wiring. Key tables:
- `robot` — robot identity and run timestamps
- `robot_process` — process definitions with their `target` (Python expression, `eval`'d at startup)
- `channel` — queue definitions linking source/target process IDs, direction (`Send`/`Receive`), and channel type
- `extcmd` — external subprocess commands (e.g., `navcam`, `autodock`, `docksignal`)
- `message` — multilingual message strings
- `move_config` — motor/wheel physical parameters

### HTTP Service

The embedded server at `lbrsys/robcom/robhttpservice.py` accepts JSON `POST` (commands) and `GET` (telemetry) requests. Commands received over HTTP are forwarded into the robot's internal queue system. Enable HTTPS by setting `USE_SSL = True` in `settings.py` and providing cert/key via environment variables.

### State Machine Application

`lbrsys/robapps/robfsm/robfsm.py` runs behavior programs defined as state transition tables. Tables live in `lbrsys/robapps/robfsm/statesd/` as `.csv` or `.json` files. The FSM communicates with the robot via the REST API, so it can run embedded or remotely.

### Code Style Note

Older modules use CamelCase (Python/Java hybrid era); newer modules use snake_case. Both styles coexist throughout the codebase.
