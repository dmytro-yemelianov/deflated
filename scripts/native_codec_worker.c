/* Pinned native-library worker, outside all Rust/Lean verification boundaries.
 * Build one binary per NATIVE_CODEC: no unrelated codec libraries in its RSS.
 * Fresh codec state + output allocation are charged on every ordinary call.
 */
#define _POSIX_C_SOURCE 200809L
#include <errno.h>
#include <inttypes.h>
#include <limits.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#if defined(__APPLE__)
#include <mach/mach_time.h>
#endif

#if NATIVE_CODEC == 1
#include <zlib.h>
#elif NATIVE_CODEC == 2
#include <zlib-ng.h>
#elif NATIVE_CODEC == 3
#include <libdeflate.h>
#elif NATIVE_CODEC == 4
#include <zstd.h>
#elif NATIVE_CODEC == 5
#include <lz4.h>
#include <lz4frame.h>
#elif NATIVE_CODEC == 6
#include <brotli/encode.h>
#include <brotli/decode.h>
#elif NATIVE_CODEC == 7
#include <lzma.h>
#else
#error NATIVE_CODEC must be 1..7
#endif

typedef struct { uint8_t *data; size_t size; } Buffer;
static const char *names[] = {"", "zlib", "zlib-ng", "libdeflate", "zstd", "lz4", "brotli", "lzma2"};
static volatile uint8_t sink;
static int reuse_context;
#if NATIVE_CODEC == 1
typedef z_stream Stream;
#define D_INIT deflateInit2
#define D_BOUND deflateBound
#define D_CALL deflate
#define D_RESET deflateReset
#define D_END deflateEnd
#define I_INIT inflateInit2
#define I_CALL inflate
#define I_RESET inflateReset
#define I_END inflateEnd
#elif NATIVE_CODEC == 2
typedef zng_stream Stream;
#define D_INIT zng_deflateInit2
#define D_BOUND zng_deflateBound
#define D_CALL zng_deflate
#define D_RESET zng_deflateReset
#define D_END zng_deflateEnd
#define I_INIT zng_inflateInit2
#define I_CALL zng_inflate
#define I_RESET zng_inflateReset
#define I_END zng_inflateEnd
#endif
#if NATIVE_CODEC <= 2
static Stream cached_enc, cached_dec;
#elif NATIVE_CODEC == 3
static struct libdeflate_compressor *cached_enc;
static struct libdeflate_decompressor *cached_dec;
#elif NATIVE_CODEC == 4
static ZSTD_CCtx *cached_enc;
static ZSTD_DCtx *cached_dec;
#elif NATIVE_CODEC == 5
static LZ4F_cctx *cached_enc;
static LZ4F_dctx *cached_dec;
#endif

