"""
Gunicorn production server configuration for Finora Financial Reconciliation Engine.
Runs Uvicorn worker class with concurrency, worker recycling, and graceful timeouts.
"""

import multiprocessing
import os

# Server socket
bind = os.environ.get("BIND", "0.0.0.0:8000")
backlog = 2048

# Worker processes
# For compute-heavy reconciliation and IO bound requests: 2 * CPUs + 1
workers = int(os.environ.get("WEB_CONCURRENCY", multiprocessing.cpu_count() * 2 + 1))
worker_class = "uvicorn.workers.UvicornWorker"
worker_connections = 1000
timeout = int(os.environ.get("TIMEOUT", 120))
keepalive = 5

# Worker lifecycle and memory protection
max_requests = 2000
max_requests_jitter = 200
graceful_timeout = 30

# Logging
loglevel = os.environ.get("LOG_LEVEL", "info")
accesslog = "-"
errorlog = "-"
access_log_format = '%(h)s %(l)s %(u)s %(t)s "%(r)s" %(s)s %(b)s "%(f)s" "%(a)s" (%(D)s µs)'
