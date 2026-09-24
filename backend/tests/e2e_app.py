"""Playwright-only ASGI entry point with deterministic host resource sampling."""

from backend.app import main
from backend.app.worker import LocalTaskWorker

# Browser acceptance tests exercise task behavior separately from the resource
# thresholds. Resource transitions retain dedicated deterministic unit coverage.
main.worker = LocalTaskWorker(main.database, resource_sampler=lambda: (0.0, 0.0))

app = main.app
