"""Streamlit Community Cloud entry point.

Cloud runs the app from the repo root, but the package lives under ``src/``. This
shim puts ``src`` on the path and then renders the dashboard. Point the Streamlit
Cloud app at this file (``streamlit_app.py``).

Streamlit re-executes THIS file on every rerun (e.g. each button click), so we must
*call* ``main()`` here every time — not rely on import side effects. A module body
runs only on its first import; importing the app for its side effects rendered the
page once and then left it blank on every rerun (the cached re-import does nothing).
"""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent / "src"))

from job_agent.ui.app import main  # noqa: E402

main()