static void fail(const char *reason) { fprintf(stderr, "%s\n", reason); exit(2); }
static void require(int condition, const char *reason) { if (!condition) fail(reason); }
static Buffer allocate(size_t size) {
    Buffer result = {malloc(size ? size : 1), size};
    require(result.data != NULL, "allocation failed");
    return result;
}
static uint64_t clock_ns(void) {
#if defined(__APPLE__)
    /* CLOCK_MONOTONIC on this host quantizes to microseconds. Match Instant's
     * monotonic tick basis instead; no subtraction/calibration of codec time. */
    static mach_timebase_info_data_t scale;
    if (scale.denom == 0) require(mach_timebase_info(&scale) == KERN_SUCCESS, "clock scale failure");
    uint64_t ticks = mach_absolute_time();
    return (ticks / scale.denom) * scale.numer + ((ticks % scale.denom) * scale.numer) / scale.denom;
#else
    struct timespec ts;
    require(clock_gettime(CLOCK_MONOTONIC, &ts) == 0, "clock failure");
    return (uint64_t)ts.tv_sec * UINT64_C(1000000000) + (uint64_t)ts.tv_nsec;
#endif
}
static uint64_t number(const char *text) {
    char *end = NULL; errno = 0;
    require(*text && *text != '-', "invalid unsigned integer");
    unsigned long long result = strtoull(text, &end, 10);
    require(errno == 0 && *end == 0, "invalid unsigned integer");
    return (uint64_t)result;
}
static int level_number(const char *text) {
    char *end = NULL; errno = 0;
    long result = strtol(text, &end, 10);
    require(*text && errno == 0 && *end == 0 && result >= -1 && result <= 12, "invalid level");
    return (int)result;
}
static Buffer read_file(const char *path) {
    FILE *file = fopen(path, "rb"); require(file != NULL, "cannot open input");
    require(fseek(file, 0, SEEK_END) == 0, "seek failure");
    long length = ftell(file); require(length >= 0 && length <= (64 << 20), "input size limit");
    require(fseek(file, 0, SEEK_SET) == 0, "seek failure");
    Buffer result = allocate((size_t)length);
    require(fread(result.data, 1, result.size, file) == result.size, "read failure");
    require(fclose(file) == 0, "close failure");
    return result;
}
static void write_file(const char *path, Buffer value) {
    FILE *file = fopen(path, "wb"); require(file != NULL, "cannot open output");
    require(fwrite(value.data, 1, value.size, file) == value.size, "write failure");
    require(fclose(file) == 0, "close failure");
}
static uint32_t get32(const uint8_t *p) {
    return (uint32_t)p[0] | (uint32_t)p[1] << 8 | (uint32_t)p[2] << 16 | (uint32_t)p[3] << 24;
}
static uint64_t get64(const uint8_t *p) { return get32(p) | (uint64_t)get32(p + 4) << 32; }
static void put16(uint8_t *p, uint16_t x) { p[0] = (uint8_t)x; p[1] = (uint8_t)(x >> 8); }
static void put32(uint8_t *p, uint32_t x) { for (int i = 0; i < 4; i++) p[i] = (uint8_t)(x >> (8 * i)); }
static void put64(uint8_t *p, uint64_t x) { for (int i = 0; i < 8; i++) p[i] = (uint8_t)(x >> (8 * i)); }

/* Same reflected CRC polynomial as the core. The build generator emits this
 * immutable table; no precomputed file-specific checksum enters a timer. */
#include "native_crc32_table.h"
static uint32_t checksum(const uint8_t *data, size_t size) {
    uint32_t crc = UINT32_MAX;
    for (size_t i = 0; i < size; i++) crc = crc_table[(crc ^ data[i]) & 255] ^ (crc >> 8);
    return crc ^ UINT32_MAX;
}

#if NATIVE_CODEC <= 3
static const uint8_t gzip_header[] = {31, 139, 8, 0, 0, 0, 0, 0, 0, 255};
static void zip_headers(uint8_t *local, uint8_t *central, uint8_t *end,
                        uint32_t crc, uint32_t packed, uint32_t raw) {
    /* ASCII filename data.bin, DOS 1980-01-01 00:00, no extras/comment/descriptor. */
    memset(local, 0, 38); memset(central, 0, 54); memset(end, 0, 22);
    put32(local, 0x04034b50); put16(local + 4, 20); put16(local + 8, 8);
    put16(local + 12, 0x21); put32(local + 14, crc); put32(local + 18, packed);
    put32(local + 22, raw); put16(local + 26, 8); memcpy(local + 30, "data.bin", 8);
    put32(central, 0x02014b50); put16(central + 4, 20); put16(central + 6, 20);
    put16(central + 10, 8); put16(central + 14, 0x21); put32(central + 16, crc);
    put32(central + 20, packed); put32(central + 24, raw); put16(central + 28, 8);
    memcpy(central + 46, "data.bin", 8);
    put32(end, 0x06054b50); put16(end + 8, 1); put16(end + 10, 1);
    put32(end + 12, 54); put32(end + 16, 38 + packed);
}
static Buffer wrap(Buffer packet, const uint8_t *raw, size_t size, const char *framing) {
    if (!strcmp(framing, "raw")) return packet;
    uint32_t crc = checksum(raw, size);
    Buffer result;
    if (!strcmp(framing, "gzip")) {
        result = allocate(packet.size + 18);
        memcpy(result.data, gzip_header, 10); memcpy(result.data + 10, packet.data, packet.size);
        put32(result.data + 10 + packet.size, crc); put32(result.data + 14 + packet.size, (uint32_t)size);
    } else {
        require(!strcmp(framing, "zip"), "invalid DEFLATE framing");
        result = allocate(packet.size + 114);
        zip_headers(result.data, result.data + 38 + packet.size,
                    result.data + 92 + packet.size, crc, (uint32_t)packet.size, (uint32_t)size);
        memcpy(result.data + 38, packet.data, packet.size);
    }
    free(packet.data);
    return result;
}
#endif

