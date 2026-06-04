#!/usr/bin/env python
import argparse
import json
from pathlib import Path

from common import resolve_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Merge a LoRA adapter into its base model.")
    parser.add_argument("--adapter", type=Path, required=True, help="LoRA adapter directory")
    parser.add_argument("--out", type=Path, required=True, help="Output directory for merged model")
    parser.add_argument("--base", help="Override base model; default reads adapter_config.json")
    args = parser.parse_args()

    adapter = resolve_path(args.adapter)
    out_dir = resolve_path(args.out)
    cfg_path = adapter / "adapter_config.json"
    base = args.base or json.loads(cfg_path.read_text())["base_model_name_or_path"]

    from peft import PeftModel
    from unsloth import FastLanguageModel

    model, tokenizer = FastLanguageModel.from_pretrained(
        model_name=base,
        max_seq_length=2048,
        load_in_4bit=False,
    )
    model = PeftModel.from_pretrained(model, str(adapter))
    model = model.merge_and_unload()

    out_dir.mkdir(parents=True, exist_ok=True)
    model.save_pretrained(str(out_dir), safe_serialization=True)
    tokenizer.save_pretrained(str(out_dir))
    print(f"merged model saved: {out_dir}")


if __name__ == "__main__":
    main()
