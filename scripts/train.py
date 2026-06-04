#!/usr/bin/env python
import argparse
import inspect
import os
from pathlib import Path
from typing import Any

import yaml

from common import normalize_messages, resolve_path


def load_config(path: Path) -> dict[str, Any]:
    return yaml.safe_load(resolve_path(path).read_text())


def load_training_dataset(dataset_cfg: dict[str, Any], tokenizer):
    from datasets import load_dataset

    source = dataset_cfg["source"]
    split = dataset_cfg.get("split", "train")
    limit = dataset_cfg.get("limit")

    source_path = resolve_path(source)
    if source_path.exists() and source_path.suffix in {".jsonl", ".json"}:
        dataset = load_dataset("json", data_files=str(source_path), split="train")
    else:
        dataset = load_dataset(source, split=split)

    if limit:
        dataset = dataset.select(range(min(int(limit), len(dataset))))

    def to_text(row: dict[str, Any]) -> dict[str, str]:
        messages = normalize_messages(row)
        text = tokenizer.apply_chat_template(
            messages,
            tokenize=False,
            add_generation_prompt=False,
        )
        return {"text": text}

    return dataset.map(to_text, remove_columns=dataset.column_names)


def precision_flags(setting: str) -> tuple[bool, bool]:
    import torch

    setting = setting.lower()
    if setting == "bf16":
        return True, False
    if setting == "fp16":
        return False, True
    if setting != "auto":
        raise ValueError("train.precision must be auto, bf16, or fp16")

    bf16 = torch.cuda.is_available() and torch.cuda.is_bf16_supported()
    return bf16, not bf16


def build_sft_config(cfg: dict[str, Any], out_dir: Path):
    from trl import SFTConfig

    train_cfg = cfg["train"]
    model_cfg = cfg["model"]
    hub_cfg = cfg.get("hub", {})
    bf16, fp16 = precision_flags(train_cfg.get("precision", "auto"))

    kwargs = {
        "output_dir": str(out_dir),
        "per_device_train_batch_size": train_cfg["per_device_batch_size"],
        "gradient_accumulation_steps": train_cfg["gradient_accumulation_steps"],
        "warmup_steps": train_cfg["warmup_steps"],
        "max_steps": train_cfg["max_steps"],
        "learning_rate": float(train_cfg["learning_rate"]),
        "weight_decay": float(train_cfg["weight_decay"]),
        "logging_steps": train_cfg["logging_steps"],
        "save_steps": train_cfg["save_steps"],
        "seed": train_cfg["seed"],
        "bf16": bf16,
        "fp16": fp16,
        "optim": train_cfg.get("optim", "adamw_8bit"),
        "report_to": train_cfg.get("report_to", "none"),
        "dataset_text_field": "text",
        "packing": bool(train_cfg.get("packing", False)),
    }

    params = inspect.signature(SFTConfig.__init__).parameters
    max_length = model_cfg.get("max_length", model_cfg.get("max_seq_length", 2048))
    if "max_length" in params:
        kwargs["max_length"] = max_length
    elif "max_seq_length" in params:
        kwargs["max_seq_length"] = max_length

    run_name = train_cfg.get("run_name", cfg.get("run_name"))
    if run_name and "run_name" in params:
        kwargs["run_name"] = run_name
    if "project" in train_cfg and "project" in params:
        kwargs["project"] = train_cfg["project"]

    if hub_cfg.get("push_to_hub"):
        if "push_to_hub" in params:
            kwargs["push_to_hub"] = True
        if "hub_model_id" in params:
            kwargs["hub_model_id"] = hub_cfg["model_id"]
        if "hub_strategy" in params and hub_cfg.get("strategy"):
            kwargs["hub_strategy"] = hub_cfg["strategy"]
        if "hub_private_repo" in params and "private" in hub_cfg:
            kwargs["hub_private_repo"] = bool(hub_cfg["private"])

    return SFTConfig(**kwargs)


def has_hub_token() -> bool:
    if os.environ.get("HF_TOKEN"):
        return True
    try:
        from huggingface_hub import get_token
    except Exception:
        return False
    return bool(get_token())


def uses_trackio(train_cfg: dict[str, Any]) -> bool:
    report_to = train_cfg.get("report_to", "none")
    if isinstance(report_to, str):
        return report_to.lower() == "trackio"
    return "trackio" in {str(item).lower() for item in report_to}


