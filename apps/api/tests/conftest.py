import os

# Configure the default engine before test modules import app.db. Individual
# database tests create their own SQLite files under pytest's tmp_path.
os.environ["DATABASE_URL"] = "sqlite:///:memory:"
