"""
Deploys the public CEOPRO-AI services to their EXISTING Hugging Face Spaces.

Each Space = its wrapper files in this folder + the exact CEOPRO-AI source files
listed in its SRC_MANIFEST.txt, copied unchanged from this repository's src/.
The Spaces (and therefore all public service URLs) must already exist: this
script only uploads a new commit to them and refuses to create a Space.

    https://huggingface.co/spaces/hhuuddaa/ceopro-ai-models     (Sentiment, Market Intelligence, RAG)
    https://huggingface.co/spaces/hhuuddaa/ceopro-ai-analytics  (Extraction, Demand Forecasting, Pricing)

Usage (needs a Hugging Face token with write access, e.g. HF_TOKEN):
    python deploy/huggingface_spaces/deploy.py ceopro-ai-analytics [--dry-run]
"""
import argparse
import shutil
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
OWNER = "hhuuddaa"
SPACES = ("ceopro-ai-models", "ceopro-ai-analytics")


def assemble(space: str, target: Path) -> list:
    source = HERE / space
    for path in source.iterdir():
        if path.is_file() and path.name != "SRC_MANIFEST.txt":
            shutil.copy2(path, target / path.name)
    copied = []
    for rel in (source / "SRC_MANIFEST.txt").read_text().split():
        dst = target / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        src = REPO / rel
        if src.exists():
            shutil.copy2(src, dst)
        elif rel.endswith("__init__.py"):
            dst.write_text("")  # package marker only
        else:
            raise FileNotFoundError(f"{rel} listed in {space}/SRC_MANIFEST.txt is missing from the repository")
        copied.append(rel)
    return copied


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("space", choices=SPACES)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    with tempfile.TemporaryDirectory() as tmp:
        target = Path(tmp)
        copied = assemble(args.space, target)
        print(f"assembled {args.space}: {len(copied)} source files + wrappers")
        if args.dry_run:
            return
        from huggingface_hub import HfApi
        api = HfApi()
        repo_id = f"{OWNER}/{args.space}"
        api.space_info(repo_id)  # raises if the Space does not exist - never create a new one / new URL
        info = api.upload_folder(
            repo_id=repo_id, repo_type="space", folder_path=str(target),
            commit_message="Deploy CEOPRO-AI service from GitHub deploy/huggingface_spaces",
            delete_patterns=["*.py", "src/**", "*.csv", "requirements.txt", "README.md"],
        )
        print("deployed commit:", getattr(info, "oid", info))


if __name__ == "__main__":
    sys.exit(main())
