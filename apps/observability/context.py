"""Context propagation for observability.

The same trace_id flows through every event for one inbound webhook (or one
Celery task run). We use Python's contextvars module — set once at the
entrypoint, available everywhere downstream without passing a request object
through every function signature.

Usage in entrypoints (webhook receiver, Celery task):

    from apps.observability.context import new_trace, set_correlation
    new_trace()
    set_correlation(whatsapp_number=phone, clinic_id=clinic.id)

Usage in middle layers (just call `log.event(...)` — context picked up automatically).
"""
from contextvars import ContextVar
from uuid import uuid4
from typing import Optional, List, Dict, Any


# Top-level trace ID — one per inbound request / task run
trace_id_var: ContextVar[Optional[str]] = ContextVar('docping_trace_id', default=None)

# Correlation keys — set incrementally as we learn them
clinic_id_var:   ContextVar[Optional[int]] = ContextVar('docping_clinic_id',   default=None)
whatsapp_var:    ContextVar[Optional[str]] = ContextVar('docping_whatsapp',    default=None)
user_type_var:   ContextVar[Optional[str]] = ContextVar('docping_user_type',   default=None)
flow_var:        ContextVar[Optional[str]] = ContextVar('docping_flow',        default=None)
step_var:        ContextVar[Optional[str]] = ContextVar('docping_step',        default=None)

# Per-request event buffer. log.event() appends; log.flush() consumes it and
# writes ONE RequestLog row. Set to None outside a request → buffering off.
events_buffer_var: ContextVar[Optional[List[Dict[str, Any]]]] = ContextVar(
    'docping_events_buffer', default=None,
)

# Marks whether log.flush() has already run for this trace — prevents
# double-writes if a middleware and a view both try to flush.
flushed_var: ContextVar[bool] = ContextVar('docping_flushed', default=False)


def new_trace(parent: Optional[str] = None) -> str:
    """Start a new trace context. Returns the trace ID.

    Also clears all OTHER correlation vars so a fresh trace doesn't inherit
    stale state from the previous request/task on the same worker thread.
    The webhook / engine will repopulate them as soon as they're known.

    Resets the events buffer to an empty list — buffering ON for this trace.
    """
    tid = parent or uuid4().hex[:16]
    trace_id_var.set(tid)
    clinic_id_var.set(None)
    whatsapp_var.set(None)
    user_type_var.set(None)
    flow_var.set(None)
    step_var.set(None)
    events_buffer_var.set([])
    flushed_var.set(False)
    return tid


def current_trace() -> Optional[str]:
    """Return the current trace ID, or None if outside a trace context."""
    return trace_id_var.get()


def set_correlation(*, clinic_id=None, whatsapp_number=None,
                    user_type=None, flow=None, step=None) -> None:
    """Set one or more correlation keys. Pass None to leave a key unchanged."""
    if clinic_id is not None:
        clinic_id_var.set(clinic_id)
    if whatsapp_number is not None:
        whatsapp_var.set(whatsapp_number)
    if user_type is not None:
        user_type_var.set(user_type)
    if flow is not None:
        flow_var.set(flow)
    if step is not None:
        step_var.set(step)


def snapshot() -> dict:
    """Read every correlation key in one go. Used by log.event()."""
    return {
        'trace_id':        trace_id_var.get(),
        'clinic_id':       clinic_id_var.get(),
        'whatsapp_number': whatsapp_var.get(),
        'user_type':       user_type_var.get(),
        'flow':            flow_var.get(),
        'step':            step_var.get(),
    }


def reset() -> None:
    """Clear all context. Called between Celery task runs to avoid bleed."""
    trace_id_var.set(None)
    clinic_id_var.set(None)
    whatsapp_var.set(None)
    user_type_var.set(None)
    flow_var.set(None)
    step_var.set(None)
    events_buffer_var.set(None)
    flushed_var.set(False)
