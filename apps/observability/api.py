"""Structured logging API — one row per request, events buffered as JSON.

Usage at call sites stays the same as before:

    from apps.observability import log

    log.event('webhook_received', sender_digit10=p[-10:])
    log.warn('match_failed', input=text)
    log.error('save_failed', exc=e, doctor_id=d.pk)

What changed under the hood:
  • log.event() now APPENDS to a per-trace event buffer + emits to stdout.
    Nothing hits the DB yet.
  • log.flush(inbound_text=..., request_kind='webhook') at request-end
    consumes the buffer and writes ONE RequestLog row.
  • The webhook view + the middleware call log.flush() automatically.

The trade:
  ‒ 5× less DB churn (1 INSERT per request, not 5)
  ‒ Clinic admins see ONE row per webhook in /admin/observability/requestlog/
  + Full breadcrumb still preserved in the row's `events` JSON field
"""
import logging
import sys
import time
import traceback as tb_mod
from typing import Optional

from apps.observability import context as ctx


_stdout_logger = logging.getLogger('docping.observability')


# ─── Level math ─────────────────────────────────────────────────────
_LEVEL_RANK = {'debug': 0, 'info': 1, 'warn': 2, 'error': 3, 'critical': 4}


def _rank(level: str) -> int:
    return _LEVEL_RANK.get(level, 1)


# ─── Phone number masking ────────────────────────────────────────────
def _mask_phone(wa: Optional[str]) -> str:
    if not wa:
        return ''
    digits = ''.join(c for c in wa if c.isdigit())
    return wa if len(digits) < 4 else f'…{digits[-4:]}'


# ─── Stdout emission ─────────────────────────────────────────────────
def _to_stdout(level: str, payload: dict) -> None:
    """Always emit immediately — gives the Render log shell a real-time view
    even before flush() writes the consolidated row."""
    bits = [
        f'[obs]',
        f'event={payload.get("event", "?")}',
        f'level={level}',
        f'trace={payload.get("trace_id") or "-"}',
    ]
    wa = payload.get('whatsapp_number')
    if wa:
        bits.append(f'wa={_mask_phone(wa)}')
    for key in ('clinic_id', 'user_type', 'flow', 'step'):
        v = payload.get(key)
        if v:
            bits.append(f'{key}={v}')
    msg = payload.get('message')
    if msg:
        s = str(msg).replace('"', "'")[:160]
        bits.append(f'msg="{s}"')
    data = payload.get('data') or {}
    for k, v in list(data.items())[:8]:
        s = str(v).replace('\n', '\\n').replace('"', "'")
        if len(s) > 60:
            s = s[:57] + '...'
        if any(c in s for c in ' \t='):
            s = f'"{s}"'
        bits.append(f'{k}={s}')
    if payload.get('exc_type'):
        bits.append(f'exc={payload["exc_type"]}')
    if payload.get('latency_ms') is not None:
        bits.append(f'lat={payload["latency_ms"]}ms')

    line = ' '.join(bits)
    {
        'debug':    _stdout_logger.debug,
        'info':     _stdout_logger.info,
        'warn':     _stdout_logger.warning,
        'error':    _stdout_logger.error,
        'critical': _stdout_logger.critical,
    }.get(level, _stdout_logger.info)(line)


# ─── Caller introspection ────────────────────────────────────────────
def _caller_source() -> str:
    """Module:function of the first caller outside apps.observability."""
    try:
        depth = 1
        while True:
            frame = sys._getframe(depth)
            mod = frame.f_globals.get('__name__', '')
            if not mod.startswith('apps.observability'):
                if mod.startswith('apps.'):
                    mod = mod[len('apps.'):]
                return f'{mod}:{frame.f_code.co_name}'
            depth += 1
    except (ValueError, AttributeError):
        return ''


# ─── Public API ──────────────────────────────────────────────────────
def event(name: str, *, level: str = 'info',
          message: str = '', exc: Optional[BaseException] = None,
          **data) -> None:
    """Append one structured event to the per-trace buffer + emit stdout."""
    snap = ctx.snapshot()
    payload = {
        'event':           name,
        'level':           level,
        'message':         message,
        'data':            data or {},
        'source':          _caller_source(),
        'trace_id':        snap['trace_id'] or '',
        'clinic_id':       snap['clinic_id'],
        'whatsapp_number': snap['whatsapp_number'] or '',
        'user_type':       snap['user_type'] or '',
        'flow':            snap['flow'] or '',
        'step':            snap['step'] or '',
    }
    if exc is not None:
        payload['exc_type']    = type(exc).__name__
        payload['exc_message'] = str(exc)[:500]
        payload['traceback']   = tb_mod.format_exc()

    _to_stdout(level, payload)

    # Append to the per-trace buffer if there's one open. If there's no buffer
    # (we're outside a trace context — e.g. management command without
    # new_trace()), stdout is the only sink. That's fine.
    buf = ctx.events_buffer_var.get()
    if buf is not None:
        buf.append({
            'ts':       time.time(),
            'event':    name,
            'level':    level,
            'source':   payload['source'],
            'message':  message,
            'data':     data or {},
            'flow':     payload['flow'],
            'step':     payload['step'],
            'exc_type':    payload.get('exc_type', ''),
            'exc_message': payload.get('exc_message', ''),
            'traceback':   payload.get('traceback', ''),
        })


