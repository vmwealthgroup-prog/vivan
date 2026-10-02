"""
This file contained a hardcoded database password and has been replaced.
The password (psgadmin) must be rotated on the server — removing it from
the code does NOT remove it from git history. Use git filter-repo or BFG
to scrub the history, then rotate the credential on the database server.
Database connections are now managed via backend/app/db.py using an env var.
"""
