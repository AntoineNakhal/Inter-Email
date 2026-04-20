# Data

This folder is for runtime state in local and self-hosted environments.

Recommended usage:

- `sqlite/`: SQLite database files
- `cache/`: analysis cache and temporary provider outputs
- `exports/`: JSON exports, debugging snapshots, or CRM-ready extracts

Do not place application source code here.

In containers, this folder should normally be mounted as a volume.
