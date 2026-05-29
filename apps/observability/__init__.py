"""DocPing observability — structured logging that lands in stdout AND the DB.

Quick start:
    from apps.observability import log

    log.event('something_happened', key=value, message='one-line summary')
    log.warn('user_input_rejected', input=text)
    log.error('something_blew_up', exc=e)

    with log.span('expensive_op') as s:
        ...
        s.data['result_count'] = n

Trace propagation:
    from apps.observability.context import new_trace, set_correlation
    new_trace()
    set_correlation(whatsapp_number=phone, clinic_id=clinic.id)
"""
default_app_config = 'apps.observability.apps.ObservabilityConfig'


def __getattr__(name):
    """Lazy: `from apps.observability import log` works without forcing app load."""
    if name == 'log':
        from apps.observability import api as _log
        return _log
    raise AttributeError(name)
