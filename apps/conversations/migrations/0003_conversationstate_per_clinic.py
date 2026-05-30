"""Make ConversationState per-clinic instead of per-phone.

Drops the column-level unique on whatsapp_number, adds a composite
UniqueConstraint on (whatsapp_number, clinic). Includes a defensive
data-migration step that deduplicates any existing rows that would
collide on the new key — keeps the most recently updated row.
"""
from collections import defaultdict

from django.db import migrations, models


def deduplicate_states(apps, schema_editor):
    """If two rows share (whatsapp_number, clinic_id), keep the newest.

    Under the OLD constraint (whatsapp_number alone is unique), this should
    never happen — but we check defensively in case a prior migration or
    manual DB edit left stale rows. Without this step, the AddConstraint
    operation below would crash with IntegrityError on any duplicate.
    """
    ConversationState = apps.get_model('conversations', 'ConversationState')

    groups = defaultdict(list)
    for row in ConversationState.objects.all().order_by('-updated_at'):
        key = (row.whatsapp_number, row.clinic_id)
        groups[key].append(row)

    deleted = 0
    for key, rows in groups.items():
        if len(rows) <= 1:
            continue
        keep = rows[0]
        for r in rows[1:]:
            print(
                f'  [dedupe] (wa={key[0]}, clinic_id={key[1]}): '
                f'deleting id={r.pk} (updated {r.updated_at}); '
                f'keeping id={keep.pk} (updated {keep.updated_at})'
            )
            r.delete()
            deleted += 1

    if deleted:
        print(f'  [dedupe] Deleted {deleted} duplicate ConversationState row(s).')
    else:
        print('  [dedupe] No duplicates found — clean state.')


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('conversations', '0002_conversationstate_clinic'),
        ('clinic', '0007_messagetemplate'),
    ]

    operations = [
        # 1. Defensive: clear any duplicate (wa, clinic) rows BEFORE altering
        migrations.RunPython(deduplicate_states, noop_reverse),

        # 2. Drop the column-level unique on whatsapp_number, add db_index
        migrations.AlterField(
            model_name='conversationstate',
            name='whatsapp_number',
            field=models.CharField(db_index=True, max_length=15),
        ),

        # 3. Add the composite unique constraint
        migrations.AddConstraint(
            model_name='conversationstate',
            constraint=models.UniqueConstraint(
                fields=['whatsapp_number', 'clinic'],
                name='uniq_convstate_phone_clinic',
            ),
        ),
    ]
