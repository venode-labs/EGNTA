#!/usr/bin/env python
import argparse
import json
from pathlib import Path

from common import resolve_path


def load_model(model_name: str, adapter: str | None, max_seq_length: int):
    from unsloth import FastLanguageModel

    model, tokenizer = FastLanguageModel.from_pretrained(
        model_name=model_name,
        max_seq_length=max_seq_length,
        load_in_4bit=True,
    )
    if adapter:
        from peft import PeftModel

        model = PeftModel.from_pretrained(model, str(resolve_path(adapter)))
    FastLanguageModel.for_inference(model)
    return model, tokenizer


def generate(model, tokenizer, prompt: str, max_new_tokens: int) -> str:
    import torch

    messages = [{"role": "user", "content": prompt}]
    inputs = tokenizer.apply_chat_template(
        messages,
        tokenize=True,
        add_generation_prompt=True,
        return_tensors="pt",
    ).to("cuda")
    with torch.inference_mode():
        output = model.generate(
            input_ids=inputs,
            max_new_tokens=max_new_tokens,
            temperature=0.7,
            top_p=0.9,
            do_sample=True,
            pad_token_id=tokenizer.eos_token_id,
        )
    new_tokens = output[0][inputs.shape[1] :]
    return tokenizer.decode(new_tokens, skip_special_tokens=True).strip()


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a simple prompt/cases eval.")
    parser.add_argument("--model", required=True, help="Base model name or local path")
    parser.add_argument("--adapter", help="Optional LoRA adapter directory")
    parser.add_argument("--cases", type=Path, help="JSONL of {prompt, expect_contains?}")
    parser.add_argument("--prompt", help="Single prompt instead of a cases file")
    parser.add_argument("--max-seq-length", type=int, default=2048)
    parser.add_argument("--max-new-tokens", type=int, default=256)
    args = parser.parse_args()

    import torch

    if not torch.cuda.is_available():
        raise SystemExit("CUDA GPU is not available. Eval with Unsloth requires CUDA.")

    model, tokenizer = load_model(args.model, args.adapter, args.max_seq_length)

    if args.prompt:
        print(generate(model, tokenizer, args.prompt, args.max_new_tokens))
        return

    if not args.cases:
        raise SystemExit("pass --prompt or --cases")

    passed = 0
    total = 0
    with resolve_path(args.cases).open("r", encoding="utf-8") as f:
        for line in f:
            case = json.loads(line)
            total += 1
            output = generate(model, tokenizer, case["prompt"], args.max_new_tokens)
            expected = case.get("expect_contains")
            ok = True if expected is None else all(s.lower() in output.lower() for s in expected)
            passed += int(ok)
            print(f"[{'PASS' if ok else 'FAIL'}] {case['prompt'][:80]}")
            if not ok:
                print(f"output: {output[:500]}")

    print(f"{passed}/{total} passed")


if __name__ == "__main__":
    main()
