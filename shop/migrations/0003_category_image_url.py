from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('shop', '0002_orderitem_product_article'),
    ]

    operations = [
        migrations.AddField(
            model_name='category',
            name='image_url',
            field=models.URLField(blank=True),
        ),
    ]
