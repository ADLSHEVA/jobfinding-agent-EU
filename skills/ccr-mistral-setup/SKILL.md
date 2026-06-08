# CCR + Mistral → Claude Code Setup Guide

> How to route a Mistral API key through Claude Code Router (CCR) into Claude Code — distilled from real debugging sessions.

## Architecture

```
Claude Code (CC)  ──Anthropic format──▶  CCR (localhost:3456)  ──OpenAI format──▶  Mistral API
                  ◀──Anthropic format──  (translate + route)    ◀──OpenAI format──
```

CCR is a local proxy. It receives Anthropic-format requests from CC, translates them to the target API's format (OpenAI for Mistral), forwards them, and translates responses back.

---

## Step 1: Install CCR

```bash
npm install -g claude-code-router
```

Verify:
```bash
ccr --version
```

---

## Step 2: Create CCR config

Config path: `~/.claude-code-router/config.json`

**Pitfall 1 — `api_base_url` must include `/chat/completions`**

Mistral's OpenAI-compatible endpoint is `https://api.mistral.ai/v1/chat/completions`.
If you only write `https://api.mistral.ai/v1`, CCR doesn't know where to forward — you get 404.

**Pitfall 2 — Use the `OpenAI` transformer, NOT `Anthropic`**

CC sends Anthropic format (`/v1/messages`). CCR must convert it to OpenAI format (`/v1/chat/completions`) for Mistral.

- ❌ `"use": ["Anthropic"]` — converts TO Anthropic format, wrong direction
- ❌ `"use": []` — no conversion, Mistral receives Anthropic format and returns 400
- ✅ `"use": ["strip-reasoning", "OpenAI", "cleancache"]` — strip unsupported fields, then convert to OpenAI

**Pitfall 3 — Must write a custom transformer to strip the `reasoning` field**

CC includes a `reasoning` field in requests (for extended thinking). Mistral does not support it and rejects the request. CCR has no built-in handler for this — you need a custom transformer.

Full config:

```json
{
  "LOG": true,
  "LOG_LEVEL": "debug",
  "HOST": "127.0.0.1",
  "PORT": 3456,
  "APIKEY": "",
  "API_TIMEOUT_MS": "600000",
  "PROXY_URL": "",
  "transformers": [
    {
      "path": "C:/Users/<YOUR_USERNAME>/.claude-code-router/strip-reasoning.js"
    }
  ],
  "Providers": [
    {
      "name": "Mistral",
      "api_base_url": "https://api.mistral.ai/v1/chat/completions",
      "api_key": "<YOUR_MISTRAL_API_KEY>",
      "models": [
        "mistral-medium-latest",
        "devstral-small-latest"
      ],
      "transformer": {
        "use": ["strip-reasoning", "OpenAI", "cleancache"],
        "mistral-medium-latest": {
          "use": ["strip-reasoning", "OpenAI", "cleancache"]
        },
        "devstral-small-latest": {
          "use": ["strip-reasoning", "OpenAI", "cleancache"]
        }
      }
    }
  ],
  "StatusLine": {
    "enabled": false,
    "currentStyle": "default",
    "default": { "modules": [] },
    "powerline": { "modules": [] }
  },
  "Router": {
    "default": "Mistral,devstral-small-latest",
    "background": "Mistral,devstral-small-latest",
    "think": "Mistral,mistral-medium-latest",
    "longContext": "Mistral,mistral-medium-latest",
    "longContextThreshold": 200000,
    "webSearch": "Mistral,mistral-medium-latest",
    "image": ""
  },
  "CUSTOM_ROUTER_PATH": ""
}
```

---

## Step 3: Create strip-reasoning.js

Path: `~/.claude-code-router/strip-reasoning.js`

A copy is included in this skill directory — just paste it into `~/.claude-code-router/`.

```javascript
class StripReasoningTransformer {
  name = "strip-reasoning";

  async transformRequestIn(requestBody, provider, context) {
    if (requestBody && typeof requestBody === "object" && "reasoning" in requestBody) {
      delete requestBody.reasoning;
    }
    return requestBody;
  }

  async transformResponseOut(response) {
    return response;
  }
}

module.exports = StripReasoningTransformer;
```

---

## Step 4: Start CCR

```bash
ccr start
```

Verify it's running:
```bash
cat ~/.claude-code-router/.claude-code-router.pid
curl http://127.0.0.1:3456
```

**Pitfall 4 — CCR must be running before CC starts**

CC connects to CCR on startup. If CCR isn't listening, CC fails immediately.

---

## Step 5: Configure Claude Code to connect to CCR

**Pitfall 5 — CC's `customApiKeyResponses` needs a `dummy` entry**

