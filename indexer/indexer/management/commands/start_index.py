import traceback

from django.core.management.base import BaseCommand
from queue import Queue

from django.db.models import Max
from django.utils.timezone import make_aware
from indexer.models import Transaction, AccountCache, LatestIndex
from tonpy.types.liteclient import LiteClient
from tonpy.blockscanner.blockscanner import BlockScanner
from tonpy.blockscanner.subscriptions import TransactionSubscription
from time import sleep, time
import os
import signal
from datetime import datetime
from loguru import logger
import random
from tqdm import tqdm

from indexer.utils.tx_unpack import get_in_msg_info
from indexer.utils.lazy_account_cache import KnownAccountsLazy, load_account
from multiprocessing import Pool, set_start_method, get_context, get_start_method
from tonpy.libs.python_ton import globalSetVerbosity
from django.conf import settings

globalSetVerbosity(2)

wallet_v1data = ["A0CFC2C48AEE16A271F2CFC0B7382D81756CECB1017D077FAAAB3BB602F6868C",
                 "D4902FCC9FAD74698FA8E353220A68DA0DCF72E32BCB2EB9EE04217C17D3062C",
                 "587CC789EFF1C84F46EC3797E45FC809A14FF5AE24F1E0C7A6A99CC9DC9061FF",
                 "5C9A5E68C108E18721A07C42F9956BFB39AD77EC6D624B60C576EC88EEE65329",
                 "FE9530D3243853083EF2EF0B4C2908C0ABF6FA1C31EA243AACAA5BF8C7D753F1"]

wallet_v2data = ["B61041A58A7980B946E8FB9E198E3C904D24799FFA36574EA4251C41A566F581",
                 "84DAFA449F98A6987789BA232358072BC0F76DC4524002A5D0918B9A75D2D599",
                 "64DD54805522C5BE8A9DB59CEA0105CCF0D08786CA79BEB8CB79E880A8D7322D",
                 "FEB5FF6820E2FF0D9483E7E0D62C817D846789FB4AE580C878866D959DABD5C0"]

wallets_blacklist = ['0:3C55D1694B3168E979F770603B47D915A2757998D24AC3525D4BCBD7ABB26BBA']

WALLET_HASHES = set(wallet_v1data + wallet_v2data)
accounts_lazy_cache = KnownAccountsLazy()


def process_blocks(lc, block_chunk):
    global accounts_lazy_cache

    block = block_chunk[0]
    block_id = block['block_id']

    to_save_txs = []
    to_proccess_accs = []  # "[account, LT]"

    for tx in block_chunk[2]:
        try:
            gen_utime = make_aware(datetime.fromtimestamp(block['gen_utime']))
            now = make_aware(datetime.fromtimestamp(tx['now']))
            t_boc = tx['tx'].to_boc()
            tx = Transaction(
                mc_ref_seqno=block['master'] if 'master' in block else block_id.id.seqno,
                gen_utime=gen_utime,
                workchain=block_id.id.workchain,
                shard=block_id.id.shard,
                seqno=block_id.id.seqno,
                root_hash=block_id.root_hash,
                file_hash=block_id.file_hash,
                lt=tx['lt'],
                now=now,
                account=hex(tx['account'])[2:].zfill(64).upper(),
                transaction_hash=tx['tx'].get_hash(),
                transaction_boc=t_boc,
                **get_in_msg_info(t_boc)
            )

            to_save_txs.append(tx)
            account = f"{tx.in_msg_src_addr_workchain_id}:{tx.in_msg_src_addr_address_hex}"

            if account not in accounts_lazy_cache:
                to_proccess_accs.append([account, tx.in_msg_created_lt])
                accounts_lazy_cache.known.add(account)

        except Exception as e:
            logger.error(traceback.format_exc())
            logger.error(f"{e}")
            logger.error(str(tx))
            raise e

    return to_save_txs, to_proccess_accs


