from asyncio import Lock

# Candidate scans, tag reconciliation, and file operations must not race each
# other. This is intentionally process-local!
#
# SQLite deployments are restricted to a single MediaMasterr process
candidate_workflow_lock = Lock()
