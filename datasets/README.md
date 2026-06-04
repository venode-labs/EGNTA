# Datasets

This directory is a local workspace. Generated datasets are ignored by Git.

Tracked:

- `samples/` - tiny examples for smoke tests and validation.

Ignored:

- `raw/` - unmodified source dumps.
- `processed/` - normalized JSONL train/eval files.
- `train/` and `eval/` - expanded local training splits.

Every real dataset source needs a source name, license, and transform note in a config file.
