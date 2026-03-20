# Research: Mechanistic Interpretability & Sparse Autoencoders (SAE)

## Executive Summary
Sparse Autoencoders (SAEs) provide a scalable method for decomposing high-dimensional neural network activations into interpretable, "monosemantic" features. By learning a sparse dictionary of features, we can effectively "look inside" a model to understand what concepts (e.g., "coding in Python", "political bias", "truthfulness") trigger specific neural activations.

## 1. How SAEs Work
Traditional neural networks suffer from **polysemanticity** (neurons firing for multiple unrelated concepts). SAEs solve this by training a small autoencoder on the activation stream:
*   **Architecture**: An encoder `E(x)` and decoder `D(f)`.
*   **Sparsity**: We introduce an L1 penalty on the hidden features `f` to force the network to represent activations using only a small subset of the total possible features.
*   **Monosemanticity**: Research (notably Anthropic's work) shows that these learned features tend to be monosemantic, meaning they correspond to a single, human-understandable concept.

## 2. Local Model Introspection Techniques

For a local system running on an RTX 2060, here is the recommended approach for implementing model introspection:

### A. The Activation-Capture Pipeline
1.  **Hooking**: Use tools like `TransformerLens` or PyTorch hooks to intercept the residual stream at specific layers during inference.
2.  **Dataset**: Capture ~100k-1M activations from typical usage logs or synthetic dataset generation.
3.  **SAE Training**: Train the autoencoder on these captured activations.
    *   *Constraint*: Keep the feature dimension expansion (e.g., if hidden size is 2048, expand to 16k or 32k features).
    *   *Optimization*: Use Adam with low learning rates, and tune the L1 coefficient (`lambda`) carefully to balance reconstruction error vs. sparsity.

### B. Mapping Features to Concepts
*   **Feature Ablation**: Once features are identified, "zero out" specific features during forward passes to observe the effect on the model's output. If zeroing feature #452 causes the model to stop referencing "OpenClaw" or "Python", you've found the relevant concept.
*   **Maximum Activation Sampling**: Feed the model a corpus of text and store the snippets that cause the highest activation for a specific feature. This reveals the "semantic cluster" for that feature.

## 3. Practical Local Implementation
For an RTX 2060 (6GB VRAM) environment:
*   **Keep Models Small**: Focus SAE implementation on smaller local models (e.g., Llama-3-8B or Phi-3) to fit both model activations and the SAE in VRAM.
*   **Quantization**: Use 8-bit or 4-bit loading for the base model, reserving VRAM for the SAE training/inference.
*   **Batching**: Process activations in small batches. Don't attempt to store millions of raw activations in RAM; stream them from disk.

## 4. Proposed Next Steps for CHIMERA
1.  **Pilot**: Implement a "Probing/Diagnostic" script that records activations for 500 prompts.
2.  **Dictionary Learning**: Train a lightweight SAE (low width, e.g., 2048 -> 4096) on the model's residual stream.
3.  **Visualization**: Build a simple script that outputs the top tokens for the top-activating features, allowing us to inspect the "latent vocabulary" of the model.
