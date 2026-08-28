from __future__ import annotations

import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent / "data"
IEEE_FILE = DATA_DIR / "train_transaction.csv"
PAYSIM_FILE = DATA_DIR / "PS_20174392719_1491204439457_log.csv"

MANUAL = """
Download manually from Kaggle and place files in backend/ml/data/:

1. IEEE-CIS Fraud Detection — train_transaction.csv
   https://www.kaggle.com/competitions/ieee-fraud-detection/data

2. PaySim — PS_20174392719_1491204439457_log.csv
   https://www.kaggle.com/datasets/ealaxi/paysim1

Then re-run: python -m backend.ml.download_data
"""


def _run_kaggle(args: list[str]) -> bool:
    try:
        subprocess.run(
            [sys.executable, "-m", "kaggle", *args],
            check=True,
            cwd=str(DATA_DIR),
        )
        return True
    except (subprocess.CalledProcessError, FileNotFoundError) as exc:
        print(f"kaggle failed: {exc}")
        return False


def _unzip_all() -> None:
    for zpath in DATA_DIR.glob("*.zip"):
        print(f"Extracting {zpath.name}…")
        with zipfile.ZipFile(zpath, "r") as zf:
            zf.extractall(DATA_DIR)


def _hf_download(repo_id: str, filename: str, dest: Path) -> bool:
    try:
        from huggingface_hub import hf_hub_download
    except ImportError:
        print("huggingface_hub not installed — pip install huggingface_hub")
        return False
    try:
        print(f"Downloading {filename} from Hugging Face ({repo_id})…")
        path = hf_hub_download(
            repo_id=repo_id,
            filename=filename,
            repo_type="dataset",
            local_dir=str(DATA_DIR / "_hf_cache"),
        )
        shutil.copy2(path, dest)
        return dest.exists()
    except Exception as exc:
        print(f"HF download failed: {exc}")
        return False


def _hf_export_paysim(dest: Path) -> bool:
    """Load PaySim from HF datasets and write CSV (same schema as Kaggle)."""
    try:
        from datasets import load_dataset
    except ImportError:
        subprocess.run([sys.executable, "-m", "pip", "install", "datasets", "-q"], check=False)
        try:
            from datasets import load_dataset
        except ImportError:
            return False
    try:
        print("Loading PaySim from Hugging Face (purulalwani/…Cleaned)…")
        ds = load_dataset(
            "purulalwani/Synthetic-Financial-Datasets-For-Fraud-Detection-Cleaned",
            split="train",
        )
        # Write in chunks to avoid huge memory peak if possible
        print(f"Writing {len(ds)} rows to {dest}…")
        df = ds.to_pandas()
        # Normalize column names to PaySim originals if cleaned differently
        rename = {}
        for col in df.columns:
            low = col.lower()
            mapping = {
                "step": "step",
                "type": "type",
                "amount": "amount",
                "nameorig": "nameOrig",
                "oldbalanceorg": "oldbalanceOrg",
                "newbalanceorig": "newbalanceOrig",
                "namedest": "nameDest",
                "oldbalancedest": "oldbalanceDest",
                "newbalancedest": "newbalanceDest",
                "isfraud": "isFraud",
                "isflaggedfraud": "isFlaggedFraud",
            }
            if low in mapping:
                rename[col] = mapping[low]
        if rename:
            df = df.rename(columns=rename)
        df.to_csv(dest, index=False)
        return dest.exists()
    except Exception as exc:
        print(f"HF PaySim export failed: {exc}")
        return False


def _find_paysim() -> Path | None:
    if PAYSIM_FILE.exists():
        return PAYSIM_FILE
    matches = list(DATA_DIR.glob("*log*.csv")) + list(DATA_DIR.rglob("PS_*.csv"))
    return matches[0] if matches else None


def main() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    if not IEEE_FILE.exists():
        print("Downloading IEEE-CIS Fraud Detection…")
        ok = _run_kaggle(
            ["competitions", "download", "-c", "ieee-fraud-detection", "-f", "train_transaction.csv"]
        )
        if not ok:
            ok = _run_kaggle(["competitions", "download", "-c", "ieee-fraud-detection"])
        _unzip_all()
        nested = list(DATA_DIR.rglob("train_transaction.csv"))
        if nested and not IEEE_FILE.exists():
            shutil.copy2(nested[0], IEEE_FILE)
        if not IEEE_FILE.exists():
            _hf_download("aliceczr/ieee-fraud-detection", "train_transaction.csv", IEEE_FILE)

    if not IEEE_FILE.exists():
        print(MANUAL)
        sys.exit(1)
    print(f"OK: {IEEE_FILE} ({IEEE_FILE.stat().st_size / 1e6:.1f} MB)")

    paysim = _find_paysim()
    if paysim is None:
        print("Downloading PaySim…")
        ok = _run_kaggle(["datasets", "download", "-d", "ealaxi/paysim1"])
        if not ok:
            ok = _run_kaggle(
                ["datasets", "download", "-d", "rupakroy/online-payments-fraud-detection-dataset"]
            )
        _unzip_all()
        paysim = _find_paysim()
        if paysim is None:
            # HF mirror ships paysim.zip (not a raw CSV)
            zip_dest = DATA_DIR / "paysim.zip"
            if _hf_download("LordNR/AMLGraphX-Paysim", "paysim.zip", zip_dest):
                print("Extracting paysim.zip…")
                with zipfile.ZipFile(zip_dest, "r") as zf:
                    zf.extractall(DATA_DIR / "_paysim_extract")
                found = [
                    p
                    for p in (DATA_DIR / "_paysim_extract").rglob("*.csv")
                    if "__MACOSX" not in p.parts
                ]
                if found:
                    shutil.copy2(found[0], PAYSIM_FILE)
            if not PAYSIM_FILE.exists():
                _hf_export_paysim(PAYSIM_FILE)
            paysim = _find_paysim()

    if paysim is None:
        print(MANUAL)
        sys.exit(1)

    if paysim != PAYSIM_FILE:
        shutil.copy2(paysim, PAYSIM_FILE)
    print(f"OK: {PAYSIM_FILE} ({PAYSIM_FILE.stat().st_size / 1e6:.1f} MB)")
    print("Datasets ready.")


if __name__ == "__main__":
    main()
