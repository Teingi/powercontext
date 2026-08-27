---
title: Configure Hermes
description: Install the Hermes MemoryProvider and connect it to a running PowerContext Server.
---

# Configure Hermes

The integration is a standard Hermes `MemoryProvider`. Hermes remains responsible for the conversation and memory
lifecycle; the provider sends recall, capture, and explicit Memory operations to a separately running PowerContext
Server. Backend failures do not interrupt the Hermes conversation.

## Prerequisites

- Hermes Agent 0.20.4 or newer, available on `PATH`;
- PowerContext CLI and Server installed from `master`;
- a running PowerContext Server.

```bash
uv tool install --force "powercontext[cli,server] @ git+https://github.com/oceanbase/powercontext.git@master"
powercontext server run
```

## Install the provider

In another terminal, install or refresh the matching provider:

```bash
powercontext setup hermes --source oceanbase/powercontext --ref master
powercontext doctor hermes
```

The setup command copies the provider to `$HERMES_HOME/plugins/powercontext`. It does not start the Server or select
the provider in Hermes.

Run the Hermes memory setup wizard and select `PowerContext`:

```bash
hermes memory setup
```

On Hermes 0.20.4, use the generic command above. `hermes memory setup powercontext` selects the provider but does not
open its configuration wizard. Restart Hermes after setup.

## Verify recall and writes

```bash
hermes powercontext status
hermes powercontext remember preference "The user prefers uv"
hermes powercontext search "Python package manager"
```

The provider uses `http://127.0.0.1:8000` by default. It derives a scope from the active Hermes profile and gateway
user identifier. For a local CLI session without a user identifier, it derives a stable value from `HERMES_HOME`.
Set an explicit scope only when you intend to share or isolate Memory differently.

## Configure the connection

The wizard writes non-sensitive settings to `$HERMES_HOME/powercontext/config.json`. Environment variables override
the file:

| Variable | Purpose |
| --- | --- |
| `POWERCONTEXT_HERMES_BASE_URL` | PowerContext Server URL |
| `POWERCONTEXT_HERMES_AUTHORIZATION` | Complete authorization header, such as `Bearer <token>` |
| `POWERCONTEXT_HERMES_TOKEN` | Bare-token shorthand used when `AUTHORIZATION` is absent |
| `POWERCONTEXT_HERMES_SCOPE_ID` | Explicit scope or scope template |
| `POWERCONTEXT_HERMES_MAX_BYTES` | Maximum prepared-context size, from 512 to 32768 bytes |
| `POWERCONTEXT_HERMES_TIMEOUT` | HTTP request timeout in seconds |
| `POWERCONTEXT_HERMES_CAPTURE_TURNS` | Capture completed turns as Sources |
| `POWERCONTEXT_HERMES_FLUSH_ON_SESSION_END` | Run Memory extraction at session end |

Let the Hermes wizard store authorization in its protected `.env` secret store; do not put the token in
`config.json`. Use plain HTTP only for a loopback Server. See [Deploy the Server](deploy-server.md) before connecting
to a remote deployment.

## Enable automatic extraction only when needed

Completed-turn capture creates Source evidence. It does not create Memory by itself. Automatic Source-to-Memory
extraction requires a generation model on the Server:

```bash
export POWERCONTEXT_SERVER_INFERENCE_GENERATION_MODEL=provider:model-name
powercontext server run
powercontext capabilities
```

The capability output must report Memory extraction as enabled. Explicit `hermes powercontext remember` writes do not
require a model.
