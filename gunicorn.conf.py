"""
Gunicorn configuration for production deployment.

Usage:
    gunicorn -c gunicorn.conf.py "run:app"
"""

import multiprocessing
import os

# ── Binding ───────────────────────────────────────────────────────────────────
bind = f"0.0.0.0:{os.environ.get('PORT', '8000')}"

# ── Workers ───────────────────────────────────────────────────────────────────
# Rule of thumb: (2 × CPU cores) + 1
workers = int(os.environ.get('WEB_CONCURRENCY', multiprocessing.cpu_count() * 2 + 1))
worker_class = 'sync'
worker_connections = 1000
timeout = 120
keepalive = 5

# ── Logging ───────────────────────────────────────────────────────────────────
accesslog = '-'          # stdout
errorlog  = '-'          # stderr
loglevel  = os.environ.get('LOG_LEVEL', 'info').lower()
access_log_format = '%(h)s %(l)s %(u)s %(t)s "%(r)s" %(s)s %(b)s "%(f)s" "%(a)s" %(D)sµs'

# ── Process naming ────────────────────────────────────────────────────────────
proc_name = 'tender_portal'

# ── Security ──────────────────────────────────────────────────────────────────
limit_request_line   = 4094
limit_request_fields = 100
forwarded_allow_ips  = '*'   # Set to your load-balancer IP in production

# ── Lifecycle hooks ───────────────────────────────────────────────────────────
def on_starting(server):
    server.log.info("Starting Gov Tender Portal")

def worker_exit(server, worker):
    server.log.info(f"Worker {worker.pid} exited")