def init_trackio(cfg: dict[str, Any]):
    train_cfg = cfg["train"]
    if not uses_trackio(train_cfg):
        return None

    import trackio

    hub_model_id = cfg.get("hub", {}).get("model_id", "")
    hub_owner = hub_model_id.split("/", 1)[0] if "/" in hub_model_id else None
    space_id = train_cfg.get("trackio_space_id") or (f"{hub_owner}/trackio" if hub_owner else None)

    init_kwargs = {
        "project": train_cfg.get("project", "egenta"),
        "name": train_cfg.get("run_name", cfg.get("run_name")),
        "config": {
            "model": cfg["model"]["name"],
            "dataset": cfg["dataset"]["source"],
            "learning_rate": float(train_cfg["learning_rate"]),
            "max_steps": train_cfg["max_steps"],
            "max_length": cfg["model"].get("max_length", cfg["model"].get("max_seq_length", 2048)),
        },
    }
    if space_id:
        init_kwargs["space_id"] = space_id

    trackio.init(**init_kwargs)
    return trackio


def main() -> None:
    parser = argparse.ArgumentParser(description="Train a QLoRA adapter with Unsloth + TRL SFT.")
    parser.add_argument("config", type=Path)
    args = parser.parse_args()

    import torch

    if not torch.cuda.is_available():
        raise SystemExit(
            "CUDA GPU is not available. Fix the NVIDIA driver/CUDA setup or run this on a cloud GPU."
        )

    from trl import SFTTrainer
    from unsloth import FastLanguageModel
    from unsloth.chat_templates import get_chat_template

    cfg = load_config(args.config)
    run_name = cfg["run_name"]
    hub_cfg = cfg.get("hub", {})
    if hub_cfg.get("push_to_hub") and not has_hub_token():
        raise SystemExit(
            "hub.push_to_hub is enabled, but no Hugging Face token is available. "
            "Set HF_TOKEN for Hugging Face Jobs or run `hf auth login` locally."
        )

    out_dir = resolve_path(Path("runs") / run_name)
    adapter_dir = resolve_path(Path("adapters") / run_name)
    max_length = cfg["model"].get("max_length", cfg["model"].get("max_seq_length", 2048))

    model, tokenizer = FastLanguageModel.from_pretrained(
        model_name=cfg["model"]["name"],
        max_seq_length=max_length,
        load_in_4bit=cfg["model"].get("load_in_4bit", True),
    )

    chat_template = cfg["model"].get("chat_template")
    if chat_template:
        tokenizer = get_chat_template(tokenizer, chat_template=chat_template)

    model = FastLanguageModel.get_peft_model(
        model,
        r=cfg["lora"]["r"],
        lora_alpha=cfg["lora"]["alpha"],
        lora_dropout=cfg["lora"]["dropout"],
        target_modules=cfg["lora"]["target_modules"],
        bias="none",
        use_gradient_checkpointing="unsloth",
        random_state=cfg["train"].get("seed", 3407),
    )

    train_dataset = load_training_dataset(cfg["dataset"], tokenizer)
    sft_config = build_sft_config(cfg, out_dir)
    trackio_run = init_trackio(cfg)

    trainer_kwargs = {
        "model": model,
        "train_dataset": train_dataset,
        "args": sft_config,
    }
    trainer_params = inspect.signature(SFTTrainer.__init__).parameters
    if "processing_class" in trainer_params:
        trainer_kwargs["processing_class"] = tokenizer
    else:
        trainer_kwargs["tokenizer"] = tokenizer

    trainer = SFTTrainer(**trainer_kwargs)
    try:
        trainer.train()
    finally:
        if trackio_run is not None:
            trackio_run.finish()

    adapter_dir.mkdir(parents=True, exist_ok=True)
    model.save_pretrained(str(adapter_dir))
    tokenizer.save_pretrained(str(adapter_dir))
    print(f"adapter saved: {adapter_dir}")

    if hub_cfg.get("push_to_hub"):
        trainer.push_to_hub()
        print(f"adapter pushed: https://huggingface.co/{hub_cfg['model_id']}")


if __name__ == "__main__":
    main()
