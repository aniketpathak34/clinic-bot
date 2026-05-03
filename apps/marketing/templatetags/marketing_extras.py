from django import template

register = template.Library()


@register.filter
def pretty_phone(value):
    """Format an Indian phone number stored as digits-only with country code
    (e.g. '917020162229') into a compact display form: '+91 70201 62229'.

    Falls back to '+<value>' if the input doesn't match the expected shape.
    """
    if not value:
        return ''
    digits = ''.join(ch for ch in str(value) if ch.isdigit())
    if len(digits) == 12 and digits.startswith('91'):
        local = digits[2:]
        return f"+91 {local[:5]} {local[5:]}"
    if len(digits) == 10:
        return f"+91 {digits[:5]} {digits[5:]}"
    return f"+{digits}" if digits else str(value)
