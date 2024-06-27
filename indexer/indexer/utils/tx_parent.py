import requests
from time import sleep
from datetime import timedelta, datetime
import gzip


# def get_parent(tx_hash: str, gen_utime: datetime, lt) -> str:
#     endpoint = 'https://dton.io/graphql/'
#
#     query = '''
#       query {
#         raw_transactions(hash: "%s", gen_utime: "%s", lt: %s){
#             trace_parent_hash
#         }
#       }
#     ''' % (tx_hash, str(gen_utime + timedelta(hours=3))[:-6], lt)
#
#     response = requests.post(endpoint, json={'query': query})
#
#     if response.status_code == 200:
#         data = response.json()['data']
#         return data['raw_transactions'][0]['trace_parent_hash']
#     else:
#         sleep(0.1)
#         return get_parent(tx_hash, gen_utime, lt)

class SuccessTxCache:
    def __init__(self):
        self.cache = None

    def init_cache(self):
        with gzip.open('indexer/data/success_first_wave.data.gz', 'rb') as f:
            file_content = f.read()
        self.cache = set(eval(file_content))

    def __contains__(self, item):
        if self.cache is None:
            self.init_cache()

        return item in self.cache


success_tx_cache = SuccessTxCache()


def check_tx_parent(tx_hash: str):
    # But while we need this only for 14M txs of 80M, we use whitelist (doublechecked with dton / tonapi)
    # It allow fast load
    if tx_hash in success_tx_cache:
        return True, ''
    else:
        return False, 'TX sended >4 times'
