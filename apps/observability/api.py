"""Structured logging API — the single entry point used by every layer.

Import once, call everywhere:

    from apps.observability import log

    log.event('webhook_received', message_id=mid, sender_digit10=p[-10:])
    log.warn('match_failed', input=text, expected_sample=opts[:5])
    log.error('slot_save_failed', exc=e, doctor_id=d.pk)

    with log.span('send_message', recipient_digit10=p[-10:]) as span:
        result = service.send_message(p, body)
        span.data['meta_message_id'] = result.get('id')

Every call:
  • Writes a row to LogEvent (best-effort — never crashes the caller)
  • Mirrors to stdout via the standard `logging` module so Render captures it
  • Auto-fills trace_id, clinic, whatsapp_number, user_type, flow, step
    from contextvars set at the entrypoint — no plumbing required
"""
import logging
import sys
import time
import traceback as tb_mod
from contextlib import contextmanager
from typing import Optional

from apps.observability import context as ctx


_stdout_logger = logging.getLogger('docping.observability')


# ─── Phone number masking ────────────────────────────────────────────
def _mask_phone(wa: Optional[str]) -> str:
    """Stdout-safe phone rendering — never expose the full number in stdout
    logs that Render keeps for 30 days. Last 4 digits are enough for grepping
    one user without leaking a complete identifier."""
    if not wa:
        return ''
    digits = ''.join(c for c in wa if c.isdigit())
    if len(digits) < 4:
        return wa
    return f'…{digits[-4:]}'


# ─── Stdout emission ─────────────────────────────────────────────────
def _to_stdout(level: str, payload: dict) -> None:
    """Emit a single grep-friendly line to stdout. Format:

      [obs] event=X level=Y trace=Z wa=…1234 clinic_id=2 flow=F step=S key=val ...
    """
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
    for k, v in list(data.items())[:10]:  # cap to keep line readable
        s = str(v).replace('\n', '\\n').replace('"', "'")
        if len(s) > 60:
            s = s[:57] + '...'
        if any(c in s for c in ' \t='):
            s = f'"{s}"'
        bits.append(f'{k}={s}')

    exc = payload.get('exc_type')
    if exc:
        bits.append(f'exc={exc}')

    lat = payload.get('latency_ms')
    if lat is not None:
        bits.append(f'lat={lat}ms')

    line = ' '.join(bits)
    log_fn = {
        'debug':    _stdout_logger.debug,
        'info':     _stdout_logger.info,
        'warn':     _stdout_logger.warning,
        'error':    _stdout_logger.error,
        'critical': _stdout_logger.critical,
    }.get(level, _stdout_logger.info)
    log_fn(line)


# ─── DB emission ─────────────────────────────────────────────────────
def _to_db(level: str, payload: dict) -> None:
    """Insert one LogEvent row. NEVER raises — falls back to stderr if DB is
    down so the webhook still returns 200 to Meta. If the clinic FK is
    pointing at a row that doesn't exist (rare — local-dev vs prod skew),
    retry without the FK so we don't lose the log."""
    try:
        from apps.observability.models import LogEvent

        clean = {k: v for k, v in payload.items() if v is not None}
        clean['data'] = clean.get('data') or {}
        clean['level'] = level

        try:
            LogEvent.objects.create(**clean)
        except Exception as first_err:
            # Most common failure: clinic_id pointing at a Clinic row that
            # doesn't exist in this DB. Drop the FK and try again so the
            # event lands at all.
            if 'clinic_id' in clean:
                clean.pop('clinic_id', None)
                try:
                    LogEvent.objects.create(**clean)
                    return
                except Exception:
                    pass
            raise first_err
    except Exception as e:
        sys.stderr.write(f'[obs] LOG_DB_WRITE_FAILED err={type(e).__name__}: {e}\n')


# ─── Caller introspection ────────────────────────────────────────────
def _caller_source() -> str:
    """Return "module.path:function" of the first caller OUTSIDE this module.
    Walks up the stack until it leaves apps.observability, so wrapper helpers
    like `warn()` or context-manager `__exit__` don't show up as the source.
    """
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
    """Emit one structured event. All kwargs except `level`, `message`, `exc`
    are attached to the JSON `data` field."""
    snap = ctx.snapshot()
    payload = {
        'event':           name,
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
    _to_db(level, payload)


def debug(name: str, **kw) -> None:
    event(name, level='debug', **kw)


def info(name: str, **kw) -> None:
    event(name, level='info', **kw)


def warn(name: str, **kw) -> None:
    event(name, level='warn', **kw)


def warning(name: str, **kw) -> None:  # alias
    event(name, level='warn', **kw)


def error(name: str, **kw) -> None:
    event(name, level='error', **kw)


def critical(name: str, **kw) -> None:
    event(name, level='critical', **kw)


# ─── Span context manager ────────────────────────────────────────────
class _Span:
    """Lightweight span — emits two events bracketing a code block, with
    latency in ms attached to the close event.

        with log.span('send_message', recipient=p) as span:
            result = service.send_message(p, body)
            span.data['meta_id'] = result['id']
    """
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
            event(f'{self.name}_failed', level='error',
                  exc=exc, latency_ms=lat, **self.data)
        else:
            event(f'{self.name}_completed', level=self.level,
                  latency_ms=lat, **self.data)
        return False  # never suppress


def span(name: str, *, level: str = 'info', **data) -> _Span:
    return _Span(name, level=level, **data)


# ─── For tests / shell ───────────────────────────────────────────────
__all__ = ['event', 'debug', 'info', 'warn', 'warning',
           'error', 'critical', 'span']
