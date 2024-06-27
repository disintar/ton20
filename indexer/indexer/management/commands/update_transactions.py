import math
import traceback
from multiprocessing import Pool

from django.core.management.base import BaseCommand

from queue import Queue

from django.db.models import Max
from django.utils.timezone import make_aware
from indexer.models import Transaction
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
from multiprocessing import Process
from django.db import connection
from django import db


def start(worker, total_workers):
    total = Transaction.objects.filter(in_msg_created_lt__isnull=True).count()
    cs = 3000
    per_worker = math.ceil(total / total_workers)

    a = worker * per_worker
    b = (worker + 1) * per_worker

    logger.info(f"Start worker {worker}, per worker: {per_worker}, from {a} to {b}, total: {b - a} / {total}, cs: {cs}")

    go = tqdm(total=math.ceil(per_worker / cs), desc=f"Worker: {worker}")
    for i in range(math.ceil(per_worker / cs)):
        logger.debug(f"Worker {worker}: Fetch from: {a + i * cs} to {a + (i + 1) * cs}")
        c = Transaction.objects.filter(in_msg_created_lt__isnull=True).order_by('gen_utime', 'lt').all()[
            a + i * cs:a + (i + 1) * cs]

        txs = []
        for t in c:
            answer = get_in_msg_info(t.transaction_boc)
            for j in answer:
                setattr(t, j, answer[j])
            txs.append(t)

        Transaction.objects.bulk_update(txs, ['in_msg_comment', 'in_msg_created_lt', 'in_msg_value_grams',
                                              'in_msg_created_at', 'in_msg_hash', 'in_msg_src_addr_workchain_id',
                                              'in_msg_src_addr_address_hex'])
        go.update(1)


class Command(BaseCommand):
    help = 'My custom management command'

    def add_arguments(self, parser):
        parser.add_argument('worker')
        parser.add_argument('total_workers')

    def handle(self, *args, **options):
        worker = int(options['worker'])
        total_workers = int(options['total_workers'])
        start(worker, total_workers)
