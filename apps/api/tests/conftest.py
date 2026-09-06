import os

# Configure the default engine before test modules import app.db. Individual
# database tests create their own SQLite files under pytest's tmp_path.
os.environ["DATABASE_URL"] = "sqlite:///:memory:"

# Never send production heartbeats from tests, even if local .env enables them.
for name in ("COLLECTING", "PUBLISHING", "BACKUP"):
    os.environ[f"HEALTHCHECKS_{name}_URL"] = ""
