# Generated by Django 5.0.2 on 2024-03-23 21:35

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('indexer', '0005_transaction_in_msg_comment_and_more'),
    ]

    operations = [
        migrations.AddIndex(
            model_name='transaction',
            index=models.Index(fields=['gen_utime', 'lt'], name='indexer_tra_gen_uti_1a5f35_idx'),
        ),
    ]