def debug(name: str, **kw) -> None:    event(name, level='debug', **kw)
def info(name: str, **kw) -> None:     event(name, level='info', **kw)
def warn(name: str, **kw) -> None:     event(name, level='warn', **kw)
def warning(name: str, **kw) -> None:  event(name, level='warn', **kw)
def error(name: str, **kw) -> None:    event(name, level='error', **kw)
def critical(name: str, **kw) -> None: event(name, level='critical', **kw)


# ─── Span context manager — appends 2 events to the same buffer ────
class _Span:
    __slots__ = ('name', 'level', 'data', '_start', '_failed')

    def __init__(self, name: str, level: str = 'info', **data):
        self.name = name
        self.level = level
        self.data = dict(data)
        self._start = 0.0
        self._failed = False

    def __enter__(self):
        self._start = time.monotonic()
        event(f'{self.name}_started', level=self.level, **self.data)
        return self

    def __exit__(self, exc_type, exc, tb):
        lat = int((time.monotonic() - self._start) * 1000)
        if exc is not None:
            self._failed = True
            event(f'{self.name}_failed', level='error', exc=exc,
                  latency_ms=lat, **self.data)
        else:
            event(f'{self.name}_completed', level=self.level,
                  latency_ms=lat, **self.data)
        return False


def span(name: str, *, level: str = 'info', **data) -> _Span:
    return _Span(name, level=level, **data)


# ─── flush — the one DB write per request ────────────────────────────
def flush(*, request_kind: str = 'webhook',
          inbound_text: str = '', summary: str = '',
          latency_ms: Optional[int] = None,
          force: bool = False) -> None:
    """Consume the per-trace event buffer and write ONE RequestLog row.

    Idempotent — second call within the same trace is a no-op unless `force`.
    NEVER raises — failures fall back to stderr so the webhook still returns 200.
    Skips writing if the buffer is empty (nothing happened worth recording).
    """
    if ctx.flushed_var.get() and not force:
        return
    buf = ctx.events_buffer_var.get()
    if not buf:
        # Mark flushed so a follow-up middleware call doesn't try again
        ctx.flushed_var.set(True)
        return

    snap = ctx.snapshot()

    # Roll-ups
    event_count = len(buf)
    warn_count = sum(1 for e in buf if e['level'] == 'warn')
    error_count = sum(1 for e in buf if e['level'] in ('error', 'critical'))

    max_level = 'info'
    for e in buf:
        if _rank(e['level']) > _rank(max_level):
            max_level = e['level']

    # Promote the FIRST error's exception details to top-level columns
    exc_type = exc_message = traceback = ''
    for e in buf:
        if e['level'] in ('error', 'critical') and e['exc_type']:
            exc_type = e['exc_type']
            exc_message = e['exc_message']
            traceback = e['traceback']
            break

    # Most meaningful final event — last non-debug event
    final_event = ''
    final_flow = snap['flow'] or ''
    final_step = snap['step'] or ''
    for e in reversed(buf):
        if e['level'] != 'debug':
            final_event = e['event']
            final_flow = e['flow'] or final_flow
            final_step = e['step'] or final_step
            break

    # Auto-summary: first error message OR last meaningful message
    if not summary:
        if error_count:
            summary = next((e['message'] for e in buf
                            if e['level'] in ('error', 'critical') and e['message']), '')
        if not summary:
            for e in reversed(buf):
                if e.get('message') and e['level'] != 'debug':
                    summary = e['message']
                    break

    try:
        from apps.observability.models import RequestLog
        kwargs = {
            'trace_id':        snap['trace_id'] or '',
            'request_kind':    request_kind,
            'level':           max_level,
            'whatsapp_number': snap['whatsapp_number'] or '',
            'user_type':       snap['user_type'] or '',
            'final_flow':      final_flow,
            'final_step':      final_step,
            'final_event':     final_event,
            'inbound_text':    (inbound_text or '')[:200],
            'summary':         (summary or '')[:1000],
            'event_count':     event_count,
            'warn_count':      warn_count,
            'error_count':     error_count,
            'events':          buf,
            'exc_type':        exc_type,
            'exc_message':     exc_message,
            'traceback':       traceback,
            'latency_ms':      latency_ms,
        }
        if snap['clinic_id'] is not None:
            kwargs['clinic_id'] = snap['clinic_id']

        try:
            RequestLog.objects.create(**kwargs)
        except Exception:
            # Stale clinic FK against this DB → retry without it
            kwargs.pop('clinic_id', None)
            RequestLog.objects.create(**kwargs)
    except Exception as e:
        sys.stderr.write(
            f'[obs] FLUSH_FAILED err={type(e).__name__}: {e} '
            f'events={len(buf)} trace={snap["trace_id"]}\n'
        )
    finally:
        ctx.flushed_var.set(True)
        # Drain so a second flush() can't double-write
        ctx.events_buffer_var.set([])


__all__ = ['event', 'debug', 'info', 'warn', 'warning',
           'error', 'critical', 'span', 'flush']
