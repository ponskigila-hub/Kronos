"""
Loads the Kronos tokenizer/model/predictor exactly once and reuses it for
every subsequent forecast request (loading from Hugging Face is the slowest
part of the old scripts, and both yahoopredict.py and csvpredict.py reloaded
it on every run).

Also applies CPU thread limiting for machines with no CUDA/MPS GPU (e.g. an
AMD Radeon iGPU, which torch can't use) -- KronosPredictor auto-detects and
falls back to CPU in that case, and PyTorch's default of using every
available thread can cause more contention/thermal throttling than benefit
on a laptop, especially alongside everything else running (browser, OS,
this Python process itself). Set KRONOS_CPU_THREADS in .env to override; a
good starting point on a 6-core/12-thread CPU with 8GB RAM is 4-6, leaving
headroom for the rest of the system.
"""
import threading

from model import Kronos, KronosTokenizer, KronosPredictor
from .config import KRONOS_MODEL_ID, KRONOS_TOKENIZER_ID, KRONOS_MAX_CONTEXT, KRONOS_CPU_THREADS

_lock = threading.Lock()
_predictor = None


def get_predictor():
    global _predictor
    if _predictor is None:
        with _lock:
            if _predictor is None:  # re-check inside the lock
                if KRONOS_CPU_THREADS:
                    import torch
                    if not torch.cuda.is_available() and not (
                        hasattr(torch.backends, "mps") and torch.backends.mps.is_available()
                    ):
                        torch.set_num_threads(KRONOS_CPU_THREADS)
                tokenizer = KronosTokenizer.from_pretrained(KRONOS_TOKENIZER_ID)
                model = Kronos.from_pretrained(KRONOS_MODEL_ID)
                _predictor = KronosPredictor(
                    model, tokenizer, max_context=KRONOS_MAX_CONTEXT
                )
    return _predictor
