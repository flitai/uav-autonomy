#include <zmq.h>
#include <chrono>
#include <cstdio>
#include <stdexcept>
#include <string>

// Uses the qualified native ZeroMQ library; no separate Python dependency.
// Output is length-prefixed raw PUB frames, not decoded/repacked LMCP.
int wmain(int argc, wchar_t** argv)
{
    if (argc != 4) return 2;
    FILE* output = nullptr;
    if (_wfopen_s(&output, argv[2], L"wb") || !output) return 3;
    void* context = zmq_ctx_new();
    void* socket = zmq_socket(context, ZMQ_SUB);
    int linger = 0;
    zmq_setsockopt(socket, ZMQ_LINGER, &linger, sizeof(linger));
    const std::wstring wideAddress(argv[1]);
    const std::string address(wideAddress.begin(), wideAddress.end());
    if (zmq_setsockopt(socket, ZMQ_SUBSCRIBE, "", 0) || zmq_connect(socket, address.c_str())) return 4;
    std::puts("SUB_READY"); std::fflush(stdout);
    const auto until = std::chrono::steady_clock::now() + std::chrono::seconds(90);
    int result = 0;
    while (std::chrono::steady_clock::now() < until) {
        FILE* stop = nullptr;
        if (!_wfopen_s(&stop, argv[3], L"rb") && stop) { std::fclose(stop); break; }
        zmq_pollitem_t item{socket, 0, ZMQ_POLLIN, 0};
        if (zmq_poll(&item, 1, 100) < 0) { result = 5; break; }
        if (!(item.revents & ZMQ_POLLIN)) continue;
        zmq_msg_t message;
        zmq_msg_init(&message);
        if (zmq_msg_recv(&message, socket, 0) < 0) { zmq_msg_close(&message); result = 6; break; }
        const auto size = static_cast<unsigned long>(zmq_msg_size(&message));
        const unsigned char length[4] = {static_cast<unsigned char>(size >> 24), static_cast<unsigned char>(size >> 16),
            static_cast<unsigned char>(size >> 8), static_cast<unsigned char>(size)};
        if (std::fwrite(length, 1, 4, output) != 4 || std::fwrite(zmq_msg_data(&message), 1, size, output) != size) result = 7;
        std::fflush(output);
        zmq_msg_close(&message);
        if (result) break;
    }
    std::fclose(output);
    zmq_close(socket);
    zmq_ctx_term(context);
    return result;
}
