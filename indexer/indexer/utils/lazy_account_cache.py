import sys
import os

sys.path.append(os.path.join(os.getcwd(), '../'))

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "tonano.settings")
os.environ["DJANGO_ALLOW_ASYNC_UNSAFE"] = "true"
import django

django.setup()

from indexer.models import AccountCache
from tonpy import Address, LiteClient
from tonpy.autogen.block import Account as TLB_Account
from cytoolz import curry


class KnownAccountsLazy:
    def __init__(self):
        self.known = set()

    def __contains__(self, item):
        if item not in self.known:
            if AccountCache.objects.filter(address=item).exists():
                self.known.add(item)
                return True
            else:
                return False


@curry
def load_account(item, lcparams):
    lc = LiteClient(**lcparams)
    account, created_lt = item

    src_addr = Address(account)
    block_lt = created_lt - created_lt % 1000000
    acc_state_block = lc.lookup_block(workchain=0, shard=src_addr.shard_prefix(60), lt=block_lt).blk_id
    acc = lc.get_account_state(account=src_addr, block=acc_state_block)

    try:
        code_hash = TLB_Account().fetch(acc.root).dump()['storage']['state']['x']['code']['value'].get_hash()
        return account, code_hash
    except Exception as e:
        return account, None
