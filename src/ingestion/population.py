"""ONS population estimates client."""
from __future__ import annotations

import pandas as pd


def fetch() -> pd.DataFrame:
    raise NotImplementedError("Plug in ONS API or use the CSV at nomisweb.co.uk.")
