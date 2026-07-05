import random
from pathlib import Path

import numpy as np
import pandas as pd
import torch

from model import Kronos, KronosPredictor, KronosTokenizer


TEST_DATA_ROOT = Path(__file__).parent
INPUT_DATA_PATH = TEST_DATA_ROOT / "regression_input.csv"
OUTPUT_DATA_DIR = TEST_DATA_ROOT
MAX_CTX_LEN = 512
TEST_CTX_LEN = [512, 256]
PRED_LEN = 8
FEATURE_NAMES = ["open", "high", "low", "close", "volume", "amount"]

MODEL_REVISION = "901c26c1332695a2a8f243eb2f37243a37bea320"
TOKENIZER_REVISION = "0e0117387f39004a9016484a186a908917e22426"
SEED = 123

DEVICE = "cpu"


def set_seed(seed: int) -> None:
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    if torch.backends.cudnn.is_available():
        torch.backends.cudnn.deterministic = True
        torch.backends.cudnn.benchmark = False


def generate_output(ctx_len: int) -> None:
    if ctx_len > MAX_CTX_LEN:
        raise ValueError(
            f"Context length for output generation ({ctx_len}) "
            f"cannot exceed maximum context length ({MAX_CTX_LEN})."
        )

    context_df = df.iloc[:ctx_len].copy()
    future_timestamps = df["timestamps"].iloc[
        ctx_len : ctx_len + PRED_LEN
    ].reset_index(drop=True)

    tokenizer = KronosTokenizer.from_pretrained("NeoQuasar/Kronos-Tokenizer-base", revision=TOKENIZER_REVISION)
    model = Kronos.from_pretrained("NeoQuasar/Kronos-small", revision=MODEL_REVISION)
    tokenizer.eval()
    model.eval()

    predictor = KronosPredictor(
        model, tokenizer, device=DEVICE, max_context=MAX_CTX_LEN
    )

    with torch.no_grad():
        pred_df = predictor.predict(
            df=context_df[FEATURE_NAMES].reset_index(drop=True),
            x_timestamp=context_df["timestamps"].reset_index(drop=True),
            y_timestamp=future_timestamps,
            pred_len=PRED_LEN,
            T=1.0,
            top_k=1,
            top_p=1.0,
            verbose=False,
            sample_count=1,
        )

    if pred_df.shape != (PRED_LEN, len(FEATURE_NAMES)):
        raise ValueError(f"Unexpected prediction shape: {pred_df.shape}")

    output_df = pred_df.reset_index(drop=True)
    output_df["timestamps"] = future_timestamps
    output_df = output_df[["timestamps"] + FEATURE_NAMES]
    output_df.to_csv(OUTPUT_DATA_DIR / f"regression_output_{ctx_len}.csv", index=False)
    print(f"Saved {ctx_len} fixture to {OUTPUT_DATA_DIR / f'regression_output_{ctx_len}.csv'}")


if __name__ == "__main__":
    set_seed(SEED)


    df = pd.read_csv(INPUT_DATA_PATH, parse_dates=["timestamps"])
    if df.shape[0] < MAX_CTX_LEN + PRED_LEN:
        raise ValueError(
            f"Input data must have at least {MAX_CTX_LEN + PRED_LEN} rows, "
            f"found {df.shape[0]} instead."
        )

    for ctx_len in TEST_CTX_LEN:
        generate_output(ctx_len)
