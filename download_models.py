"""
CHIMERA Model Downloader
Downloads quantized GGUF models optimized for RTX 2060

Usage: python download_models.py [--model qwen2.5-7b] [--all]
"""

import os
import sys
import subprocess
from pathlib import Path

# Models optimized for RTX 2060 (6GB VRAM)
MODELS = {
    "qwen2.5-7b": {
        "repo": "Qwen/Qwen2.5-7B-Instruct-GGUF",
        "file": "qwen2.5-7b-instruct-q4_k_m.gguf",
        "size": "~4.5GB",
        "quantization": "Q4_K_M",
        "priority": 1,
    },
    "gemma-2-9b": {
        "repo": "google/gemma-2-9b-it-GGUF",
        "file": "gemma-2-9b-it-q4_k_m.gguf",
        "size": "~5.5GB",
        "quantization": "Q4_K_M",
        "priority": 2,
    },
    "llama-3.2-3b": {
        "repo": "meta-llama/Llama-3.2-3B-Instruct-GGUF",
        "file": "llama-3.2-3b-instruct-q8_0.gguf",
        "size": "~3GB",
        "quantization": "Q8_0",
        "priority": 3,
    },
    "phi-3.5-mini": {
        "repo": "microsoft/Phi-3.5-mini-instruct-GGUF",
        "file": "Phi-3.5-mini-instruct-q8_0.gguf",
        "size": "~2.5GB",
        "quantization": "Q8_0",
        "priority": 4,
    },
    "tinyllama-1.1b": {
        "repo": "TinyLlama/TinyLlama-1.1B-Chat-v1.0-GGUF",
        "file": "tinyllama-1.1b-chat-v1.0-q8_0.gguf",
        "size": "~1GB",
        "quantization": "Q8_0",
        "priority": 5,
    },
}


def check_huggingface_cli():
    """Check if huggingface-cli is installed."""
    try:
        subprocess.run(
            ["huggingface-cli", "--version"],
            check=True,
            capture_output=True,
        )
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False


def install_huggingface_hub():
    """Install huggingface_hub package."""
    print("📦 Installing huggingface_hub...")
    subprocess.run(
        [sys.executable, "-m", "pip", "install", "-U", "huggingface_hub"],
        check=True,
    )
    print("✅ huggingface_hub installed")


def download_model(model_key: str, output_dir: Path):
    """Download a single model."""
    if model_key not in MODELS:
        print(f"❌ Unknown model: {model_key}")
        print(f"Available: {', '.join(MODELS.keys())}")
        return False
    
    model_info = MODELS[model_key]
    repo = model_info["repo"]
    filename = model_info["file"]
    
    print(f"\n{'='*60}")
    print(f"📥 Downloading: {model_key}")
    print(f"   Repo: {repo}")
    print(f"   File: {filename}")
    print(f"   Size: {model_info['size']}")
    print(f"   Quantization: {model_info['quantization']}")
    print(f"{'='*60}\n")
    
    # Create models directory
    models_dir = output_dir / "models"
    models_dir.mkdir(parents=True, exist_ok=True)
    
    # Check if already downloaded
    model_path = models_dir / filename
    if model_path.exists():
        print(f"✅ Model already exists: {model_path}")
        return True
    
    # Download using huggingface-cli
    try:
        subprocess.run(
            [
                "huggingface-cli", "download",
                "--repo-type", "model",
                "--local-dir", str(models_dir),
                "--include", filename,
                repo,
            ],
            check=True,
        )
        
        if model_path.exists():
            print(f"✅ Downloaded: {model_path}")
            return True
        else:
            print(f"❌ Download completed but file not found: {model_path}")
            return False
            
    except subprocess.CalledProcessError as e:
        print(f"❌ Download failed: {e}")
        return False
    except KeyboardInterrupt:
        print("\n⚠️  Download cancelled by user")
        return False


def download_all(output_dir: Path):
    """Download all models in priority order."""
    print("\n🚀 CHIMERA Model Downloader")
    print("=" * 60)
    print("Downloading all models optimized for RTX 2060")
    print("=" * 60)
    
    # Sort by priority
    sorted_models = sorted(MODELS.items(), key=lambda x: x[1]["priority"])
    
    results = {}
    for model_key, info in sorted_models:
        success = download_model(model_key, output_dir)
        results[model_key] = success
        
        if not success:
            print(f"\n⚠️  Continuing despite failure...\n")
    
    # Summary
    print("\n" + "=" * 60)
    print("📊 Download Summary")
    print("=" * 60)
    
    total = len(results)
    successful = sum(1 for v in results.values() if v)
    
    for model_key, success in results.items():
        status = "✅" if success else "❌"
        print(f"   {status} {model_key}")
    
    print(f"\nTotal: {successful}/{total} models downloaded")
    
    if successful > 0:
        print("\n🎉 Models ready! Start llama.cpp servers with:")
        print("   .\\start_local_llms.bat")
    
    return successful > 0


def main():
    import argparse
    
    parser = argparse.ArgumentParser(description="Download CHIMERA local LLM models")
    parser.add_argument(
        "--model",
        type=str,
        help="Specific model to download (e.g., qwen2.5-7b)",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Download all models",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(__file__).parent,
        help="Output directory for models",
    )
    
    args = parser.parse_args()
    
    # Check/install huggingface-cli
    if not check_huggingface_cli():
        print("⚠️  huggingface-cli not found")
        install_huggingface_hub()
    
    # Download requested models
    if args.all:
        download_all(args.output_dir)
    elif args.model:
        download_model(args.model, args.output_dir)
    else:
        # Interactive mode
        print("\n🚀 CHIMERA Model Downloader")
        print("=" * 60)
        print("\nAvailable models for RTX 2060:")
        print()
        
        sorted_models = sorted(MODELS.items(), key=lambda x: x[1]["priority"])
        for i, (key, info) in enumerate(sorted_models, 1):
            print(f"   {i}. {key}")
            print(f"      Size: {info['size']}, Quant: {info['quantization']}")
            print(f"      Priority: {info['priority']}")
            print()
        
        print("Commands:")
        print("   python download_models.py --all")
        print("   python download_models.py --model qwen2.5-7b")
        print()
        
        choice = input("Download all models? (y/n): ").strip().lower()
        if choice == 'y':
            download_all(args.output_dir)
        else:
            print("👋 No models downloaded")


if __name__ == "__main__":
    main()
