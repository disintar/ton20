# Ton-20 index

Public API: [api.tonano.io](https://api.tonano.io/swagger/)

## Index process

1. Index all messages from TON from all shards over `tonpy.blockscanner.blockscanner.BlockScanner` over liteservers
2. Save all ton-20 transactions to DB
    1. All ton-20 logic related is in `ton20logic.py`
    2. State serialization/deserialization `ton20state.py`
3. Load all transactions from latest state (`ton20state.tlb`) and index them
    1. Wallets & ticks & transactions saved to DB separately from state
4. State commited to DB each `COMMIT_STATE_EACH` txs

---
Warning: if your reboot index it will roll-back to latest state in DB including wallets&ticks and index all TXs from
latest state again

## Dumps

1. LiteDump: latest actual state
    1. This is just BOC of latest state if costs several mb and it's fast to download
    2. To do this just run `manage.py get_latest_state https://api.tonano.io/api/v1/latest-state-boc/`
2. PostgresDump: full transactions history dump
    1. It's costs several gb (~160) and it's slow to download, but you will have full history of transactions
    2. Download postgres dump from `TBD`
    3. [OPTIONAL] You can reindex all ton20 index based on RAW data from liteserver: 
       1. Delete all serialized states and transactions status (indexes also if you want faster insert)
       2. Run `manage.py start_ton20` it'll load all transactions and index data from start, it'll take ~8h depends on your
          server

---

## Server requirements

### With liteserver on same node

- 16 cores CPU
- 128 GB RAM
- 1TB NVME
- 1 Gbit/s network connectivity

### Without liteserver on same node

- 64gb RAM
- 16 CPU
- 500gb NVME

## Liteserver

Liteserver stability must be excellent, consider host own node or use [@liteserver_bot](https://t.me/liteserver_bot)
instances

Add your liteserver config to `.env` (check out `.env_example`)

## Hints if you want to index from start

Since there's a lot of TXs to load (~90m) it needed to be setup correctly

1. Remove all indexes on tables for faster push
2. Change `chunk_size` in `start_index.py`. >chunk = faster process, higher RAM usage.