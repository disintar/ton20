# Generated by Django 4.2.7 on 2024-06-17 15:21

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('indexer', '0021_transactionstatus_in_msg_created_lt_and_more'),
    ]

    operations = [
        migrations.RemoveIndex(
            model_name='transactionstatus',
            name='indexer_tra_in_msg__cfd0ad_idx',
        ),
        migrations.RemoveIndex(
            model_name='transactionstatus',
            name='indexer_tra_transac_6205ca_idx',
        ),
        migrations.RemoveIndex(
            model_name='transactionstatus',
            name='indexer_tra_success_d2aa10_idx',
        ),
        migrations.RemoveIndex(
            model_name='transactionstatus',
            name='indexer_tra_op_code_14a907_idx',
        ),
        migrations.RemoveIndex(
            model_name='transactionstatus',
            name='indexer_tra_tick_b044f9_idx',
        ),
        migrations.RemoveIndex(
            model_name='transactionstatus',
            name='indexer_tra_initiat_11d64b_idx',
        ),
        migrations.RemoveIndex(
            model_name='transactionstatus',
            name='indexer_tra_transfe_0986a3_idx',
        ),
    ]