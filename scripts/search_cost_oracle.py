"""Short exact fixed-Huffman parse oracle, independent of native match finding.

Optimality is for a single fixed-code block and all legal matches in the input.
It says nothing about dynamic Huffman coding or bounded native candidate sets.
"""
import bisect

LENGTH_BASE = [3, 4, 5, 6, 7, 8, 9, 10, 11, 13, 15, 17, 19, 23, 27, 31,
               35, 43, 51, 59, 67, 83, 99, 115, 131, 163, 195, 227, 258]
LENGTH_EXTRA = [0] * 8 + [1] * 4 + [2] * 4 + [3] * 4 + [4] * 4 + [5] * 4 + [0]
DIST_BASE = [1, 2, 3, 4, 5, 7, 9, 13, 17, 25, 33, 49, 65, 97, 129, 193,
             257, 385, 513, 769, 1025, 1537, 2049, 3073, 4097, 6145,
             8193, 12289, 16385, 24577]
DIST_EXTRA = [0] * 4 + [i for i in range(1, 14) for _ in range(2)]


def match_bits(length, distance):
    if not 3 <= length <= 258 or not 1 <= distance <= 32768:
        raise ValueError('illegal fixed-code match')
    l = bisect.bisect_right(LENGTH_BASE, length) - 1
    d = bisect.bisect_right(DIST_BASE, distance) - 1
    return (7 if 257 + l <= 279 else 8) + LENGTH_EXTRA[l] + 5 + DIST_EXTRA[d]


def literal_bits(byte):
    return 8 if byte <= 143 else 9


def all_edges(raw, position):
    yield 1, literal_bits(raw[position]), ('l', raw[position])
    for distance in range(1, min(position, 32768) + 1):
        length = 0
        while length < min(258, len(raw) - position) and raw[position + length] == raw[position + length - distance]:
            length += 1
        for count in range(3, length + 1):
            yield count, match_bits(count, distance), ('m', count, distance)


def exact(raw):
    if len(raw) > 4096:
        raise ValueError('exact oracle input exceeds 4096-byte research limit')
    # EOB 7 bits; block header 3; final padding is monotonically increasing
    # in token bit cost, so minimizing bits also minimizes byte count.
    costs, decisions = [0] * (len(raw) + 1), [None] * len(raw)
    costs[-1] = 7
    for position in range(len(raw) - 1, -1, -1):
        best = min((bits + costs[position + length], token) for length, bits, token in all_edges(raw, position))
        costs[position], decisions[position] = best
    tokens, position = [], 0
    while position < len(raw):
        token = decisions[position]
        tokens.append(token)
        position += 1 if token[0] == 'l' else token[1]
    return {'fixed_bits': costs[0] + 3, 'packed_bytes': (costs[0] + 10) // 8, 'tokens': tokens}


def longest(raw):
    tokens, position, bits = [], 0, 10
    while position < len(raw):
        length, cost, token = min(all_edges(raw, position), key=lambda edge: (-edge[0], edge[1], edge[2]))
        tokens.append(token)
        bits += cost
        position += length
    return {'fixed_bits': bits, 'packed_bytes': (bits + 7) // 8, 'tokens': tokens}


def expand(tokens):
    output = bytearray()
    for token in tokens:
        if token[0] == 'l':
            output.append(token[1])
        else:
            _, length, distance = token
            if not 3 <= length <= 258 or not 1 <= distance <= min(len(output), 32768):
                raise ValueError('invalid parsed match')
            for _ in range(length):
                output.append(output[-distance])
    return bytes(output)


def native_tokens(tokens):
    return ' '.join(f'l:{t[1]:02x}' if t[0] == 'l' else f'm:{t[1]}:{t[2]}' for t in tokens)
