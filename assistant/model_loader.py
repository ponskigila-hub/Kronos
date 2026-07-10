"""
Loads the Kronos tokenizer/model/predictor exactly once and reuses it for
every subsequent forecast request (loading from Hugging Face is the slowest
part of the old scripts, and both yahoopredict.py and csvpredict.py reloaded
it on every run).
"""
import threading

from model import Kronos, KronosTokenizer, KronosPredictor
from .config import KRONOS_MODEL_ID, KRONOS_TOKENIZER_ID, KRONOS_MAX_CONTEXT

_lock = threading.Lock()
_predictor = None


def get_predictor():
    global _predictor
    if _predictor is None:
        with _lock:
            if _predictor is None:  # re-check inside the lock
                tokenizer = KronosTokenizer.from_pretrained(KRONOS_TOKENIZER_ID)
                model = Kronos.from_pretrained(KRONOS_MODEL_ID)
                _predictor = KronosPredictor(
                    model, tokenizer, max_context=KRONOS_MAX_CONTEXT
                )
    return _predictor
