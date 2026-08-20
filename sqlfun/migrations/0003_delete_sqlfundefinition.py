from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ('sqlfun', '0002_signature_columns'),
    ]

    operations = [
        migrations.DeleteModel(name='SqlFunDefinition'),
    ]
