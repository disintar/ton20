from django.db import models
from django.utils import timezone
import orjson as json
from loguru import logger


class LatestIndex(models.Model):
    seqno = models.BigIntegerField()


class Transaction(models.Model):
    mc_ref_seqno = models.DecimalField(max_digits=78, decimal_places=0)

    gen_utime = models.DateTimeField(default=timezone.now)
    workchain = models.IntegerField()
    shard = models.DecimalField(max_digits=78, decimal_places=0)
    seqno = models.DecimalField(max_digits=78, decimal_places=0)
    root_hash = models.CharField(max_length=200, null=True)
    file_hash = models.CharField(max_length=200, null=True)

    lt = models.DecimalField(max_digits=78, decimal_places=0)
    now = models.DateTimeField(default=timezone.now)
    account = models.CharField(max_length=200)
    transaction_hash = models.CharField(max_length=200, unique=True)
    transaction_boc = models.TextField()

    in_msg_comment = models.TextField(null=True)
    in_msg_created_lt = models.BigIntegerField(null=True)
    in_msg_created_at = models.BigIntegerField(null=True)
    in_msg_value_grams = models.DecimalField(max_digits=78, decimal_places=0, null=True)
    in_msg_hash = models.CharField(max_length=200, null=True)
    in_msg_src_addr_workchain_id = models.IntegerField(null=True)
    in_msg_src_addr_address_hex = models.CharField(max_length=200, null=True)

    def __repr__(self):
        return f"<Transaction hash='{self.transaction_hash}', gen_utime='{self.gen_utime}'>"

    def to_dict(self):
        comment = {}
        try:
            comment = json.loads(self.in_msg_comment)
            if not isinstance(comment, dict):
                comment = {}
        except KeyboardInterrupt:
            raise KeyboardInterrupt
        except Exception as e:
            # logger.error(f"Can't parse json: {e}")
            pass

        return {
            'mc_ref_seqno': self.mc_ref_seqno,
            'gen_utime': self.gen_utime,
            'workchain': self.workchain,
            'shard': self.shard,
            'seqno': self.seqno,
            'root_hash': self.root_hash,
            'file_hash': self.file_hash,
            'lt': self.lt,
            'now': self.now,
            'account': self.account,
            'transaction_hash': self.transaction_hash,
            'transaction_boc': self.transaction_boc,
            'in_msg_comment': comment,
            'in_msg_created_lt': self.in_msg_created_lt,
            'in_msg_created_at': self.in_msg_created_at,
            'in_msg_value_grams': self.in_msg_value_grams,
            'in_msg_hash': self.in_msg_hash,
            'in_msg_src_addr_workchain_id': self.in_msg_src_addr_workchain_id,
            'in_msg_src_addr_address_hex': self.in_msg_src_addr_address_hex
        }

    class Meta:
        indexes = [
            models.Index(fields=['gen_utime', 'lt']),
            models.Index(fields=['in_msg_created_lt']),
            models.Index(fields=['in_msg_created_lt', 'in_msg_hash']),
            models.Index(fields=['gen_utime', 'lt', 'in_msg_created_lt']),
            models.Index(fields=['in_msg_src_addr_workchain_id', 'in_msg_src_addr_address_hex']),
            models.Index(fields=['root_hash']),
            models.Index(fields=['transaction_hash']),
            models.Index(fields=['mc_ref_seqno']),
        ]


class TransactionStatus(models.Model):
    transaction_hash = models.CharField(max_length=200, unique=True, primary_key=True)
    success = models.BooleanField(default=False)
    fail_reason = models.TextField()
    in_msg_created_lt = models.BigIntegerField(null=True)

    op_code = models.CharField(max_length=200, null=True)
    tick = models.CharField(max_length=200, null=True)
    initiator = models.CharField(max_length=78, null=True)

    mint_amount = models.DecimalField(max_digits=78, decimal_places=0, null=True)
    transfer_amount = models.DecimalField(max_digits=78, decimal_places=0, null=True)
    transfer_to = models.CharField(max_length=78, null=True)
    memo = models.CharField(max_length=255, null=True)

    # class Meta:
    #     indexes = [
    #         models.Index(fields=['in_msg_created_lt']),
    #         models.Index(fields=['transaction_hash']),
    #         models.Index(fields=['success']),
    #         models.Index(fields=['op_code']),
    #         models.Index(fields=['tick']),
    #         models.Index(fields=['initiator']),
    #         models.Index(fields=['transfer_to']),
    #     ]


class Ton20StateSerialized(models.Model):
    state_hash = models.CharField(max_length=67, unique=True, primary_key=True)
    in_msg_created_lt = models.BigIntegerField()
    transaction_hash = models.CharField(max_length=67, unique=True)
    state_boc = models.TextField()

    class Meta:
        indexes = [
            models.Index(fields=['in_msg_created_lt']),
            models.Index(fields=['transaction_hash']),
        ]

    def to_cell(self):
        from tonpy import Cell
        return Cell(self.state_boc)

    @staticmethod
    def get_latest_state():
        try:
            latest_state = Ton20StateSerialized.objects.order_by('-in_msg_created_lt').first()
            return latest_state
        except Ton20StateSerialized.DoesNotExist:
            return None


class AccountCache(models.Model):
    # wc:address uppercase
    address = models.CharField(max_length=67, unique=True, primary_key=True)
    is_contract_wallet = models.BooleanField(default=False)

    # Banned from mint accounts, because they delete wallet in some blocks
    account_blacklist = models.BooleanField(default=False)
    smc_hash = models.CharField(max_length=64)

    class Meta:
        indexes = [
            models.Index(fields=['address']),
            models.Index(fields=['smc_hash']),
        ]


class Ton20Tick(models.Model):
    tick = models.CharField(max_length=255, unique=True, primary_key=True)
    max = models.DecimalField(max_digits=78, decimal_places=0, null=True)
    lim = models.DecimalField(max_digits=78, decimal_places=0, null=True)
    rest = models.DecimalField(max_digits=78, decimal_places=0, null=True)
    deploy_by = models.CharField(max_length=78)
    txhash = models.CharField(max_length=67)

    class Meta:
        indexes = [
            models.Index(fields=['deploy_by']),
            models.Index(fields=['txhash']),
        ]

        ordering = ['tick']


class Ton20Wallet(models.Model):
    wallet = models.CharField(max_length=78)
    tick = models.CharField(max_length=255)
    amount = models.DecimalField(max_digits=78, decimal_places=0, null=True)
    txhash = models.CharField(max_length=67)

    class Meta:
        unique_together = (('wallet', 'tick'),)

        indexes = [
            models.Index(fields=['wallet']),
            models.Index(fields=['tick']),
            models.Index(fields=['amount']),
        ]

def get_field_names(model):
    return [field.name for field in model._meta.fields]