static Buffer encode_codec(const uint8_t *raw, size_t size, int level) {
    Buffer result;
#if NATIVE_CODEC <= 2
    Stream local = {0}; Stream *state = reuse_context ? &cached_enc : &local;
    if (reuse_context) require(D_RESET(state) == Z_OK, "deflate reset");
    else require(D_INIT(state, level, Z_DEFLATED, -15, 8, Z_DEFAULT_STRATEGY) == Z_OK, "deflate init");
    result = allocate(D_BOUND(state, size));
    state->next_in = (uint8_t *)raw; state->avail_in = (unsigned int)size;
    state->next_out = result.data; state->avail_out = (unsigned int)result.size;
    int code = D_CALL(state, Z_FINISH); result.size = state->total_out;
    require(code == Z_STREAM_END && state->total_in == size, "deflate encode");
    if (!reuse_context) require(D_END(state) == Z_OK, "deflate end");
#elif NATIVE_CODEC == 3
    struct libdeflate_compressor *state = reuse_context ? cached_enc : libdeflate_alloc_compressor(level);
    require(state != NULL, "libdeflate init");
    result = allocate(libdeflate_deflate_compress_bound(state, size));
    result.size = libdeflate_deflate_compress(state, raw, size, result.data, result.size);
    require(result.size != 0, "libdeflate encode"); if (!reuse_context) libdeflate_free_compressor(state);
#elif NATIVE_CODEC == 4
    ZSTD_CCtx *state = reuse_context ? cached_enc : ZSTD_createCCtx(); require(state != NULL, "zstd init");
    if (reuse_context) require(!ZSTD_isError(ZSTD_CCtx_reset(state, ZSTD_reset_session_only)), "zstd reset");
    require(!ZSTD_isError(ZSTD_CCtx_setParameter(state, ZSTD_c_compressionLevel, level)), "zstd level");
    require(!ZSTD_isError(ZSTD_CCtx_setParameter(state, ZSTD_c_checksumFlag, 1)), "zstd checksum");
    require(!ZSTD_isError(ZSTD_CCtx_setParameter(state, ZSTD_c_contentSizeFlag, 1)), "zstd size");
    require(!ZSTD_isError(ZSTD_CCtx_setParameter(state, ZSTD_c_nbWorkers, 0)), "zstd threads");
    result = allocate(ZSTD_compressBound(size));
    result.size = ZSTD_compress2(state, result.data, result.size, raw, size);
    require(!ZSTD_isError(result.size), "zstd encode");
    if (!reuse_context) require(!ZSTD_isError(ZSTD_freeCCtx(state)), "zstd end");
#elif NATIVE_CODEC == 5
    LZ4F_preferences_t settings = LZ4F_INIT_PREFERENCES;
    settings.frameInfo.contentSize = size; /* The API omits the size field for empty input. */
    settings.frameInfo.contentChecksumFlag = LZ4F_contentChecksumEnabled;
    settings.frameInfo.blockChecksumFlag = LZ4F_blockChecksumEnabled;
    settings.compressionLevel = level;
    result = allocate(LZ4F_compressFrameBound(size, &settings));
    if (reuse_context) {
        settings.autoFlush = 1;
        settings.frameInfo.blockSizeID = LZ4F_max64KB;
        if (size <= 65536) settings.frameInfo.blockMode = LZ4F_blockIndependent;
        LZ4F_compressOptions_t options = {0}; options.stableSrc = 1;
        size_t header = LZ4F_compressBegin(cached_enc, result.data, result.size, &settings);
        require(!LZ4F_isError(header), "lz4 begin");
        size_t encoded = LZ4F_compressUpdate(cached_enc, result.data + header, result.size - header, raw, size, &options);
        require(!LZ4F_isError(encoded), "lz4 update");
        size_t end = LZ4F_compressEnd(cached_enc, result.data + header + encoded, result.size - header - encoded, &options);
        require(!LZ4F_isError(end), "lz4 end"); result.size = header + encoded + end;
    } else result.size = LZ4F_compressFrame(result.data, result.size, raw, size, &settings);
    require(!LZ4F_isError(result.size), "lz4 encode");
#elif NATIVE_CODEC == 6
    size_t capacity = BrotliEncoderMaxCompressedSize(size);
    require(capacity > 0, "brotli bound"); result = allocate(capacity + 16);
    memcpy(result.data, "BRF1", 4); put64(result.data + 4, size); put32(result.data + 12, checksum(raw, size));
    size_t encoded = capacity;
    require(BrotliEncoderCompress(level, 22, BROTLI_MODE_GENERIC, size, raw, &encoded, result.data + 16), "brotli encode");
    result.size = encoded + 16;
#elif NATIVE_CODEC == 7
    result = allocate(lzma_stream_buffer_bound(size)); size_t position = 0;
    require(lzma_easy_buffer_encode((uint32_t)level, LZMA_CHECK_CRC32, NULL,
                                   raw, size, result.data, &position, result.size) == LZMA_OK, "lzma2 encode");
    result.size = position;
#endif
    return result;
}

