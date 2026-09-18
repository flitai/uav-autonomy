#include <Windows.h>
#include <atomic>
#include <chrono>
#include <cstdint>
#include <iostream>
#include <string>
#include <thread>
#include <vector>

#if !defined(_M_X64) || !defined(_DLL) || !defined(_MT) || defined(_DEBUG)
#error Expected Release MSVC x64 with /MD
#endif
static_assert(_MSVC_LANG == 201402L, "Expected /std:c++14");
static_assert(sizeof(void*) == 8, "Expected x64");

int main(int argc, char** argv)
{
    const std::int64_t big = INT64_C(9007199254740993);
    const std::vector<std::int64_t> values{big, big + 1};
    std::atomic<int> count(0);
    const auto started = std::chrono::steady_clock::now();
    auto increment = [&count]() { for (int i = 0; i < 1000; ++i) { ++count; } };
    std::thread first(increment), second(increment);
    first.join();
    second.join();
    if (count != 2000 || values[1] - values[0] != 1 || GetCurrentProcessId() == 0 ||
        std::chrono::steady_clock::now() < started) {
        return 1;
    }
    std::cout << "CPP_PROBE_OK x64 MD c++14 int64=" << big << " threads=" << count << std::endl;
    // Give the acceptance driver time to inspect this process's actual loaded CRTs.
    if (argc == 2 && std::string(argv[1]) == "--inspect-runtime") {
        std::this_thread::sleep_for(std::chrono::seconds(5));
    }
    return 0;
}
