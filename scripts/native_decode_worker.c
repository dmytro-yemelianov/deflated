/* Decoder-only timing, preserving the sealed v1 codec/framing implementation. */
#define main v1_encoder_worker_main
#include "native_codec_worker.c"
#undef main

int main(int argc, char **argv) {
    if (argc == 2 && !strcmp(argv[1], "--version")) { version(); return 0; }
    require(argc == 9, "decode worker cold|warm CODEC LEVEL FRAMING PACKET OUTPUT MIN_NS EXPECTED_RAW");
    const char *mode = argv[1], *framing = argv[4];
    require(!strcmp(mode, "cold") || !strcmp(mode, "warm"), "invalid decode timer mode");
    require(!strcmp(argv[2], names[NATIVE_CODEC]), "wrong codec worker");
    int level = level_number(argv[3]); valid_level(level);
    uint64_t minimum = number(argv[7]), declared = number(argv[8]);
    require(declared <= (64 << 20), "output limit");
    require(strcmp(mode, "warm") || minimum > 0, "zero sample duration");
    Buffer packet = read_file(argv[5]);
    /* No encoder, context creation, checksum, or decoder is called here. */
    uint64_t start = clock_ns();
    Buffer raw = decode(packet, (size_t)declared, framing);
    uint64_t first = clock_ns() - start, count = 1;
    double duration = (double)first;
    if (!strcmp(mode, "warm")) {
        Buffer raw_shape = {NULL, (size_t)declared};
        duration = sample(raw_shape, packet, level, framing, 1, minimum, &count);
    }
    write_file(argv[6], raw);
    printf("{\"raw_bytes\":%zu,\"packed_bytes\":%zu,\"decode_ns\":%.9g,"
           "\"first_decode_ns\":%" PRIu64 ",\"decode_iterations\":%" PRIu64 ","
           "\"context\":\"fresh-decoder-only\",\"encoder_calls\":0,\"decode_init_ns\":0}\n",
           raw.size, packet.size, duration, first, count);
    free(raw.data); free(packet.data); return 0;
}
