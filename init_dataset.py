"""Create a Phoenix Dataset for the self-healing agent's demo task.

Idempotent — re-running just confirms the dataset already exists. The dataset
contains one row: the 40-number statistics task + ground-truth expected output.

Run:  .venv/bin/python init_dataset.py     (or: make dataset)
"""
import os
from dotenv import load_dotenv
load_dotenv()

from phoenix.client import Client

NAME = "self-healing-stats"
DATA = [12, 7, 22, 9, 14, 31, 5, 18, 27, 3, 19, 44, 8, 16, 25, 11, 38, 6, 21, 13,
        29, 2, 17, 33, 10, 24, 41, 4, 15, 28, 36, 1, 20, 23, 39, 7, 30, 18, 26, 9]
EXPECTED = {"mean": 19.02, "population_std": 11.57, "median": 18.0}

px = Client(
    base_url=os.environ["PHOENIX_COLLECTOR_ENDPOINT"],
    api_key=os.environ["PHOENIX_API_KEY"],
)

try:
    existing = px.datasets.get_dataset(dataset=NAME)
    print(f"✅ Dataset {NAME!r} already exists — nothing to do.")
except Exception:
    px.datasets.create_dataset(
        name=NAME,
        examples=[{
            "input":  {"data": DATA},
            "output": EXPECTED,
            "metadata": {
                "trap": "numpy_not_installed",
                "description": "Compute mean, population std, median; numpy will fail in the sandbox so the agent must use the standard library.",
            },
        }],
    )
    print(f"✅ Created dataset {NAME!r} (1 row, ground-truth = {EXPECTED}).")
