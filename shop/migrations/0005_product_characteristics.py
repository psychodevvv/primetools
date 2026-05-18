from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('shop', '0004_product_source_url'),
    ]

    operations = [
        migrations.AddField(
            model_name='product',
            name='characteristics',
            field=models.TextField(blank=True),
        ),
    ]
