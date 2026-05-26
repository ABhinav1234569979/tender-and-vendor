import sqlite3, sys
sys.path.insert(0, '.')
from src.utils.paths import PROJECT_ROOT
db = str(PROJECT_ROOT / 'data' / 'parsed' / 'app.db')
conn = sqlite3.connect(db)
rows = conn.execute(
    "SELECT spec_id, vendor_id, status, citation_page, reasoning FROM compliance_matrix WHERE vendor_id='Alstonia-merged' LIMIT 10"
).fetchall()
for r in rows:
    print(r)
conn.close()
