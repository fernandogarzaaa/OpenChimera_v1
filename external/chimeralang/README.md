# ChimeraLang

**A programming language designed for AI cognition** — probabilistic types, quantum consensus gates, directed hallucination, and cryptographic integrity proofs.

ChimeraLang treats uncertainty, confidence, and epistemic state as **first-class language primitives** rather than bolted-on libraries. Programs in ChimeraLang describe *how an AI should think*, not just what it should compute.

---

## Key Features

| Feature | Description |
|---|---|
| **Probabilistic Types** | `Confident<T>`, `Explore<T>`, `Converge<T>`, `Provisional<T>` — types that carry confidence scores |
| **Quantum Consensus Gates** | Multiple candidate values vote under Gaussian noise; the result is the *consensus* of an ensemble |
| **Hallucination Detection** | 5 built-in strategies: range, dictionary, semantic, cross-reference, temporal |
| **Cryptographic Integrity** | Merkle-chain proofs and gate certificates ensure reasoning traces are tamper-evident |
| **Memory Modifiers** | `Ephemeral`, `Persistent`, `Provisional` — explicit lifecycle for every binding |
| **Intent-First Goals** | `goal` blocks declare desired outcomes; `reasoning` blocks show the derivation |

## Quick Start

### Prerequisites

- Python ≥ 3.11

### Run an example

```bash
cd ChimeraLang
python -m chimera.cli run examples/hello_chimera.chimera
```

### Available commands

```
python -m chimera.cli run    <file>   # Execute a .chimera program
python -m chimera.cli check  <file>   # Type-check without running
python -m chimera.cli prove  <file>   # Run and generate integrity proof
python -m chimera.cli ast    <file>   # Print the AST
python -m chimera.cli tokens <file>   # Print the token stream
```

## Examples

Four example programs are included in [`examples/`](examples/):

| File | What it demonstrates |
|---|---|
| `hello_chimera.chimera` | Basic emit, confident values |
| `quantum_reasoning.chimera` | Consensus gates with Gaussian noise, confidence propagation |
| `goal_driven.chimera` | Goals, reasoning blocks, semantic constraints |
| `hallucination_guard.chimera` | All 5 hallucination-detection strategies |

### Sample run

```
$ python -m chimera.cli run examples/quantum_reasoning.chimera

=== ChimeraLang Quantum Consensus VM ===
[gate:ensemble_gate] Candidate values: [42, 43, 41]
[gate:ensemble_gate] Noisy values:     [42.03, 42.98, 41.05]
[gate:ensemble_gate] Strategy: median → collapsed to 42.03
 >> ensemble_answer = 42.03 (confidence: 0.9500)
 >> high_confidence = true (confidence: 0.9800)
Verdict: PASS (confidence 0.95 ≥ 0.50)
```

## Project Structure

```
ChimeraLang/
├── chimera/                  # Core language implementation
│   ├── tokens.py             # 70+ token types
│   ├── lexer.py              # Tokenizer
│   ├── ast_nodes.py          # AST node hierarchy
│   ├── parser.py             # Recursive-descent parser
│   ├── types.py              # Runtime type system & confidence propagation
│   ├── type_checker.py       # Static type checker
│   ├── vm.py                 # Quantum Consensus VM
│   ├── detect.py             # Hallucination detector (5 strategies)
│   ├── integrity.py          # Merkle chains & gate certificates
│   └── cli.py                # Command-line interface
├── examples/                 # Example .chimera programs
├── spec/
│   └── SPEC.md               # Formal language specification
├── paper/
│   └── chimeralang.tex       # ArXiv whitepaper (LaTeX)
├── tests/                    # Test suite (planned)
└── pyproject.toml
```

## Language Overview

### Probabilistic Types

```chimera
val answer: Confident<Int> = confident(42, 0.95)
val idea:   Explore<Text>  = explore("maybe this?", 0.60)
```

Every value carries a **confidence score** (0.0–1.0). Confidence propagates through operations — if you combine two uncertain values, the result inherits a combined confidence.

### Quantum Consensus Gates

```chimera
gate ensemble_gate(strategy: "median", threshold: 0.80) {
    candidate a = 42
    candidate b = 43
    candidate c = 41
}
val result = consensus(ensemble_gate)
```

Candidates are perturbed with Gaussian noise, then collapsed via `mean`, `median`, or `majority_vote`. The gate only passes if collective confidence meets the threshold.

### Hallucination Detection

```chimera
detect hallucination {
    strategy: "range"
    on input: temperature
    valid_range: [-50.0, 60.0]
    action: "flag"
}
```

Five built-in strategies: `range`, `dictionary`, `semantic`, `cross_reference`, and `temporal`.

### Integrity Proofs

```bash
python -m chimera.cli prove examples/quantum_reasoning.chimera
```

Generates a Merkle-chain proof with SHA-256 hashes so that every step of the reasoning trace is tamper-evident.

## Academic Paper

A full whitepaper is available in [`paper/chimeralang.tex`](paper/chimeralang.tex). It covers the formal type system, execution model, consensus algorithms, and cryptographic integrity framework with 25 academic references.

To compile:
```bash
pdflatex chimeralang.tex   # or upload to Overleaf
bibtex chimeralang
pdflatex chimeralang.tex
pdflatex chimeralang.tex
```

## How It Differs

| Aspect | Traditional Languages | ChimeraLang |
|---|---|---|
| Values | Deterministic | Carry confidence scores |
| Execution | Single-path | Ensemble consensus |
| Correctness | Tests/assertions | Continuous hallucination detection |
| Auditability | Logs | Cryptographic Merkle proofs |
| Intent | Implicit in code | Explicit `goal` declarations |

## License

MIT

## Citation

```bibtex
@article{chimeralang2025,
  title   = {ChimeraLang: A Programming Language for AI Cognition},
  year    = {2025},
  note    = {https://github.com/fernandogarzaaa/ChimeraLang}
}
```