static Buffer encode(const uint8_t *raw, size_t size, int level, const char *framing) {
    Buffer packet = encode_codec(raw, size, level);
#if NATIVE_CODEC <= 3
    return wrap(packet, raw, size, framing);
#else
    require(!strcmp(framing, "frame"), "invalid native framing"); return packet;
#endif
}

static Buffer decode_codec(const uint8_t *packet, size_t size, size_t expected) {
    Buffer out = allocate(expected + 1);
#if NATIVE_CODEC <= 2
    Stream local = {0}; Stream *state = reuse_context ? &cached_dec : &local;
    if (reuse_context) require(I_RESET(state) == Z_OK, "inflate reset");
    else require(I_INIT(state, -15) == Z_OK, "inflate init");
    state->next_in = (uint8_t *)packet; state->avail_in = (unsigned int)size;
    state->next_out = out.data; state->avail_out = (unsigned int)out.size;
    int code = I_CALL(state, Z_FINISH);
    require(code == Z_STREAM_END && state->total_in == size && state->total_out == expected, "inflate decode/consumption");
    if (!reuse_context) require(I_END(state) == Z_OK, "inflate end");
#elif NATIVE_CODEC == 3
    struct libdeflate_decompressor *state = reuse_context ? cached_dec : libdeflate_alloc_decompressor(); require(state != NULL, "libdeflate decode init");
    size_t consumed = 0, written = 0;
    require(libdeflate_deflate_decompress_ex(state, packet, size, out.data, out.size,
                                           &consumed, &written) == LIBDEFLATE_SUCCESS
            && consumed == size && written == expected, "libdeflate decode/consumption");
    if (!reuse_context) libdeflate_free_decompressor(state);
#elif NATIVE_CODEC == 4
    require(size >= 5 && get32(packet) == 0xfd2fb528 && (packet[4] & 4), "zstd frame/checksum");
    require(ZSTD_findFrameCompressedSize(packet, size) == size
            && ZSTD_getFrameContentSize(packet, size) == expected, "zstd frame size/consumption");
    ZSTD_DCtx *state = reuse_context ? cached_dec : ZSTD_createDCtx(); require(state != NULL, "zstd decode init");
    if (reuse_context) require(!ZSTD_isError(ZSTD_DCtx_reset(state, ZSTD_reset_session_only)), "zstd decode reset");
    size_t written = ZSTD_decompressDCtx(state, out.data, out.size, packet, size);
    require(!ZSTD_isError(written) && written == expected, "zstd decode");
    if (!reuse_context) require(!ZSTD_isError(ZSTD_freeDCtx(state)), "zstd decode end");
#elif NATIVE_CODEC == 5
    LZ4F_dctx *state = cached_dec;
    if (reuse_context) LZ4F_resetDecompressionContext(state);
    else require(!LZ4F_isError(LZ4F_createDecompressionContext(&state, LZ4F_VERSION)), "lz4 decode init");
    LZ4F_frameInfo_t info = LZ4F_INIT_FRAMEINFO; size_t consumed = size;
    size_t hint = LZ4F_getFrameInfo(state, &info, packet, &consumed);
    require(!LZ4F_isError(hint) && info.contentSize == expected
            && info.contentChecksumFlag == LZ4F_contentChecksumEnabled
            && info.blockChecksumFlag == LZ4F_blockChecksumEnabled
            && info.blockSizeID == LZ4F_max64KB
            && info.blockMode == (expected <= 65536 ? LZ4F_blockIndependent : LZ4F_blockLinked), "lz4 frame settings");
    size_t written = 0;
    while (hint != 0) {
        size_t input = size - consumed, output = out.size - written;
        hint = LZ4F_decompress(state, out.data + written, &output, packet + consumed, &input, NULL);
        require(!LZ4F_isError(hint) && (hint == 0 || input || output), "lz4 decode/progress");
        consumed += input; written += output;
    }
    require(consumed == size && written == expected, "lz4 consumption/size");
    if (!reuse_context) require(!LZ4F_isError(LZ4F_freeDecompressionContext(state)), "lz4 decode end");
#elif NATIVE_CODEC == 6
    require(size >= 16 && !memcmp(packet, "BRF1", 4) && get64(packet + 4) == expected, "brotli frame");
    BrotliDecoderState *state = BrotliDecoderCreateInstance(NULL, NULL, NULL); require(state != NULL, "brotli decode init");
    size_t input = size - 16, output = out.size, written = 0;
    const uint8_t *source = packet + 16; uint8_t *destination = out.data;
    BrotliDecoderResult code = BrotliDecoderDecompressStream(state, &input, &source, &output, &destination, &written);
    require(code == BROTLI_DECODER_RESULT_SUCCESS && input == 0 && written == expected, "brotli decode/consumption");
    BrotliDecoderDestroyInstance(state);
    require(checksum(out.data, expected) == get32(packet + 12), "brotli crc");
#elif NATIVE_CODEC == 7
    static const uint8_t magic[] = {253, 55, 122, 88, 90, 0};
    require(size >= 24 && !memcmp(packet, magic, 6) && packet[6] == 0 && packet[7] == LZMA_CHECK_CRC32, "xz frame/checksum");
    size_t consumed = 0, written = 0; uint64_t memory_limit = UINT64_MAX;
    require(lzma_stream_buffer_decode(&memory_limit, 0, NULL, packet, &consumed, size,
                                     out.data, &written, out.size) == LZMA_OK
            && consumed == size && written == expected, "lzma2 decode/consumption");
#endif
    out.size = expected; return out;
}

