"""Workforce forecaster: national vacancy rate.

This replaces a model that was not a forecast. The previous
``WorkforceDemandModel`` trained and predicted on the *same single-day
snapshot* of the workforce table. With one date, every lag feature was NaN
(filled to zero) and the regressor simply learned ``staff_count`` from
``role_code`` — it predicted its own input, and the "60-day demand forecast"
written to the warehouse was that input with a ±5% band drawn around it.

The fact table carries a daily vacancy rate per trust, which is a genuine time
series. Forecasting its national mean with Prophet is modest, but it is real:
it answers "where is the vacancy rate heading" rather than restating today's
number.
"""
from __future__ import annotations

import pandas as pd
from prophet import Prophet

from src.models._common import yearly_seasonality_for
from src.utils.logging import get_logger

log = get_logger("models.workforce")


class VacancyRateForecaster:
    def __init__(self, horizon_days: int = 90) -> None:
        self.horizon_days = horizon_days
        self._m: Prophet | None = None
        self.yearly_seasonality: bool = False

    @staticmethod
    def national_daily(df: pd.DataFrame, target: str = "vacancy_rate") -> pd.DataFrame:
        daily = (
            df.groupby("date_key", as_index=False)[target].mean()
            .rename(columns={"date_key": "ds", target: "y"})
            .dropna()
        )
        daily["ds"] = pd.to_datetime(daily["ds"])
        return daily.sort_values("ds").reset_index(drop=True)

    def fit(self, df: pd.DataFrame, target: str = "vacancy_rate") -> None:
        daily = self.national_daily(df, target)
        self.yearly_seasonality = yearly_seasonality_for(daily["ds"])
        # Vacancy rates move slowly: damp the trend's willingness to change.
        m = Prophet(
            weekly_seasonality=False,
            yearly_seasonality=self.yearly_seasonality,
            changepoint_prior_scale=0.02,
        )
        m.fit(daily)
        self._m = m
        log.info("workforce.fit", days=len(daily), yearly=self.yearly_seasonality)

    def forecast(self) -> pd.DataFrame:
        if self._m is None:
            raise RuntimeError("Model has not been fit()")
        future = self._m.make_future_dataframe(periods=self.horizon_days, include_history=False)
        fc = self._m.predict(future)
        fc["date_key"] = pd.to_datetime(fc["ds"])
        return fc[["date_key", "yhat", "yhat_lower", "yhat_upper"]]
