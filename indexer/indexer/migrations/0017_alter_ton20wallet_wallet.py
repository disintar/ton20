# Generated by Django 5.0.2 on 2024-06-03 09:33

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('indexer', '0016_alter_ton20wallet_txhash'),
    ]

    operations = [
        migrations.AlterField(
            model_name='ton20wallet',
            name='wallet',
            field=models.CharField(max_length=78),
        ),
    ]
