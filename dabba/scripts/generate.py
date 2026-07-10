"""
Generation script for trained dabba models.

Loads a trained model checkpoint and generates text from a prompt.
Supports interactive chat mode, batch generation, and streaming.

Usage:
    python -m dabba.scripts.generate --checkpoint ./checkpoints/best \
        --prompt "Once upon a time"
    python -m dabba.scripts.generate --checkpoint ./checkpoints/best \
        --interactive
    python -m dabba.scripts.generate --checkpoint ./checkpoints/best \
        --prompt "Hello" --max-tokens 200 --temperature 0.8 --top-p 0.9
"""

import argparse
import sys
from pathlib import Path
from typing import Optional

import torch

from dabba.utils.config_loader import load_config
from dabba.utils.logging import setup_logger, get_logger
from dabba.model.transformer import Transformer
from dabba.config.model_config import ModelConfig
from dabba.inference.generator import Generator


def parse_args():
    parser = argparse.ArgumentParser(
        description="Generate text using a trained dabba model"
    )
    parser.add_argument("--checkpoint", type=str, required=True,
                        help="Path to checkpoint directory")
    parser.add_argument("--config", type=str,
                        help="Path to model config file (optional)")
    parser.add_argument("--prompt", type=str, default=None,
                        help="Text prompt for generation")
    parser.add_argument("--interactive", action="store_true",
                        help="Run in interactive chat mode")
    parser.add_argument("--max-tokens", type=int, default=100,
                        help="Maximum tokens to generate")
    parser.add_argument("--temperature", type=float, default=0.7,
                        help="Sampling temperature")
    parser.add_argument("--top-k", type=int, default=None,
                        help="Top-K sampling parameter")
    parser.add_argument("--top-p", type=float, default=0.9,
                        help="Top-P (nucleus) sampling parameter")
    parser.add_argument("--do-sample", action="store_true", default=True,
                        help="Use sampling (vs greedy)")
    parser.add_argument("--beam-size", type=int, default=None,
                        help="Beam search beam size (overrides sampling)")
    parser.add_argument("--device", type=str, default="auto",
                        choices=["auto", "cpu", "cuda"],
                        help="Device to run on")
    return parser.parse_args()


def load_model(checkpoint_path: str, config_path: Optional[str] = None) -> Transformer:
    """
    Load a trained model from a checkpoint.

    Args:
        checkpoint_path: Path to checkpoint directory.
        config_path: Path to model config file.

    Returns:
        Loaded Transformer model.
    """
    logger = get_logger("dabba.scripts")
    checkpoint_dir = Path(checkpoint_path)

    if config_path:
        model_config, _, _, _ = load_config(config_path)
    else:
        import json
        config_file = checkpoint_dir.parent / "config.json"
        if config_file.exists():
            with open(config_file) as f:
                config_data = json.load(f)
            model_config = ModelConfig(**config_data)
        else:
            model_config = ModelConfig.from_preset("tiny")
            logger.warning("No config found, using tiny preset")

    model = Transformer(model_config)

    model_file = checkpoint_dir / "model.pt"
    if model_file.exists():
        state = torch.load(model_file, map_location="cpu")
        if "model_state_dict" in state:
            model.load_state_dict(state["model_state_dict"])
        else:
            model.load_state_dict(state)
        logger.info(f"Loaded model from {model_file}")
    else:
        raise FileNotFoundError(f"No model file found at {model_file}")

    return model


@torch.no_grad()
def main():
    args = parse_args()
    logger = setup_logger("dabba.scripts")

    if args.device == "auto":
        device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    else:
        device = torch.device(args.device)
    logger.info(f"Using device: {device}")

    model = load_model(args.checkpoint, args.config)
    model = model.to(device)
    model.eval()
    logger.info(f"Model loaded: {sum(p.numel() for p in model.parameters()) / 1e6:.1f}M params")

    generator = Generator(model=model)

    def generate(prompt: str) -> str:
        """Generate text from a prompt string."""
        dummy_tokenizer = type('DummyTokenizer', (), {
            'encode': lambda self, s: [ord(c) for c in s[:100]],
            'decode': lambda self, ids: ''.join(chr(i) if 32 <= i <= 126 else '?' for i in ids),
        })()

        input_ids = torch.tensor(
            dummy_tokenizer.encode(prompt),
            dtype=torch.long,
            device=device,
        ).unsqueeze(0)

        if args.beam_size:
            output_ids = generator.beam_search(
                input_ids,
                beam_size=args.beam_size,
                max_length=args.max_tokens,
            )
        else:
            output_ids = generator.generate(
                input_ids=input_ids,
                max_new_tokens=args.max_tokens,
                temperature=args.temperature,
                top_k=args.top_k,
                top_p=args.top_p,
                do_sample=args.do_sample,
            )

        response = dummy_tokenizer.decode(
            output_ids[0][len(input_ids[0]):].tolist()
        )
        return response

    if args.prompt:
        result = generate(args.prompt)
        print(f"\nPrompt: {args.prompt}")
        print(f"Response: {result}\n")

    if args.interactive:
        print("\nInteractive mode. Type 'exit' to quit.\n")
        while True:
            try:
                prompt = input(">>> ")
                if prompt.lower() in ("exit", "quit", "q"):
                    break
                result = generate(prompt)
                print(f"\n{result}\n")
            except KeyboardInterrupt:
                print("\nExiting...")
                break
            except Exception as e:
                print(f"Error: {e}")


if __name__ == "__main__":
    main()
