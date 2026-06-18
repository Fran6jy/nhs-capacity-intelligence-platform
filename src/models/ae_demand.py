"""A&E demand forecaster — Prophet handles strong daily/weekly seasonality."""
from __future__ import annotations

import pandas as pd
from prophet import Prophet

from src.utils.logging import get_logger

log = get_logger("models.ae_demand")


class AEDemandForecaster:
    def __init__(self, horizon_days: int = 90) -> None:
        self.horizon_days = horizon_days
        self._m: Prophet | None = None

    def fit(self, df: pd.DataFrame, target: str = "ae_attendances") -> None:
        daily = (
            df.groupby("date_key", as_index=False)[target].sum()
            .rename(columns={"date_key": "ds", target: "y"})
        )
        daily["ds"] = pd.to_datetime(daily["ds"])
        m = Prophet(
            weekly_seasonality=True,
            yearly_seasonality=True,
            changepoint_prior_scale=0.05,
        )
        m.add_country_holidays(country_name="UK")
        m.fit(daily)
        self._m = m
        log.info("ae.fit", rows=len(daily))

    def forecast(self) -> pd.DataFrame:
        if self._m is None:
            raise RuntimeError("Model has not been fit()")
        future = self._m.make_future_dataframe(periods=self.horizon_days)
        fc = self._m.predict(future)
        fc["date_key"] = pd.to_datetime(fc["ds"])
        return fc[["date_key", "yhat", "yhat_lower", "yhat_upper"]]
