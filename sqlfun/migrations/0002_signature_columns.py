from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('sqlfun', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='sqlfundefinition',
            name='identity_arguments',
            field=models.TextField(blank=True, default=''),
        ),
        migrations.AddField(
            model_name='sqlfundefinition',
            name='result_type',
            field=models.TextField(blank=True, default=''),
        ),
    ]
