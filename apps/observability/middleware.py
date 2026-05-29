"""Trace-id middleware for Django requests.

Sets a fresh trace_id at request-enter, clears all observability context at
request-exit so contextvars don't bleed between requests on the same worker
thread. The webhook receiver sets its own trace + correlation — but for every
OTHER Django request (admin browsing, marketing landing, etc.) this middleware
makes sure the calls still have a trace ID even if they `log.event(...)`.
"""
from apps.observability import context as ctx


class TraceContextMiddleware:
    """Lightweight — single trace_id per request, no DB hit."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        ctx.new_trace()
        try:
            return self.get_response(request)
        finally:
            # Always clear so worker thread reuse doesn't bleed context
            ctx.reset()
