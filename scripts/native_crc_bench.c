/* CRC-only diagnostic using the same pinned native libraries as decode. */
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <time.h>
#if NATIVE_CODEC == 2
#include <zlib-ng.h>
#define CRC(data, size) zng_crc32(0, (data), (size))
#elif NATIVE_CODEC == 3
#include <libdeflate.h>
#define CRC(data, size) libdeflate_crc32(0, (data), (size))
#else
#error Select NATIVE_CODEC=2 or 3
#endif
static volatile uint32_t sink;
static uint64_t now(void) {
    struct timespec ts;
    if (clock_gettime(CLOCK_MONOTONIC, &ts)) exit(2);
    return (uint64_t)ts.tv_sec * 1000000000 + (uint64_t)ts.tv_nsec;
}
int main(int argc, char **argv) {
    if (argc != 3) return 2;
    FILE *file = fopen(argv[1], "rb");
    if (!file || fseek(file, 0, SEEK_END)) return 2;
    long length = ftell(file);
    if (length < 0 || length > (64 << 20) || fseek(file, 0, SEEK_SET)) return 2;
    size_t size = (size_t)length;
    uint8_t *data = malloc(size ? size : 1);
    if (!data || fread(data, 1, size, file) != size || fclose(file)) return 2;
    uint64_t minimum = strtoull(argv[2], NULL, 10);
    if (!minimum) return 2;
    uint32_t crc = CRC(data, size);
    uint64_t count = 0, start = now(), elapsed;
    do {
        sink = CRC(data, size);
        count++;
        elapsed = now() - start;
    } while (elapsed < minimum);
    printf("{\"crc32\":%u,\"ns\":%.9g,\"iterations\":%llu}\n", crc,
           (double)elapsed / (double)count, (unsigned long long)count);
    free(data);
    return 0;
}
