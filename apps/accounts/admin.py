from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin

from .models import User


@admin.register(User)
class UserAdmin(DjangoUserAdmin):
    """Same admin as Django's built-in UserAdmin, with a new "Landing page contacts"
    fieldset so the superuser edits their bot_number + contact_number inline."""

    # Reuse UserAdmin's fieldsets and append a new one for our custom fields.
    fieldsets = DjangoUserAdmin.fieldsets + (
        ('Landing page contacts', {
            'fields': ('bot_number', 'contact_number', 'contact_name'),
            'description': (
                "<b>bot_number</b> — Meta WhatsApp number patients message to try the demo "
                "(e.g. <code>15551773718</code>).<br>"
                "<b>contact_number</b> — your personal WhatsApp, shown in the \"Talk to me\" card.<br>"
                "<b>contact_name</b> — first name used in CTA copy (e.g. \"Chat with Aniket\").<br>"
                "Digits only with country code. No + or spaces."
            ),
        }),
    )
    # Same for the "Add user" form so new admins can enter these at creation time.
    add_fieldsets = DjangoUserAdmin.add_fieldsets + (
        ('Landing page contacts (optional)', {
            'classes': ('wide',),
            'fields': ('bot_number', 'contact_number', 'contact_name'),
        }),
    )
    list_display = DjangoUserAdmin.list_display + ('bot_number', 'contact_number')
