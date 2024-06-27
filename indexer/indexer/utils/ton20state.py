import codecs

from tonpy import CellBuilder, VmDict, Address, Cell, CellSlice
from tqdm import tqdm

from indexer.models import Ton20Tick, Ton20Wallet
from django.db import connection, transaction
from django.db.models import Q
from loguru import logger
import psycopg2.extras

from indexer.utils.chunks import chunks


def bulk_upsert(model, conflict_fields, update_fields, records):
    if not records:
        return

    table_name = model._meta.db_table
    columns = [field.column for field in model._meta.fields if field.column != 'id']
    conflict_fields_str = ', '.join(conflict_fields)
    update_fields_str = ', '.join([f"{field}=EXCLUDED.{field}" for field in update_fields])

    values_list = []
    for record in records:
        values = [getattr(record, field) for field in columns]
        values_list.append(values)

    sql = f"""
        INSERT INTO {table_name} ({', '.join(columns)}) VALUES %s
        ON CONFLICT ({conflict_fields_str}) DO UPDATE SET {update_fields_str}
    """
    with connection.cursor() as cursor:
        psycopg2.extras.execute_values(cursor, sql, values_list)


class Ton20State:
    """Here's no checks, just serialization & deserialization"""

    def __init__(self, boc: str = None):
        self.ticks = {}
        self.wallets = {}
        self.to_update_ticks = []
        self.to_update_wallets = []
        self.to_delete_wallets = set()

    def create_wallet(self, tick_: str, wallet_: str):
        if frozenset([tick_, wallet_]) in self.to_delete_wallets:
            logger.info(f"Will move back: {tick_}, {wallet_}")
            self.to_delete_wallets.remove(frozenset([tick_, wallet_]))

        self.wallets[tick_][wallet_] = {
            'amount': 0,
            'txhash': '0' * 64
        }

    def deploy(self, tick_: str, max_: int, lim_: int, address: str, txhash: str):
        self.wallets[tick_] = {}
        self.ticks[tick_] = {
            'max': max_,
            'lim': lim_,
            'rest': max_,
            'deploy_by': address,
            'txhash': txhash
        }
        self.to_update_ticks.append(tick_)

    def mint(self, tick_: str, wallet_: str, amt_: int, txhash: str):
        if wallet_ not in self.wallets[tick_]:
            self.create_wallet(tick_, wallet_)

        self.wallets[tick_][wallet_]['amount'] += amt_
        self.wallets[tick_][wallet_]['txhash'] = txhash
        self.ticks[tick_]['rest'] -= amt_
        self.to_update_wallets.append([tick_, wallet_])

    def transfer(self, tick_: str, from_: str, to_: str, amt_: int, txhash: str):
        self.wallets[tick_][from_]['amount'] -= amt_
        self.wallets[tick_][from_]['txhash'] = txhash

        if self.wallets[tick_][from_]['amount'] == 0:
            self.to_delete_wallets.add(frozenset([tick_, from_]))
            logger.info(f"Will delete: {tick_}, {from_}")
            del self.wallets[tick_][from_]

        if to_ not in self.wallets[tick_]:
            self.create_wallet(tick_, to_)

        self.wallets[tick_][to_]['amount'] += amt_
        self.wallets[tick_][to_]['txhash'] = txhash
        self.to_update_wallets.extend([[tick_, to_], [tick_, from_]])

    def serialize(self, last_tx) -> Cell:
        lt = last_tx['lt']
        txhash = last_tx['transaction_hash']
        mc_ref_seqno = int(last_tx['mc_ref_seqno'])

        # walletinfo$_ amount:uint256 last_txhash:bits256 = WalletInfo;
        #
        # tickinfo$000 max:uint256 lim:uint256 rest:uint256
        #             ^[deploy_by:MsgAddressInt deploy_txhash:bits256]
        #             wallets:(HashmapE 264 WalletInfo) = TickInfo;
        #
        # ton20state#64746f6e last_tx_hash:uint256 last_tx_lt:uint64 master_ref_seqno:uint32
        #                 ticks:(HashmapE 256 TickInfo) = Ton20State;

        ticks = VmDict(256, False)

        for tick in self.ticks:
            tick_header = CellBuilder() \
                .store_bitstring('000') \
                .store_uint(self.ticks[tick]['max'], 256) \
                .store_uint(self.ticks[tick]['lim'], 256) \
                .store_uint(self.ticks[tick]['rest'], 256) \
                .store_ref(CellBuilder().store_address(self.ticks[tick]['deploy_by']) \
                           .store_uint(int(self.ticks[tick]['txhash'], 16), 256).end_cell())

            if len(self.wallets[tick]) == 0:
                tick_header = tick_header.store_uint(0, 1)
            else:
                vmdict = VmDict(264, False)

                for wallet in self.wallets[tick]:
                    a = Address(wallet)

                    key = CellBuilder() \
                        .store_int(a.wc, 8) \
                        .store_uint(int(a.address, 16), 256) \
                        .end_cell().begin_parse()

                    vmdict.set_builder_keycs(key, CellBuilder() \
                                             .store_uint(self.wallets[tick][wallet]['amount'], 256) \
                                             .store_uint(int(self.wallets[tick][wallet]['txhash'], 16), 256))

                tick_header = tick_header.store_uint(1, 1).store_ref(vmdict.get_cell())

            ticks[int(tick.encode().hex(), 16)] = tick_header.end_cell()

        return CellBuilder() \
            .store_uint(0x64746f6e, 32) \
            .store_uint(int(txhash, 16), 256) \
            .store_uint(int(lt), 64) \
            .store_uint(int(mc_ref_seqno), 32) \
            .store_uint(1, 1) \
            .store_ref(ticks.get_cell()) \
            .end_cell()

    def process_tick_wallet(self, tick):
        def process_wallet(key, value):
            wallet_wc = key.load_int(8)
            wallets_address = hex(key.load_uint(256)).upper()[2:].zfill(64)
            address = f"{wallet_wc}:{wallets_address}"

            amount = value.load_uint(256)
            last_txhash = hex(value.load_uint(256)).upper()[2:].zfill(64)
            self.wallets[tick][address] = {
                'amount': amount,
                'txhash': last_txhash
            }
            return True

        return process_wallet

    def process_tick(self, key, value):
        value = value.load_ref().begin_parse()
        assert value.load_bitstring(3) == '000'

        tick_max = value.load_uint(256)
        tick_lim = value.load_uint(256)
        tick_rest = value.load_uint(256)

        other = value.load_ref().begin_parse()
        tick_deploy_by = other.load_address()
        tick_deploy_txhash = hex(other.load_uint(256)).upper()[2:].zfill(64)
        tick = codecs.decode(hex(key.load_uint(256))[2:], "hex").decode('utf-8')

        self.ticks[tick] = {
            'max': tick_max,
            'lim': tick_lim,
            'rest': tick_rest,
            'deploy_by': tick_deploy_by.serialize(),
            'txhash': tick_deploy_txhash
        }

        self.wallets[tick] = {}
        if value.load_bool():
            c = value.load_ref()
            wallets = VmDict(256 + 8, cell_root=c)
            wallets.map(self.process_tick_wallet(tick))

        return True

    def deserialize(self, state_boc, latest_lt, latest_hash):
        logger.info(f"Start state deseiralize")
        cc = CellSlice(state_boc)
        assert cc.load_uint(32) == 0x64746f6e

        last_tx_hash = hex(cc.load_uint(256)).upper()[2:].zfill(64)
        logger.info(f"Last tx hash: {last_tx_hash} / {latest_hash}")
        # assert last_tx_hash == latest_hash

        last_tx_lt = cc.load_uint(64)
        master_ref_seqno = cc.load_uint(32)
        ticks = VmDict(256, cell_root=cc.load_ref())

        logger.info(f"Start load ticks")
        ticks.map(self.process_tick)

        self.to_update_ticks = list(self.ticks.keys())
        self.to_update_wallets = [(tick, wallet) for tick in self.wallets for wallet in self.wallets[tick]]

        logger.info(f"Loaded: {len(self.to_update_ticks)} ticks and {len(self.to_update_wallets)} wallets")

        self.save_to_db()

    def save_to_db(self):
        logger.info(f"Start saving to db")
        self.to_update_ticks = set(self.to_update_ticks)

        if len(self.to_update_wallets):
            self.to_update_wallets = set(frozenset(a) for a in self.to_update_wallets)

            # Prepare data for Ton20Tick
            tick_objects = []
            for tick, data in self.ticks.items():
                if tick in self.to_update_ticks:
                    tick_objects.append(
                        Ton20Tick(
                            tick=tick,
                            max=data['max'],
                            lim=data['lim'],
                            rest=data['rest'],
                            deploy_by=data['deploy_by'],
                            txhash=data['txhash']
                        )
                    )

            # Prepare data for Ton20Wallet
            wallet_objects = []
            for tick, wallets in self.wallets.items():
                for address, data in wallets.items():
                    if frozenset([tick, address]) in self.to_update_wallets:
                        wallet_objects.append(
                            Ton20Wallet(
                                wallet=address,
                                tick=tick,
                                amount=data['amount'],
                                txhash=data['txhash']
                            )
                        )

            with transaction.atomic():
                if len(self.to_delete_wallets):
                    logger.info(f"Will delete wallets: {len(self.to_delete_wallets)}")

                    for tick, wallet in tqdm(self.to_delete_wallets, desc="delete wallets"):
                        Ton20Wallet.objects.filter(wallet=wallet, tick=tick).delete()

                    self.to_delete_wallets = []

                for chunk in tqdm(list(chunks(tick_objects)), desc="Ticks insert"):
                    bulk_upsert(
                        Ton20Tick,
                        conflict_fields=['tick'],
                        update_fields=['max', 'lim', 'rest', 'deploy_by', 'txhash'],
                        records=chunk
                    )

                for chunk in tqdm(list(chunks(wallet_objects)), desc="Wallets insert"):
                    bulk_upsert(
                        Ton20Wallet,
                        conflict_fields=['wallet', 'tick'],
                        update_fields=['amount', 'txhash'],
                        records=chunk
                    )

        logger.info(f"Done insert")
        self.to_update_ticks = []
        self.to_update_wallets = []
