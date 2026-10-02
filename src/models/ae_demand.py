"""A&E demand forecaster.

Prophet on the national daily total. Strong weekly seasonality is the dominant
structure in A&E attendances, which Prophet handles well; yearly seasonality is
enabled only once the series has seen two full years, because an annual
Fourier series fitted to six months is noise that extrapolates confidently.

Intervals are Prophet's own, which are derived from its posterior over trend
changes rather than a fixed multiplier.
"""
from __future__ import annotations

import pandas as pd
from prophet import Prophet

from src.models._common import yearly_seasonality_for
from src.utils.logging import get_logger

log = get_logger("models.ae_demand")


class AEDemandForecaster:
    def __init__(self, horizon_days: int = 90) -> None:
        self.horizon_days = horizon_days
        self._m: Prophet | None = None
        self.yearly_seasonality: bool = False

    @staticmethod
    def national_daily(df: pd.DataFrame, target: str) -> pd.DataFrame:
        daily = (
            df.groupby("date_key", as_index=False)[target].sum()
            .rename(columns={"date_key": "ds", target: "y"})
        )
        daily["ds"] = pd.to_datetime(daily["ds"])
        return daily.sort_values("ds").reset_index(drop=True)

    def fit(self, df: pd.DataFrame, target: str = "ae_attendances") -> None:
        daily = self.national_daily(df, target)
        self.yearly_seasonality = yearly_seasonality_for(daily["ds"])
        m = Prophet(
            weekly_seasonality=True,
            yearly_seasonality=self.yearly_seasonality,
            changepoint_prior_scale=0.05,
        )
        m.add_country_holidays(country_name="UK")
        m.fit(daily)
        self._m = m
        log.info("ae.fit", days=len(daily), yearly=self.yearly_seasonality)

    def forecast(self) -> pd.DataFrame:
        if self._m is None:
            raise RuntimeError("Model has not been fit()")
        future = self._m.make_future_dataframe(periods=self.horizon_days, include_history=False)
        fc = self._m.predict(future)
        fc["date_key"] = pd.to_datetime(fc["ds"])
        return fc[["date_key", "yhat", "yhat_lower", "yhat_upper"]]
