"""Launch Streamlit on Windows / Unix."""
#!/usr/bin/env bash
set -e
cd "$(dirname "$0")/.."
streamlit run src/dashboard/app.py --server.port 8501
