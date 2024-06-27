from tonpy import CellSlice, Cell
from tonpy.autogen.block import MessageAny


def get_in_msg_info(tx_boc):
    result = {
        'in_msg_comment': None,
        'in_msg_created_lt': None,
        'in_msg_value_grams': None,
        'in_msg_created_at': None,
        'in_msg_hash': None,
        'in_msg_src_addr_workchain_id': None,
        'in_msg_src_addr_address_hex': None,
    }

    tx = CellSlice(tx_boc)
    r1 = tx.load_ref(as_cs=True)

    maybe = r1.load_uint(1)

    if maybe == 1:
        in_msg = r1.load_ref()

        result['in_msg_hash'] = in_msg.get_hash()

        message_parsed = MessageAny().cell_unpack(in_msg, True)

        result['in_msg_src_addr_workchain_id'] = message_parsed.x.info.src.workchain_id
        result['in_msg_src_addr_address_hex'] = hex(int(message_parsed.x.info.src.address, 2))[2:].zfill(64).upper()
        result['in_msg_created_at'] = message_parsed.x.info.created_at
        result['in_msg_created_lt'] = message_parsed.x.info.created_lt
        result['in_msg_value_grams'] = message_parsed.x.info.value.grams.amount.value

        try:
            cs = message_parsed.x.body.value
            if isinstance(cs, Cell):
                cs = cs.begin_parse()
            cs.skip_bits(32)
            text = cs.load_string()[22:]
            result['in_msg_comment'] = text.replace("\x00", "\uFFFD")
        except Exception as e:
            print(e)
    return result
