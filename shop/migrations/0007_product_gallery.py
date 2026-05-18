from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('shop', '0006_category_parent'),
    ]

    operations = [
        migrations.AddField(
            model_name='product',
            name='gallery',
            field=models.TextField(blank=True),
        ),
    ]
