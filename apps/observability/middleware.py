"""Trace-id middleware for Django requests.

For every Django request:
  • Opens a fresh trace (so log.event calls have somewhere to land)
  • At request-exit, calls log.flush() — writes ONE RequestLog row if the
    request emitted any events. If nothing was logged, no DB write happens.
  • Always resets all observability context so worker thread reuse can't
    leak state between requests.
"""
import time
from apps.observability import context as ctx
from apps.observability import api as log


class TraceContextMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        ctx.new_trace()
        started = time.monotonic()
        try:
            response = self.get_response(request)
            return response
        finally:
            # One row per Django request — but ONLY if anything actually
            # called log.event(). Empty buffer = no DB write.
            try:
                kind = 'webhook' if '/api/webhook/' in request.path else (
                    'admin' if '/admin/' in request.path else 'other'
                )
                # Webhook view flushes itself — we double-protect with
                # idempotent flush (the flushed_var guard makes it a no-op).
                log.flush(
                    request_kind=kind,
                    inbound_text=request.path[:200],
                    latency_ms=int((time.monotonic() - started) * 1000),
                )
            except Exception:
                pass
            ctx.reset()
