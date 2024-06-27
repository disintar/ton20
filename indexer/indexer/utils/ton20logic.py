import traceback
from io import StringIO
from time import time
from typing import Tuple, Union

from indexer.models import Transaction, AccountCache, TransactionStatus, Ton20StateSerialized, get_field_names
from tonpy import VmDict
from loguru import logger
from collections import defaultdict
from tonpy import Address

from indexer.utils.ton20state import Ton20State
from indexer.utils.tx_parent import check_tx_parent
import orjson as json
import pandas as pd
from django.db import connection
status_columns = get_field_names(TransactionStatus)
max_int = 2 ** 256


def try_int(x):
    try:
        x = int(x)
        if x < max_int:
            return x
        else:
            return 0
    except Exception as e:
        return 0


def fix_address(address):
    if address is None:
        return None

    if ':' in address:
        to_addr = address.split(':')
        address = f"{to_addr[0]}:{to_addr[1].zfill(64)}"

    try:
        a = Address(address)
        return f"{a.wc}:{a.address}"
    except Exception as e:
        return None


def convert_tx(tx):
    if not isinstance(tx['in_msg_comment'], dict):
        return {"transaction_hash": tx['transaction_hash'],
                "success": False,
                'tick': None,
                'op_code': None,
                'initiator': f"{tx['in_msg_src_addr_workchain_id']}:{tx['in_msg_src_addr_address_hex']}",
                'mint_amount': 0,
                'transfer_amount': 0,
                'transfer_to': None,
                'memo': None,
                'in_msg_created_lt': tx['in_msg_created_lt'],
                "fail_reason": "no"}

    data = tx['in_msg_comment']
    op_code = str(data.get('op', ''))[:200].lower()
    return {
        'transaction_hash': tx['transaction_hash'],
        'tick': str(data.get('tick', None))[:200].lower(),
        'op_code': op_code if op_code else None,
        'initiator': f"{tx['in_msg_src_addr_workchain_id']}:{tx['in_msg_src_addr_address_hex']}",
        'mint_amount': try_int(data.get('amt', 0)) if op_code == 'mint' else 0,
        'transfer_amount': try_int(data.get('amt', 0)) if op_code != 'mint' else 0,
        'transfer_to': fix_address(data.get('to', None)),
        'memo': str(data.get('memo', ''))[:254],
        'success': True,
        'fail_reason': 'no',
        'in_msg_created_lt': tx['in_msg_created_lt']
    }