CC checks whether an API key has been approved on startup. With CCR, the real key lives on the CCR side — CC doesn't need one. But CC's config must have at least one approved key or it gets stuck in onboarding.

In the project's `.claude.json` (or global `~/.claude.json`):

```json
{
  "customApiKeyResponses": {
    "approved": ["dummy"],
    "rejected": []
  },
  "hasCompletedOnboarding": true
}
```

Then launch CC pointing at CCR:

```bash
ANTHROPIC_BASE_URL=http://127.0.0.1:3456 ANTHROPIC_API_KEY=dummy claude
```

PowerShell:

```powershell
$env:ANTHROPIC_BASE_URL="http://127.0.0.1:3456"
$env:ANTHROPIC_API_KEY="dummy"
claude
```

---

## Step 6: Verify

Ask CC something simple, e.g. "What day is it?".

Check CCR logs (`~/.claude-code-router/logs/`) to confirm:
1. Request arrives from CC (`/v1/messages`)
2. Transformers fire (`strip-reasoning` + `OpenAI`)
3. Request forwards to Mistral (`/v1/chat/completions`)
4. Response translates back to CC

---

## Pitfall Summary

| # | Problem | Symptom | Fix |
|---|---------|---------|-----|
| 1 | `api_base_url` missing `/chat/completions` | 404 Not Found | Use full URL: `https://api.mistral.ai/v1/chat/completions` |
| 2 | Used `Anthropic` transformer | 400 Bad Request | Use `OpenAI` transformer instead |
| 3 | `reasoning` field not stripped | Mistral rejects the request | Write custom `strip-reasoning.js` transformer |
| 4 | CCR not started before CC | Connection refused | Run `ccr start` first |
| 5 | CC approved key list empty | Stuck in onboarding | Set `"approved": ["dummy"]` |
| 6 | Router default set to expensive model | Every call uses `mistral-medium` | Use `devstral-small-latest` for default/background, reserve medium for think/longContext |

---

## Available Mistral Models

| Model | Use case | Notes |
|-------|----------|-------|
| `devstral-small-latest` | Daily chat, code | Fast, cheap |
| `mistral-medium-latest` | Complex reasoning, long context | Slower, more expensive, more capable |

Router recommendation:
- `default` / `background` → `devstral-small-latest` (save tokens)
- `think` / `longContext` / `webSearch` → `mistral-medium-latest` (when you need the extra capability)

---

## Quick Copy-Paste

### Final config.json (replace `<USERNAME>` and `<API_KEY>`)

```json
{
  "LOG": true,
  "LOG_LEVEL": "debug",
  "CLAUDE_PATH": "",
  "HOST": "127.0.0.1",
  "PORT": 3456,
  "APIKEY": "",
  "API_TIMEOUT_MS": "600000",
  "PROXY_URL": "",
  "transformers": [
    {
      "path": "C:/Users/<USERNAME>/.claude-code-router/strip-reasoning.js"
    }
  ],
  "Providers": [
    {
      "name": "Mistral",
      "api_base_url": "https://api.mistral.ai/v1/chat/completions",
      "api_key": "<API_KEY>",
      "models": ["mistral-medium-latest", "devstral-small-latest"],
      "transformer": {
        "use": ["strip-reasoning", "OpenAI", "cleancache"],
        "mistral-medium-latest": { "use": ["strip-reasoning", "OpenAI", "cleancache"] },
        "devstral-small-latest": { "use": ["strip-reasoning", "OpenAI", "cleancache"] }
      }
    }
  ],
  "StatusLine": { "enabled": false, "currentStyle": "default", "default": { "modules": [] }, "powerline": { "modules": [] } },
  "Router": {
    "default": "Mistral,devstral-small-latest",
    "background": "Mistral,devstral-small-latest",
    "think": "Mistral,mistral-medium-latest",
    "longContext": "Mistral,mistral-medium-latest",
    "longContextThreshold": 200000,
    "webSearch": "Mistral,mistral-medium-latest",
    "image": ""
  },
  "CUSTOM_ROUTER_PATH": ""
}
```

### One-liner launch

```bash
# 1. Start CCR
ccr start

# 2. Start CC connected to CCR
ANTHROPIC_BASE_URL=http://127.0.0.1:3456 ANTHROPIC_API_KEY=dummy claude
```

---

## Debugging

1. **Enable CCR logs**: set `"LOG": true, "LOG_LEVEL": "debug"` in `config.json`
2. **Read log files**: `~/.claude-code-router/logs/ccr-*.log`
3. **400 errors**: check transformer config — make sure `OpenAI` is in the `use` list
4. **404 errors**: check `api_base_url` — must end with `/chat/completions`
5. **CCR won't respond**: check PID file, `ccr stop` then `ccr start`
