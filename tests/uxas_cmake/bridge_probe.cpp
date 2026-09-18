#include "BridgeBuildCapabilities.h"
#if !UXAS_ENABLE_SERIAL
#include "../../OpenUxAS/src/cpp/Communications/LmcpObjectNetworkSerialBridge.h"
#include "../../OpenUxAS/src/cpp/Includes/TypeDefs/UxAS_TypeDefs_Serial.h"
#endif
#if !UXAS_ENABLE_ZYRE
#include "../../OpenUxAS/src/cpp/Communications/LmcpObjectNetworkZeroMqZyreBridge.h"
#include "../../OpenUxAS/src/cpp/Communications/ZeroMqZyreBridge.h"
#include "../../OpenUxAS/src/cpp/Utilities/UxAS_Zyre.h"
#endif
#include <iostream>

int wmain(int argc, wchar_t** argv)
{
    if (argc != 2) { std::cerr << "Expected one XML configuration path\n"; return 2; }
    pugi::xml_document document;
    const pugi::xml_parse_result parsed = document.load_file(argv[1]);
    if (!parsed || !document.child("UxAS"))
    {
        std::cerr << "Invalid UxAS XML: " << parsed.description() << '\n';
        return 100;
    }
    const std::string error = uxas::communications::unavailableConfiguredBridges(document.child("UxAS"));
    if (!error.empty()) { std::cerr << error << '\n'; return 300; }
    std::cout << "BRIDGE_CAPABILITIES_OK serial=" << UXAS_ENABLE_SERIAL << " zyre=" << UXAS_ENABLE_ZYRE << '\n';
    return 0;
}