class Ton20Logic:
    """
    Main workflow:

    # Start commit of new patch of TXs per next max_mc_ref
    self.start()

    # Add txs one by one ordered by lt/hash
    for tx in txs:
        self.add_transaction(...)

    # Commit batch to DB
    self.commit()

    """

    def __init__(self,
                 mc_ref_seqno=0,
                 commit_state_each_x_txs=100000,
                 status_txs_enabled=True):
        self.mc_ref_seqno = mc_ref_seqno
        self.max_mc_ref = mc_ref_seqno
        self.committed = True
        self.status_txs_enabled = status_txs_enabled

        # {address: {block_lt: cnt}}
        self.by_block_by_account = None
        self.account_cache = {}
        self.state = Ton20State()
        self.uncommited_txs = 0
        self.transactions_status = []
        self.commit_state_each_x_txs = commit_state_each_x_txs

        self.clear_by_block_by_account()
        self.load_account_cache()

    def load_account_cache(self):
        for i in AccountCache.objects.all():
            if i.is_contract_wallet and not i.account_blacklist:
                self.account_cache[i.address] = True
            else:
                self.account_cache[i.address] = False

    def check_account_type(self, address):
        if address not in self.account_cache:
            account = AccountCache.objects.filter(address=address).first()
            self.account_cache[account.address] = account.is_contract_wallet and not account.account_blacklist

        return self.account_cache[address]

    def finalize(self):
        if self.transactions_status:
            self.bulk_insert_status()

    def bulk_insert_status(self):
        if not self.transactions_status:
            return

        # Get the correct order of columns from the model
        field_names = [field.name for field in TransactionStatus._meta.fields]

        # Create DataFrame with the correct column order
        df = pd.DataFrame(self.transactions_status, columns=field_names)

        # Convert DataFrame to CSV string
        buffer = StringIO()
        df.to_csv(buffer, index=False, header=False)
        buffer.seek(0)

        table_name = TransactionStatus._meta.db_table

        with connection.cursor() as cursor:
            cursor.copy_expert(f"COPY {table_name} ({', '.join(field_names)}) FROM STDIN WITH CSV",
                               buffer)

        self.transactions_status = []

    def clear_by_block_by_account(self):
        self.by_block_by_account = defaultdict(lambda: defaultdict(lambda: []))

    def deploy(self, tx) -> tuple[bool, str]:
        for f in ['tick', 'max', 'lim']:
            if f not in tx['in_msg_comment']:
                return False, f"Can't find: {f}"

        if not isinstance(tx['in_msg_comment']['tick'], str):
            return False, "Tick invalid"

        tick = tx['in_msg_comment']['tick'].lower()

        if tick in self.state.ticks:
            return False, "Already exist"

        if len(bin(int(tick.encode().hex(), 16))[2:]) > 256:
            return False, "Tick too large"

        try:
            if not isinstance(tx['in_msg_comment']['max'], str):
                raise ValueError

            if not isinstance(tx['in_msg_comment']['lim'], str):
                raise ValueError

            max_ = int(tx['in_msg_comment']['max'])
            lim_ = int(tx['in_msg_comment']['lim'])
            assert max_ > 0, f"Must be: max > 0: {max_}"
            assert max_ < max_int, f"Must be: max < max_int: {max_}"
            assert lim_ > 0, f"Must be: lim_ > 0: {lim_}"
            assert lim_ < max_int, f"Must be: lim_ < max_int: {lim_}"
        except Exception as e:
            return False, "Can't parse params"

        address = f"{tx['in_msg_src_addr_workchain_id']}:{tx['in_msg_src_addr_address_hex']}"
        self.state.deploy(tick, max_, lim_, address, tx['transaction_hash'])
        return True, ''

    def transfer(self, tx) -> tuple[bool, str]:
        for f in ['tick', 'to', 'amt']:
            if f not in tx['in_msg_comment'] or not isinstance(tx['in_msg_comment'][f], str):
                return False, f"Can't find {f}"

        if not isinstance(tx['in_msg_comment']['tick'], str):
            return False, "Tick not valid"

        if not isinstance(tx['in_msg_comment']['to'], str):
            return False, "To not valid"

        tick = tx['in_msg_comment']['tick'].lower()
        address_from = f"{tx['in_msg_src_addr_workchain_id']}:{tx['in_msg_src_addr_address_hex']}"

        if tick not in self.state.ticks:
            return False, f"Tick not exist"

        try:
            if not isinstance(tx['in_msg_comment']['amt'], str):
                raise ValueError(f"amt must be str, got: {type(tx['in_msg_comment']['amt'])}")

            amt = int(tx['in_msg_comment']['amt'])
            assert amt > 0, f"amt must be > 0, {amt}"
            assert amt < max_int, f"amt must be < max_int, {amt}"
        except Exception as e:
            return False, f"Can't parse amt"

        if tick not in self.state.wallets:
            return False, "Tick not exist"

        if address_from not in self.state.wallets[tick] or self.state.wallets[tick][address_from]['amount'] < amt:
            return False, f"Out of money"

        try:
            if ':' in tx['in_msg_comment']['to']:
                to_addr = tx['in_msg_comment']['to'].split(':')
                tx['in_msg_comment']['to'] = f"{to_addr[0]}:{to_addr[1].zfill(64)}"

            a = Address(f"{tx['in_msg_comment']['to']}")
            address_to = f"{a.wc}:{a.address}"
        except Exception as e:
            return False, f"Can't parse to"

        self.state.transfer(tick, address_from, address_to, amt, tx['transaction_hash'])
        return True, ''

    def mint(self, tx) -> tuple[bool, str]:
        for f in ['tick', 'amt']:
            if f not in tx['in_msg_comment']:
                return False, f"Can't find {f}"

        if not isinstance(tx['in_msg_comment']['tick'], str):
            return False, "Tick invalid"

        tick = tx['in_msg_comment']['tick'].lower()

        try:
            if not isinstance(tx['in_msg_comment']['amt'], str):
                raise ValueError(f"amt must be str, got: {type(tx['in_msg_comment']['amt'])}")

            amt = int(tx['in_msg_comment']['amt'])
            assert amt > 0, f"amt must be > 0, {amt}"
            assert amt < max_int, f"amt must be < max_int, {amt}"
        except Exception as e:
            return False, f"Can't parse amt: {e}"

        if tick not in self.state.ticks:
            return False, "Tick not found"

        if amt > self.state.ticks[tick]['lim']:
            return False, "Amt > limit of tick"

        if self.state.ticks[tick]['rest'] == 0:
            return False, "Tick is full"

        if amt > self.state.ticks[tick]['rest']:
            # amt = self.state.ticks[tick]['rest']
            # logger.warning(f"Apply not full sum for {tx['transaction_hash']}")
            return False, "Tick rest less amt"

        address = f"{tx['in_msg_src_addr_workchain_id']}:{tx['in_msg_src_addr_address_hex']}"
        self.state.mint(tick, address, amt, tx['transaction_hash'])
        return True, ''

    def initial_check(self, tx) -> tuple[bool, str]:
        """
        Check txs per block, check valid of structure, check receiver & sender
        """
        change_point = 1701955800

        # success transaction
        if 'p' in tx['in_msg_comment'] and tx['in_msg_comment']['p'] == 'ton-20' and 'op' in tx['in_msg_comment'] \
                and tx['in_msg_comment']['op'] in ['transfer', 'mint', 'deploy']:
            address = f"{tx['workchain']}:{tx['account']}"
            to_zero = address == "0:0000000000000000000000000000000000000000000000000000000000000000"

            address_from = f"{tx['in_msg_src_addr_workchain_id']}:{tx['in_msg_src_addr_address_hex']}"

            key = tx['in_msg_created_lt'] - (tx['in_msg_created_lt'] % 1000000)
            if tx['in_msg_created_at'] < change_point and to_zero and not self.check_account_type(address_from):
                # This is only for initial accounts, we need to know parent TX
                # Because you can send several TXs with 4 child in one block with highland
                # And it'll not be tracked by LT
                success, fail_reason = check_tx_parent(tx['transaction_hash'])

                if not success:
                    return success, fail_reason

                key = tx['transaction_hash']

            self.by_block_by_account[address_from][key].append(tx['in_msg_created_lt'])

            # Up to 4 messages per 1 time
            if len(self.by_block_by_account[address_from][key]) > 4:
                return False, f"TX sended >4 times: {self.by_block_by_account[address_from][key]}, address, key"

            # Before `change_point` to 0
            if tx['in_msg_created_at'] < change_point and not to_zero:
                return False, "TX sended not to zero account"
            elif tx['in_msg_created_at'] > change_point:
                if to_zero:
                    return False, "TX sended to zero account after change point"

                if tx['in_msg_comment']['op'] != 'transfer' and not self.check_account_type(address_from):
                    return False, "TX sended not in wallet"

            return True, ""
        else:
            return False, "Json is not valid"

    def add_transaction(self, tx):
        if tx['mc_ref_seqno'] < self.mc_ref_seqno:
            raise ValueError(f"Transactions should be already processed")

        if tx['mc_ref_seqno'] > self.max_mc_ref:
            self.max_mc_ref = tx['mc_ref_seqno']

        success, fail_reason = self.initial_check(tx)
        if not success:
            if self.status_txs_enabled:
                self.transactions_status.append({"transaction_hash": tx['transaction_hash'],
                                                 "success": False,
                                                 'tick': None,
                                                 'op_code': None,
                                                 'initiator': f"{tx['in_msg_src_addr_workchain_id']}:{tx['in_msg_src_addr_address_hex']}",
                                                 'mint_amount': 0,
                                                 'transfer_amount': 0,
                                                 'transfer_to': None,
                                                 'memo': None,
                                                 'in_msg_created_lt': tx['in_msg_created_lt'],
                                                 "fail_reason": fail_reason if fail_reason else "no"})

            return success, fail_reason

        if tx['in_msg_comment']['op'] == 'transfer':
            success, fail_reason = self.transfer(tx)
        elif tx['in_msg_comment']['op'] == 'mint':
            success, fail_reason = self.mint(tx)
        elif tx['in_msg_comment']['op'] == 'deploy':
            success, fail_reason = self.deploy(tx)

        txs = convert_tx(tx)
        txs['success'] = success
        txs['fail_reason'] = fail_reason if fail_reason else 'no'

        if self.status_txs_enabled:
            self.transactions_status.append(txs)

        self.uncommited_txs += 1
        if self.uncommited_txs == self.commit_state_each_x_txs:
            logger.info(f"Start commit batch")
            self.commit(tx)

        return success, fail_reason

    def commit(self, last_tx):
        if self.max_mc_ref is None:
            logger.warning(f"There's no success transactions in current batch")
        else:
            self.clear_by_block_by_account()

            logger.info(f"Start dump TransactionStatus")
            t = time()
            self.bulk_insert_status()

            logger.info(f"TransactionStatus created at: {time() - t}")

            logger.info(f"Start serialize state")
            t = time()
            serialized_state = self.state.serialize(last_tx)

            logger.info(f"Serialize state at: {time() - t}")
            t = time()
            total_state = Ton20StateSerialized(state_hash=serialized_state.get_hash(),
                                               in_msg_created_lt=int(last_tx['in_msg_created_lt']),
                                               transaction_hash=last_tx['transaction_hash'],
                                               state_boc=serialized_state.to_boc())
            total_state.save()
            logger.info(f"Saved state to db at: {time() - t}")

            self.uncommited_txs = 0
