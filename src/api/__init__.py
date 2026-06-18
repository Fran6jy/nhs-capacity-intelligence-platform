"""FastAPI backend — serves the NHS platform from PostgreSQL.

The React frontend and any external consumer (Power BI, mobile) talk to this
API; all data access goes through `src.db` (SQLAlchemy/Postgres).
"""
