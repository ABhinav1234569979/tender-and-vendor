"""Clear any stale running/queued pipeline runs from the DB."""
import sys
sys.path.insert(0, '.')
from src.storage.db import get_connection
from src.utils.paths import PROJECT_ROOT

db = str(PROJECT_ROOT / 'data' / 'parsed' / 'app.db')
conn = get_connection(db)
conn.execute(
    "UPDATE pipeline_runs SET status='failed', message='Interrupted — server restarted', "
    "updated_at=CURRENT_TIMESTAMP WHERE status IN ('running','queued')"
)
conn.commit()
rows = conn.execute("SELECT run_id, status FROM pipeline_runs WHERE status IN ('running','queued')").fetchall()
print(f"Remaining active runs: {rows}")
print("Done — stale runs cleared.")
conn.close()