static Buffer decode(Buffer packet, size_t expected, const char *framing) {
#if NATIVE_CODEC <= 3
    size_t offset = 0, stored = packet.size; uint32_t declared_crc = 0;
    if (!strcmp(framing, "gzip")) {
        require(packet.size >= 18 && !memcmp(packet.data, gzip_header, 10), "gzip header");
        offset = 10; stored -= 18;
        declared_crc = get32(packet.data + 10 + stored);
        require(get32(packet.data + 14 + stored) == expected, "gzip length");
    } else if (!strcmp(framing, "zip")) {
        require(packet.size >= 114, "zip length"); offset = 38; stored -= 114;
        declared_crc = get32(packet.data + 14);
        uint8_t local[38], central[54], end[22];
        zip_headers(local, central, end, declared_crc, (uint32_t)stored, (uint32_t)expected);
        require(!memcmp(local, packet.data, 38) && !memcmp(central, packet.data + 38 + stored, 54)
                && !memcmp(end, packet.data + 92 + stored, 22), "zip headers");
    } else require(!strcmp(framing, "raw"), "invalid DEFLATE framing");
    Buffer out = decode_codec(packet.data + offset, stored, expected);
    if (offset) require(checksum(out.data, expected) == declared_crc, "container checksum");
    return out;
#else
    require(!strcmp(framing, "frame"), "invalid native framing"); return decode_codec(packet.data, packet.size, expected);
#endif
}

