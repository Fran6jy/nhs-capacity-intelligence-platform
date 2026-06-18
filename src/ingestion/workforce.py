"""NHS Digital Workforce Statistics client."""
from __future__ import annotations

import pandas as pd


def fetch() -> pd.DataFrame:
    raise NotImplementedError("Plug in NHS Digital WFS credentials to use live data.")
