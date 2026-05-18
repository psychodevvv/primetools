from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0001_initial'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='customer',
            name='password_hash',
        ),
        migrations.AlterField(
            model_name='customer',
            name='last_name',
            field=models.CharField(blank=True, max_length=100),
        ),
        migrations.AlterModelOptions(
            name='customer',
            options={'ordering': ['-created_at'],
                     'verbose_name': 'Покупатель',
                     'verbose_name_plural': 'Покупатели'},
        ),
    ]