static void valid_level(int level) {
#if NATIVE_CODEC == 1 || NATIVE_CODEC == 2
    require(level == 1 || level == 6 || level == 9, "level outside preregistered roster");
#elif NATIVE_CODEC == 3
    require(level == 1 || level == 6 || level == 9 || level == 12, "level outside preregistered roster");
#elif NATIVE_CODEC == 4
    require(level == -1 || level == 1 || level == 3 || level == 9, "level outside preregistered roster");
#elif NATIVE_CODEC == 5
    require(level == 0 || level == 9, "level outside preregistered roster");
#elif NATIVE_CODEC == 6
    require(level == 1 || level == 5 || level == 9, "level outside preregistered roster");
#elif NATIVE_CODEC == 7
    require(level == 1 || level == 6, "level outside preregistered roster");
#endif
}

static void init_contexts(int level, uint64_t *encode_init, uint64_t *decode_init) {
#if NATIVE_CODEC > 5
    (void)level; *encode_init = 0; *decode_init = 0; return;
#else
    uint64_t start = clock_ns();
#if NATIVE_CODEC <= 2
    require(D_INIT(&cached_enc, level, Z_DEFLATED, -15, 8, Z_DEFAULT_STRATEGY) == Z_OK, "cached deflate init");
#elif NATIVE_CODEC == 3
    cached_enc = libdeflate_alloc_compressor(level); require(cached_enc != NULL, "cached libdeflate init");
#elif NATIVE_CODEC == 4
    (void)level; cached_enc = ZSTD_createCCtx(); require(cached_enc != NULL, "cached zstd init");
#elif NATIVE_CODEC == 5
    (void)level; require(!LZ4F_isError(LZ4F_createCompressionContext(&cached_enc, LZ4F_VERSION)), "cached lz4 init");
#else
    (void)level;
#endif
    *encode_init = clock_ns() - start; start = clock_ns();
#if NATIVE_CODEC <= 2
    require(I_INIT(&cached_dec, -15) == Z_OK, "cached inflate init");
#elif NATIVE_CODEC == 3
    cached_dec = libdeflate_alloc_decompressor(); require(cached_dec != NULL, "cached libdeflate decode init");
#elif NATIVE_CODEC == 4
    cached_dec = ZSTD_createDCtx(); require(cached_dec != NULL, "cached zstd decode init");
#elif NATIVE_CODEC == 5
    require(!LZ4F_isError(LZ4F_createDecompressionContext(&cached_dec, LZ4F_VERSION)), "cached lz4 decode init");
#endif
    *decode_init = clock_ns() - start;
#endif
}
static void end_contexts(void) {
#if NATIVE_CODEC <= 2
    require(D_END(&cached_enc) == Z_OK && I_END(&cached_dec) == Z_OK, "cached deflate/inflate end");
#elif NATIVE_CODEC == 3
    libdeflate_free_compressor(cached_enc); libdeflate_free_decompressor(cached_dec);
#elif NATIVE_CODEC == 4
    require(!ZSTD_isError(ZSTD_freeCCtx(cached_enc)) && !ZSTD_isError(ZSTD_freeDCtx(cached_dec)), "cached zstd end");
#elif NATIVE_CODEC == 5
    require(!LZ4F_isError(LZ4F_freeCompressionContext(cached_enc)) && !LZ4F_isError(LZ4F_freeDecompressionContext(cached_dec)), "cached lz4 end");
#endif
}
static void reset_check(Buffer a, Buffer b, const char *output, int level, const char *framing) {
    reuse_context = 0;
    Buffer expected_a = encode(a.data, a.size, level, framing), expected_b = encode(b.data, b.size, level, framing);
    uint64_t init_enc, init_dec; reuse_context = 1; init_contexts(level, &init_enc, &init_dec);
    Buffer inputs[] = {a, b, a}; Buffer packets[] = {expected_a, expected_b, expected_a};
    for (int i = 0; i < 3; i++) {
        Buffer actual = encode(inputs[i].data, inputs[i].size, level, framing);
        require(actual.size == packets[i].size && !memcmp(actual.data, packets[i].data, actual.size), "reset packet identity");
        Buffer raw = decode(actual, inputs[i].size, framing);
        require(raw.size == inputs[i].size && !memcmp(raw.data, inputs[i].data, raw.size), "reset decoded identity");
        free(actual.data); free(raw.data);
    }
    end_contexts(); write_file(output, expected_b);
    printf("{\"reset_check\":\"passed-A-B-A\",\"encode_init_ns\":%" PRIu64 ",\"decode_init_ns\":%" PRIu64 "}\n", init_enc, init_dec);
    free(expected_a.data); free(expected_b.data);
}
static double sample(Buffer input, Buffer packet, int level, const char *framing,
                     int decoding, uint64_t minimum, uint64_t *iterations) {
    uint64_t start = clock_ns(), elapsed;
    *iterations = 0;
    do {
        Buffer result = decoding ? decode(packet, input.size, framing) : encode(input.data, input.size, level, framing);
        if (result.size) sink ^= result.data[0];
        free(result.data); (*iterations)++; elapsed = clock_ns() - start;
    } while (elapsed < minimum);
    return (double)elapsed / (double)*iterations;
}
static void version(void) {
#if NATIVE_CODEC == 1
    printf("{\"codec\":\"zlib\",\"version\":\"%s\"}\n", zlibVersion());
#elif NATIVE_CODEC == 2
    printf("{\"codec\":\"zlib-ng\",\"version\":\"%s\"}\n", zlibng_version());
#elif NATIVE_CODEC == 3
    printf("{\"codec\":\"libdeflate\",\"version\":\"%s\",\"version_origin\":\"sealed header; library has no runtime version API\"}\n", LIBDEFLATE_VERSION_STRING);
#elif NATIVE_CODEC == 4
    printf("{\"codec\":\"zstd\",\"version\":\"%s\"}\n", ZSTD_versionString());
#elif NATIVE_CODEC == 5
    printf("{\"codec\":\"lz4\",\"version\":\"%s\"}\n", LZ4_versionString());
#elif NATIVE_CODEC == 6
    printf("{\"codec\":\"brotli\",\"version_integer\":%u}\n", BrotliEncoderVersion());
#elif NATIVE_CODEC == 7
    printf("{\"codec\":\"lzma2\",\"version\":\"%s\"}\n", lzma_version_string());
#endif
}
int main(int argc, char **argv) {
    if (argc == 2 && !strcmp(argv[1], "--version")) { version(); return 0; }
    if (argc == 2 && !strcmp(argv[1], "--clock")) {
        uint64_t previous = clock_ns(), smallest = UINT64_MAX;
        for (int i = 0; i < 10000; i++) { uint64_t now = clock_ns(); if (now > previous && now - previous < smallest) smallest = now - previous; previous = now; }
        printf("{\"minimum_observed_clock_step_ns\":%" PRIu64 "}\n", smallest); return 0;
    }
    require(argc == 9 || (argc == 10 && !strcmp(argv[1], "reset-check")), "worker MODE CODEC LEVEL FRAMING INPUT OUTPUT MIN_NS EXPECTED_RAW [SECOND_INPUT for reset-check]");
    const char *mode = argv[1], *framing = argv[4];
    require(!strcmp(argv[2], names[NATIVE_CODEC]), "wrong codec worker");
    int level = level_number(argv[3]); valid_level(level);
    uint64_t minimum = number(argv[7]), declared = number(argv[8]);
    require(declared <= (64 << 20), "output limit");
    Buffer input = read_file(argv[5]);
    if (!strcmp(mode, "reset-check")) {
        require(argc == 10, "reset-check needs a second input");
        Buffer second = read_file(argv[9]); reset_check(input, second, argv[6], level, framing);
        free(input.data); free(second.data); return 0;
    }
    if (!strcmp(mode, "decode") || !strcmp(mode, "memory-decode")) {
        Buffer raw = decode(input, (size_t)declared, framing); write_file(argv[6], raw);
        printf("{\"raw_bytes\":%zu,\"packed_bytes\":%zu}\n", raw.size, input.size);
        free(raw.data); free(input.data); return 0;
    }
    require(!strcmp(mode, "encode") || !strcmp(mode, "memory-encode") || !strcmp(mode, "warm") || !strcmp(mode, "cold")
            || !strcmp(mode, "reuse-warm") || !strcmp(mode, "reuse-cold"), "invalid mode");
    uint64_t init_enc = 0, init_dec = 0;
    reuse_context = !strcmp(mode, "reuse-warm") || !strcmp(mode, "reuse-cold");
    if (reuse_context) init_contexts(level, &init_enc, &init_dec);
    uint64_t start = clock_ns(); Buffer packet = encode(input.data, input.size, level, framing);
    uint64_t first_encode = clock_ns() - start;
    if (!strcmp(mode, "encode") || !strcmp(mode, "memory-encode")) {
        write_file(argv[6], packet);
        printf("{\"raw_bytes\":%zu,\"packed_bytes\":%zu}\n", input.size, packet.size);
        free(packet.data); free(input.data); return 0;
    }
    start = clock_ns(); Buffer raw = decode(packet, input.size, framing); uint64_t first_decode = clock_ns() - start;
    require(raw.size == input.size && !memcmp(raw.data, input.data, input.size), "roundtrip mismatch"); free(raw.data);
    uint64_t enc_count = 1, dec_count = 1;
    double enc = (double)first_encode, dec = (double)first_decode;
    if (!strcmp(mode, "warm") || !strcmp(mode, "reuse-warm")) {
        require(minimum > 0, "zero sample duration");
        enc = sample(input, packet, level, framing, 0, minimum, &enc_count);
        dec = sample(input, packet, level, framing, 1, minimum, &dec_count);
    }
    if (reuse_context) {
        Buffer repeated = encode(input.data, input.size, level, framing);
        require(repeated.size == packet.size && !memcmp(repeated.data, packet.data, packet.size), "reused sample packet identity");
        free(repeated.data);
    }
    write_file(argv[6], packet);
    printf("{\"raw_bytes\":%zu,\"packed_bytes\":%zu,\"encode_ns\":%.9g,\"decode_ns\":%.9g,\"first_encode_ns\":%" PRIu64 ",\"first_decode_ns\":%" PRIu64 ",\"encode_iterations\":%" PRIu64 ",\"decode_iterations\":%" PRIu64 ",\"context\":\"%s\",\"encode_init_ns\":%" PRIu64 ",\"decode_init_ns\":%" PRIu64 "}\n",
           input.size, packet.size, enc, dec, first_encode, first_decode, enc_count, dec_count,
           reuse_context ? (NATIVE_CODEC <= 5 ? "reused-reset-paid" : "fresh-no-reset-api") : "fresh", init_enc, init_dec);
    if (reuse_context) end_contexts();
    free(packet.data); free(input.data); return 0;
}
