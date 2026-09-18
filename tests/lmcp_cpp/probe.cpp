// File-only C++11-compatible acceptance probe; the Windows build uses /std:c++14.
#include "avtas/lmcp/Factory.h"
#include "avtas/lmcp/Object.h"
#include "afrl/cmasi/AirVehicleState.h"
#include "uxas/messages/task/TaskActive.h"
#include <algorithm>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <iterator>
#include <map>
#include <memory>
#include <numeric>
#include <sstream>
#include <stdexcept>
#include <vector>

using avtas::lmcp::ByteBuffer;
using avtas::lmcp::Factory;
using avtas::lmcp::Object;
using afrl::cmasi::AirVehicleState;
using uxas::messages::task::TaskActive;
typedef std::vector<uint8_t> Bytes;
static void require(bool value, const char* message) { if (!value) throw std::runtime_error(message); }
static Bytes read(const std::wstring& file) {
    std::ifstream stream(file.c_str(), std::ios::binary);
    require(bool(stream), "Missing input file");
    return Bytes(std::istreambuf_iterator<char>(stream), std::istreambuf_iterator<char>());
}
static void write(const std::wstring& file, const Bytes& bytes) {
    std::ofstream stream(file.c_str(), std::ios::binary);
    stream.write(reinterpret_cast<const char*>(bytes.data()), bytes.size());
    require(bool(stream), "Could not write sample");
}
static uint32_t big32(const Bytes& b, size_t offset) {
    return (uint32_t(b.at(offset)) << 24) | (uint32_t(b.at(offset+1)) << 16) |
        (uint32_t(b.at(offset+2)) << 8) | uint32_t(b.at(offset+3));
}
static std::unique_ptr<Object> decode(const Bytes& bytes) {
    // This guard belongs to the acceptance probe, not the generated library.
    // Factories intentionally allow checksum=0; they are not complete framing guards.
    require(bytes.size() >= 27 && big32(bytes, 0) == 0x4c4d4350, "Invalid LMCP header");
    require(uint64_t(big32(bytes, 4)) + 12 == bytes.size(), "Invalid LMCP length");
    const uint32_t checksum = big32(bytes, bytes.size()-4);
    const uint32_t calculated = std::accumulate(bytes.begin(), bytes.end()-4, uint32_t(0));
    require(checksum == 0 || checksum == calculated, "Invalid LMCP checksum");
    require(Factory::validate(bytes.data(), static_cast<uint32_t>(bytes.size())), "Factory checksum rejected");
    ByteBuffer buffer;
    buffer.allocate(static_cast<uint32_t>(bytes.size()));
    buffer.put(bytes.data(), static_cast<uint32_t>(bytes.size())); buffer.rewind();
    std::unique_ptr<Object> object(Factory::getObject(buffer));
    require(bool(object), "Unsupported LMCP type or version");
    require(buffer.position() + 4 == bytes.size(), "Decoded size differs from frame");
    return object;
}
static Bytes encode(const Object* object, bool checksum) {
    std::unique_ptr<ByteBuffer> buffer(Factory::packMessage(object, checksum));
    require(bool(buffer), "Could not pack object");
    return Bytes(buffer->array(), buffer->array() + buffer->capacity());
}
static std::string describe(Object* object) {
    std::ostringstream out; out << std::setprecision(17);
    out << "{\"type\":\"" << object->getFullLmcpTypeName() << "\",\"version\":" << object->getSeriesVersion();
    if (AirVehicleState* s = dynamic_cast<AirVehicleState*>(object)) {
        out << ",\"ID\":\"" << s->getID() << "\",\"Time\":\"" << s->getTime() << "\",\"Latitude\":" << s->getLocation()->getLatitude()
            << ",\"Longitude\":" << s->getLocation()->getLongitude() << ",\"Altitude\":" << s->getLocation()->getAltitude()
            << ",\"AltitudeType\":\"" << afrl::cmasi::AltitudeType::get_string(s->getLocation()->getAltitudeType())
            << "\",\"Heading\":" << s->getHeading() << ",\"Airspeed\":" << s->getAirspeed() << ",\"AssociatedTasks\":[";
        for (size_t i=0; i<s->getAssociatedTasks().size(); ++i) {
            if (i) out << ',';
            out << '"' << s->getAssociatedTasks()[i] << '"';
        }
        out << ']';
    } else if (const TaskActive* task = dynamic_cast<const TaskActive*>(object)) {
        out << ",\"TaskID\":\"" << task->getTaskID() << "\",\"EntityID\":\"" << task->getEntityID()
            << "\",\"TimeTaskActivated\":\"" << task->getTimeTaskActivated() << '"';
    } else throw std::runtime_error("Unexpected sample type");
    return out.str() + "}";
}
static std::map<std::string, std::unique_ptr<Object> > objects(const std::wstring& fixture) {
    std::ifstream stream(fixture.c_str()); require(bool(stream), "Missing fixture");
    std::map<std::string, std::string> p;
    std::string line;
    while (std::getline(stream, line)) {
        const size_t equal = line.find('=');
        if (equal != std::string::npos && line[0] != '#') p[line.substr(0,equal)] = line.substr(equal+1);
    }
    std::map<std::string, std::unique_ptr<Object> > result;
    for (const std::string label : {"basic", "wide"}) {
        std::unique_ptr<AirVehicleState> s(new AirVehicleState());
        s->setID(std::stoll(p.at(label+".id"))); s->setTime(std::stoll(p.at("time")));
        s->setHeading(std::stof(p.at("heading"))); s->setAirspeed(std::stof(p.at("airspeed")));
        s->getLocation()->setLatitude(std::stod(p.at("latitude")));
        s->getLocation()->setLongitude(std::stod(p.at("longitude")));
        s->getLocation()->setAltitude(std::stof(p.at("altitude")));
        s->getLocation()->setAltitudeType(afrl::cmasi::AltitudeType::MSL);
        if (label == "wide") {
            std::istringstream tasks(p.at("wide.tasks")); std::string id;
            while (std::getline(tasks, id, ',')) s->getAssociatedTasks().push_back(std::stoll(id));
        }
        result[label] = std::move(s);
    }
    std::unique_ptr<TaskActive> t(new TaskActive());
    t->setTaskID(std::stoll(p.at("task.id"))); t->setEntityID(std::stoll(p.at("task.entity")));
    t->setTimeTaskActivated(std::stoll(p.at("task.time"))); result["task"] = std::move(t);
    return result;
}
int wmain(int argc, wchar_t** argv) {
    try {
        require(sizeof(void*) == 8 && sizeof(int64_t) == 8, "Expected x64/int64");
        require(argc >= 3, "Expected mode and input");
        const std::wstring mode(argv[1]);
        if (mode == L"decode") {
            const auto object = decode(read(argv[2])); std::cout << describe(object.get()) << '\n'; return 0;
        }
        if (mode == L"inventory") {
            std::ifstream stream(argv[2]); require(bool(stream), "Missing inventory");
            std::string name; int64_t series; uint32_t type; uint16_t version; size_t count=0;
            while (stream >> name >> series >> type >> version) {
                std::unique_ptr<Object> object(Factory::createObject(series, type, version));
                require(object && object->getFullLmcpTypeName() == name && object->getSeriesNameAsLong() == series &&
                        object->getLmcpType() == type && object->getSeriesVersion() == version, "Factory inventory differs");
                // Exercise all seven factory registrations and every message's default binary roundtrip.
                const Bytes frame = encode(object.get(), true);
                const auto copy = decode(frame);
                require(encode(copy.get(), true) == frame, "Default type roundtrip differs");
                ++count;
            }
            require(count == 164, "Expected all 164 model structures");
            std::cout << "INVENTORY_OK 164\n"; return 0;
        }
        require(argc == 4 && (mode == L"emit" || mode == L"verify"), "Expected emit/verify fixture directory");
        auto samples = objects(argv[2]); std::ostringstream fields; fields << '{'; bool first=true;
        for (const auto& item : samples) {
            if (!first) fields << ','; first=false;
            fields << '"' << item.first << "\":" << describe(item.second.get());
            for (const bool checksum : {false, true}) {
                const std::wstring file = std::wstring(argv[3]) + L"/" + std::wstring(item.first.begin(),item.first.end()) +
                    (checksum ? L"-checksum.bin" : L"-zero.bin");
                const Bytes expected = encode(item.second.get(), checksum);
                const Bytes received = mode == L"emit" ? expected : read(file);
                const auto decoded = decode(received);
                require(describe(decoded.get()) == describe(item.second.get()), "Sample fields differ");
                require(received == expected && encode(decoded.get(), checksum) == received, "Raw LMCP bytes differ");
                if (mode == L"emit") write(file, expected);
            }
        }
        fields << "}\n";
        if (mode == L"emit") {
            const std::string json=fields.str(); write(std::wstring(argv[3])+L"/fields.json", Bytes(json.begin(),json.end()));
        }
        std::cout << "SAMPLES_OK 6\n"; return 0;
    } catch (const std::exception& error) { std::cerr << error.what() << '\n'; return 2; }
}
