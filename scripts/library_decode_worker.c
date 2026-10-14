/* Library restart: time the native raw/gzip APIs, including native checksums.
 * Historical v1 adapters remain unchanged and are not used as gzip decoders.
 */
#define main historical_worker_main
#include "native_codec_worker.c"
#undef main

static Buffer decode_public(Buffer packet, size_t expected, const char *frame) {
    if (!strcmp(frame, "raw")) return decode_codec(packet.data, packet.size, expected);
    require(!strcmp(frame, "gzip"), "invalid framing");
    Buffer out = allocate(expected + 1);
#if NATIVE_CODEC == 2
    Stream state; memset(&state, 0, sizeof(state));
    require(I_INIT(&state, 31) == Z_OK, "gzip init");
    state.next_in = packet.data; state.avail_in = (uint32_t)packet.size;
    state.next_out = out.data; state.avail_out = (uint32_t)out.size;
    int result = I_CALL(&state, Z_FINISH);
    int valid = result == Z_STREAM_END && state.total_in == packet.size && state.total_out == expected;
    require(I_END(&state) == Z_OK, "gzip end");
    require(valid, "gzip decode/consumption/size");
#elif NATIVE_CODEC == 3
    struct libdeflate_decompressor *state = libdeflate_alloc_decompressor();
    require(state != NULL, "gzip init");
    size_t consumed = 0, written = 0;
    enum libdeflate_result result = libdeflate_gzip_decompress_ex(
        state, packet.data, packet.size, out.data, out.size, &consumed, &written);
    libdeflate_free_decompressor(state);
    require(result == LIBDEFLATE_SUCCESS && consumed == packet.size && written == expected,
            "gzip decode/consumption/size");
#else
#error Only zlib-ng and libdeflate are library-v1 references
#endif
    out.size = expected; return out;
}

/* Same API and full validation as fresh calls, retaining both state and output.
 * zlib-ng resets its stream on each call; libdeflate's object is reusable as-is.
 * A worker handles one framing/packet per process; no dictionary is preserved.
 */
static int reuse_initialized;
static Buffer decode_reusing(Buffer packet, size_t expected, const char *frame, Buffer out) {
    int gzip = !strcmp(frame, "gzip");
    require(gzip || !strcmp(frame, "raw"), "invalid framing");
#if NATIVE_CODEC == 2
    if (!reuse_initialized) {
        memset(&cached_dec, 0, sizeof(cached_dec));
        require(I_INIT(&cached_dec, gzip ? 31 : -15) == Z_OK, "reuse init");
        reuse_initialized = 1;
    } else {
        require(I_RESET(&cached_dec) == Z_OK, "reuse reset");
    }
    cached_dec.next_in = packet.data; cached_dec.avail_in = (uint32_t)packet.size;
    cached_dec.next_out = out.data; cached_dec.avail_out = (uint32_t)(expected + 1);
    int result = I_CALL(&cached_dec, Z_FINISH);
    require(result == Z_STREAM_END && cached_dec.total_in == packet.size &&
            cached_dec.total_out == expected, "reuse decode/consumption/size");
#elif NATIVE_CODEC == 3
    if (!reuse_initialized) {
        cached_dec = libdeflate_alloc_decompressor();
        require(cached_dec != NULL, "reuse init");
        reuse_initialized = 1;
    }
    size_t consumed = 0, written = 0;
    enum libdeflate_result result = gzip ?
        libdeflate_gzip_decompress_ex(cached_dec, packet.data, packet.size,
                                     out.data, expected + 1, &consumed, &written) :
        libdeflate_deflate_decompress_ex(cached_dec, packet.data, packet.size,
                                        out.data, expected + 1, &consumed, &written);
    require(result == LIBDEFLATE_SUCCESS && consumed == packet.size && written == expected,
            "reuse decode/consumption/size");
#endif
    out.size = expected;
    return out;
}

int main(int argc, char **argv) {
    if (argc == 2 && !strcmp(argv[1], "--version")) { version(); return 0; }
    require(argc == 9, "decoder warm|cold CODEC LEVEL raw|gzip PACKET OUT MIN_NS EXPECTED");
    int reuse = !strcmp(argv[1], "context-warm") || !strcmp(argv[1], "context-cold");
    int cold = !strcmp(argv[1], "cold") || !strcmp(argv[1], "context-cold");
    require(reuse || cold || !strcmp(argv[1], "warm"), "mode");
    require(!strcmp(argv[2], names[NATIVE_CODEC]), "codec");
    uint64_t expected = number(argv[8]), minimum = number(argv[7]);
    require(expected <= (64 << 20), "output limit");
    require(cold || minimum > 0, "duration");
    Buffer packet = read_file(argv[5]);
    uint64_t start = clock_ns();
    Buffer out = reuse ? decode_reusing(packet, (size_t)expected, argv[4], allocate(expected + 1)) :
                         decode_public(packet, (size_t)expected, argv[4]);
    uint64_t first = clock_ns() - start, count = 1;
    double elapsed = (double)first;
    if (!cold) {
        start = clock_ns(); count = 0;
        do {
            if (reuse) {
                out = decode_reusing(packet, (size_t)expected, argv[4], out);
                if (out.size) sink ^= out.data[out.size - 1];
            } else {
                Buffer next = decode_public(packet, (size_t)expected, argv[4]);
                if (next.size) sink ^= next.data[next.size - 1];
                free(next.data);
            }
            count++;
        } while (clock_ns() - start < minimum);
        elapsed = (double)(clock_ns() - start) / (double)count;
    }
    write_file(argv[6], out);
    printf("{\"decode_ns\":%.9g,\"first_decode_ns\":%" PRIu64 ",\"decode_iterations\":%" PRIu64
           ",\"raw_bytes\":%zu,\"packed_bytes\":%zu,\"context\":\"%s\",\"encoder_calls\":0}\n",
           elapsed, first, count, out.size, packet.size, reuse ? "reuse-state-output" : "fresh-decoder-only");
    if (reuse_initialized) {
#if NATIVE_CODEC == 2
        require(I_END(&cached_dec) == Z_OK, "reuse end");
#elif NATIVE_CODEC == 3
        libdeflate_free_decompressor(cached_dec);
#endif
    }
    free(out.data); free(packet.data); return 0;
}
