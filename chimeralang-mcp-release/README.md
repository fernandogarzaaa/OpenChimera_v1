# chimeralang-mcp

**Give Claude typed confidence, hallucination detection, and constraint enforcement — as native MCP tools.**

ChimeraLang is a programming language built for AI cognition. This MCP server exposes its runtime as 12 tools Claude can call during any conversation — no Anthropic permission needed, works today with Claude Desktop and Claude Code.

---

## Install

```bash
pip install chimeralang-mcp
# or
uvx chimeralang-mcp
```

---

## Claude Desktop Setup

Add to your config file:

**macOS:** `~/Library/Application Support/Claude/claude_desktop_config.json`  
**Windows:** `%APPDATA%\Claude\claude_desktop_config.json`

```json
{
  "mcpServers": {
    "chimeralang": {
      "command": "uvx",
      "args": ["chimeralang-mcp"]
    }
  }
}
```

Or with pip-installed version:
```json
{
  "mcpServers": {
    "chimeralang": {
      "command": "python",
      "args": ["-m", "chimeralang_mcp"]
    }
  }
}
```

Restart Claude Desktop — 12 ChimeraLang tools are now available.

---

## Tools

| Tool | What it does |
|---|---|
| `chimera_run` | Execute a `.chimera` program string |
| `chimera_confident` | Assert a value meets >= 0.95 confidence threshold |
| `chimera_explore` | Wrap a value as exploratory (hallucination explicitly permitted) |
| `chimera_gate` | Collapse multiple candidates via consensus (majority / weighted_vote / highest_confidence) |
| `chimera_detect` | Hallucination detection — 5 strategies: range, dictionary, semantic, cross_reference, temporal |
| `chimera_constrain` | Full constraint middleware on any tool result |
| `chimera_typecheck` | Static type-check a `.chimera` program |
| `chimera_prove` | Execute + Merkle-chain integrity proof |
| `chimera_audit` | Session-level call log and confidence summary |
| `chimera_compress` | Proportional message-history compression to a token budget |
| `chimera_optimize` | Aggressive text extraction (structural + entity + frequency) |
| `chimera_fracture` | Full pipeline — optimize docs + compress messages + quality gate |

---

## What problem does this solve?

Claude's tool-use loop has no built-in mechanism for:

- **Confidence gating** — only proceed if confidence >= threshold
- **Typed output contracts** — this result must satisfy constraint X before going downstream  
- **Genuine consensus detection** — is multi-path agreement real, or trivially identical?
- **Hallucination signals** — structured detection, not just "does it sound right"
- **Trust propagation** — confidence degrades through chained tool calls; nothing tracks it

ChimeraLang fills exactly these gaps as a constraint layer sitting between Claude and its tools.

---

## Example prompts

**Gate a value before a critical action:**
> *"Before you submit that form, use chimera_confident to verify you're >= 0.95 confident the data is correct."*

**Consensus across reasoning paths:**
> *"Generate 3 different answers, then use chimera_gate with weighted_vote to collapse to the most reliable one."*

**Hallucination scan on output:**
> *"After you get that search result, run chimera_detect with semantic strategy to check for absolute-certainty markers."*

**Full constraint pipeline:**
> *"Use chimera_constrain on that tool result with min_confidence 0.85 and detect_strategy semantic."*

**Integrity proof for audit:**
> *"Run this reasoning with chimera_prove so we have a tamper-evident trace."*

---

## ChimeraLang Quick Reference

```chimera
// Confident<> — enforces >= 0.95 confidence
val answer: Confident<Text> = confident("Paris", 0.97)

// Explore<> — hallucination explicitly permitted
val hypothesis: Explore<Text> = explore("maybe dark matter is...", 0.4)

// Gate — multi-branch consensus
gate verify(claim: Text) -> Converge<Text>
  branches: 3
  collapse: weighted_vote
  threshold: 0.80
  return claim
end

// Detect — hallucination scan
detect temperature_check
  strategy: "range"
  on: temperature
  valid_range: [-50.0, 60.0]
  action: "flag"
end
```

---

## Links

- **ChimeraLang core:** [github.com/fernandogarzaaa/ChimeraLang](https://github.com/fernandogarzaaa/ChimeraLang)
- **OpenChimera:** [github.com/fernandogarzaaa/OpenChimera_v1](https://github.com/fernandogarzaaa/OpenChimera_v1)

---

## License

MIT © [Fernando Garza](https://github.com/fernandogarzaaa)
