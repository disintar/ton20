# Generated by Django 5.0.2 on 2024-04-24 19:28

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('indexer', '0010_transaction_indexer_tra_mc_ref__0ece2b_idx'),
    ]

    operations = [
        migrations.AddField(
            model_name='transaction',
            name='fail_reason',
            field=models.CharField(max_length=200, null=True),
        ),
        migrations.AddField(
            model_name='transaction',
            name='success',
            field=models.BooleanField(default=False),
        ),
    ]