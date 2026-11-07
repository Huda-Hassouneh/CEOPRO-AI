"""Heavy work run outside the API process.

The API only describes a task (``kind`` + JSON ``params``) and sends it to a
separate processor service (``processor.py``) over signed HTTPS. The
processor runs each task in its own short-lived child process, so neither a
slow task nor one that runs out of memory can reach the API. Identical tasks
share one job id (``protocol.job_key``): a retry, a double click or two
companies asking the same question run the work once and read the same
result.
"""
