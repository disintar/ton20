from django.core.management import BaseCommand
from django.db import transaction, connection
from indexer.models import Transaction, Ton20StateSerialized, \
    get_field_names
from time import sleep, time
from loguru import logger
from tqdm import tqdm
import orjson as json

from multiprocessing import Pool, set_start_method, get_context, get_start_method
from tonpy.libs.python_ton import globalSetVerbosity

from indexer.utils.ton20logic import Ton20Logic
from django.conf import settings

globalSetVerbosity(2)

def process_new_transaction(logic, latest_lt, latest_hash, batch_size=1000):
    allow_next = latest_hash is None

    with connection.cursor() as cursor:
        field_names = get_field_names(Transaction)
        fields_str = ", ".join(field_names)

        with transaction.atomic():
            cursor.execute(
                f"DECLARE mycursor CURSOR FOR SELECT {fields_str} FROM {Transaction._meta.db_table} WHERE in_msg_created_lt >= {latest_lt} ORDER BY in_msg_created_lt, in_msg_hash")
            t = tqdm()

            while True:
                cursor.execute(f"FETCH {batch_size} FROM mycursor")
                rows = cursor.fetchall()
                if not rows:
                    break

                for row in rows:
                    row_dict = dict(zip(field_names, row))
                    try:
                        comment = json.loads(row_dict['in_msg_comment'])
                        if not isinstance(comment, dict):
                            comment = {}
                    except KeyboardInterrupt:
                        raise KeyboardInterrupt
                    except Exception as e:
                        comment = {}

                    row_dict['in_msg_comment'] = comment
                    if allow_next:
                        logic.add_transaction(row_dict)

                        latest_lt = row_dict['in_msg_created_lt']
                        latest_hash = row_dict['in_msg_hash']
                    else:
                        if row_dict['in_msg_created_lt'] == latest_lt and row_dict['in_msg_hash'] == latest_hash:
                            allow_next = True
                            logger.info(f"Founded last state hash: {latest_hash}, start index from it")

                    t.update(1)
            cursor.execute("CLOSE mycursor")

    logic.state.save_to_db()
    return latest_lt, latest_hash


def batched_query(queryset, batch_size=1000):
    total = queryset.count()
    for start in range(0, total, batch_size):
        t = time()
        f = True
        end = min(start + batch_size, total)
        logger.info(f"Request batch: {start} / {end}")

        for entry in queryset[start:end]:
            if f:
                f = False
                logger.info(f"Request batch: {start} / {end} at {time() - t}")

            yield entry


def start():
    logger.info(f"Start ton20logic")
    # TransactionStatus.objects.all().delete()
    # Ton20StateSerialized.objects.all().delete()

    logic = Ton20Logic(commit_state_each_x_txs=settings.COMMIT_STATE_EACH)
    state = Ton20StateSerialized.get_latest_state()

    if state is None:
        latest_lt = 0
        latest_hash = None
    else:
        latest_lt = state.in_msg_created_lt
        latest_hash = state.transaction_hash
        logic.state.deserialize(state.state_boc,
                                latest_lt,
                                latest_hash)

    if not get_start_method(allow_none=True):
        set_start_method("spawn")

    latest_lt, latest_hash = process_new_transaction(logic, latest_lt, latest_hash)

    while True:
        latest = Transaction.objects.filter(in_msg_created_lt__gte=latest_lt).count()
        if latest == 0:
            sleep(1)
        else:
            logger.info(f"Latest lt: {latest_lt}, {latest_hash}, got: {latest}")
            new_latest_lt, new_latest_hash = process_new_transaction(logic, latest_lt, latest_hash)
            if new_latest_hash != latest_hash:
                logic.state.save_to_db()
            else:
                sleep(1)

            latest_lt = new_latest_lt
            latest_hash = new_latest_hash


class Command(BaseCommand):
    help = 'Start ton20 index'

    def handle(self, *args, **options):
        start()