def process_result(lc, outq):
    try:
        total_txs = []

        if not outq.empty():
            data = outq.get()
            total_txs.extend(data['txs'])
            seqno = data['seqno']
        else:
            return 0

        if len(total_txs) > 0:
            tmp_txs = []
            tmp_accs = []
            tmp_load_accs = []
            tmp_load_accs_str = set()
            stat = time()

            for i in tqdm(total_txs, desc="Create obj"):
                txs, to_load_accs = process_blocks(lc, i)

                for i in to_load_accs:
                    if i[0] not in tmp_load_accs_str:
                        tmp_load_accs_str.add(i[0])
                        tmp_load_accs.append(i)

                tmp_txs.extend(txs)

            if len(tmp_load_accs) > 0:
                logger.debug(f"Load accounts states: {len(tmp_load_accs)}")

                if len(tmp_load_accs) > 10:
                    with get_context("spawn").Pool(settings.NPROC) as pool:
                        results = tqdm(
                            pool.imap_unordered(load_account(lcparams=settings.LCPARAMS), tmp_load_accs, chunksize=10),
                            total=len(tmp_load_accs), desc=f"Load accounts states")

                        for i in results:
                            tmp_accs.append(AccountCache(address=i[0], is_contract_wallet=i[1] in WALLET_HASHES,
                                                         smc_hash=i[1] if i[1] is not None else "0" * 64,
                                                         account_blacklist=i[0] in wallets_blacklist))
                else:
                    for i in tqdm(map(load_account(lcparams=settings.LCPARAMS), tmp_load_accs),
                                  total=len(tmp_load_accs), desc=f"Load accounts states"):
                        tmp_accs.append(AccountCache(address=i[0], is_contract_wallet=i[1] in WALLET_HASHES,
                                                     smc_hash=i[1] if i[1] is not None else "0" * 64,
                                                     account_blacklist=i[0] in wallets_blacklist))

            if len(tmp_accs) > 0:
                try:
                    logger.debug(f"Insert: {len(tmp_accs)}")
                    AccountCache.objects.bulk_create(tmp_accs, ignore_conflicts=True, batch_size=100000)
                except Exception as e:
                    print(e, traceback.format_exc())
                    os.kill(os.getpid(), signal.SIGKILL)
                del tmp_accs

                logger.debug(f"Done of ACCOUNTS insert: {time() - stat}")
            if len(tmp_txs) > 0:
                try:
                    logger.debug(f"Insert: {len(tmp_txs)}")
                    Transaction.objects.bulk_create(tmp_txs, ignore_conflicts=True, batch_size=100000)
                except Exception as e:
                    print(e, traceback.format_exc())
                    os.kill(os.getpid(), signal.SIGKILL)

                logger.debug(f"Done of TXs insert: {time() - stat}")
                del tmp_txs

        latest = LatestIndex.objects.first()
        if latest is None or latest.seqno is None:
            latest = LatestIndex(seqno=-1)

        if latest.seqno < seqno:
            logger.info(f"Update MAX seqno to: {seqno}")
            latest.seqno = seqno
            latest.save()

        total = len(total_txs)
        del total_txs
        return total
    except Exception as e:
        logger.error(traceback.format_exc())
        logger.error(str(e))
        os.kill(os.getpid(), signal.SIGKILL)


def start():
    if not get_start_method(allow_none=True):
        set_start_method("spawn")

    cnt = Transaction.objects.count()
    if cnt > 0:
        print(f"Got in db: ", cnt)
        latest = LatestIndex.objects.first()

        if latest is None or latest.seqno is None:
            max_mc_ref_seqno = int(
                Transaction.objects.aggregate(max_mc_ref_seqno=Max('mc_ref_seqno'))['max_mc_ref_seqno'])
        else:
            max_mc_ref_seqno = latest.seqno

        chunk_size = 1000
    else:
        # Initial of TONANO mint
        max_mc_ref_seqno = 34506140
        chunk_size = 10

    lc = LiteClient(**settings.LCPARAMS)

    logger.info(f"Latest seqno: {max_mc_ref_seqno}, chunk size: {chunk_size}")
    outq = Queue()

    scanner = BlockScanner(
        lcparams=settings.LCPARAMS,
        start_from=max_mc_ref_seqno,
        nproc=settings.NPROC,
        loglevel=1,
        out_queue=outq,
        transaction_subscriptions=TransactionSubscription(text="ton-20"),
        tx_chunk_size=5000,
        chunk_size=chunk_size,
        live_load_enable=True
    )

    scanner.start()

    success = 0

    while True:
        success += process_result(lc, outq)
        sleep(1)


class Command(BaseCommand):
    help = 'Start blockchain index'

    def handle(self, *args, **options):
        start()
