#ifndef UXAS_BRIDGE_BUILD_CAPABILITIES_H
#define UXAS_BRIDGE_BUILD_CAPABILITIES_H

#include "UxAS_BridgeFeatures.h"
#include "pugixml.hpp"
#include <string>

namespace uxas { namespace communications {

// Only checks build capabilities; it neither creates bridges nor opens sockets.
inline std::string unavailableBridgeReason(const std::string& type)
{
#if !UXAS_ENABLE_SERIAL
    if (type == "LmcpObjectNetworkSerialBridge")
        return type + " is unavailable (UXAS_ENABLE_SERIAL=OFF)";
#endif
#if !UXAS_ENABLE_ZYRE
    if (type == "LmcpObjectNetworkZeroMqZyreBridge")
        return type + " is unavailable (UXAS_ENABLE_ZYRE=OFF)";
#endif
    (void)type;
    return std::string();
}

// Accepts either the UxAS root or ConfigurationManager's enabled-bridge container.
inline std::string unavailableConfiguredBridges(const pugi::xml_node& container)
{
    std::string errors;
    for (pugi::xml_node node = container.child("Bridge"); node; node = node.next_sibling("Bridge"))
    {
        const std::string error = unavailableBridgeReason(node.attribute("Type").value());
        if (!error.empty())
        {
            if (!errors.empty()) errors += "; ";
            errors += error;
        }
    }
    return errors;
}

} }
#endif
