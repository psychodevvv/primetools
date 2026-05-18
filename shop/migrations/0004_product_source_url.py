from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('shop', '0003_category_image_url'),
    ]

    operations = [
        migrations.AddField(
            model_name='product',
            name='source_url',
            field=models.URLField(blank=True),
        ),
    ]
