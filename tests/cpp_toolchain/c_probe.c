#include <Windows.h>
#include <stdint.h>
#include <inttypes.h>
#include <stdio.h>

#if !defined(_M_X64) || !defined(_DLL) || !defined(_MT) || defined(_DEBUG)
#error Expected Release MSVC x64 with /MD
#endif

int main(void)
{
    const int64_t value = INT64_C(9007199254740993);
    if (sizeof(void*) != 8 || sizeof(value) != 8 ||
        value - INT64_C(9007199254740992) != 1 || GetCurrentProcessId() == 0) {
        return 1;
    }
    printf("C_PROBE_OK x64 MD int64=%" PRId64 "\n", value);
    return 0;
}
