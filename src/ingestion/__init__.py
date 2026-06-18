"""Ingestion clients — thin wrappers around real NHS APIs.

Each client returns a pandas DataFrame. When credentials / network are
unavailable the bronze layer falls back to synthetic data.
"""
