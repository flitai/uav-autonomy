// File-only acceptance of the same Windows initialization and utility code as UxAS.
#include "UxAS_WindowsEnvironment.h"
#include "FileSystemUtilities.h"
#include "UxAS_FileLogger.h"
#include "UxAS_Time.h"
#include "Permute.h"
#include <boost/filesystem.hpp>
#include <pugixml.hpp>
#include <windows.h>
#include <chrono>
#include <fstream>
#include <iostream>
#include <limits>
#include <stdexcept>
#include <ctime>

static void check(bool value, const char* message)
{
    if (!value) throw std::runtime_error(message);
}

int main(int argc, char** argv)
{
    try
    {
        const std::string globalLocale = std::locale().name();
        uxas::common::initializeWindowsPaths();
        check(std::locale().name() == globalLocale, "global locale changed");
        check(GetACP() == CP_UTF8, "process ACP is not UTF-8");
        check(argc == 3 && std::string(argv[2]) == u8"中文 参数", "UTF-8 argv mismatch");
        const std::string directory = std::string(argv[1]) + u8"/中文 目录";
        std::stringstream errors;
        check(uxas::common::utilities::c_FileSystemUtilities::bCreateDirectory(directory, errors), "directory creation failed");
        const boost::filesystem::path path(directory);
        check(boost::filesystem::path(path.wstring()).string() == directory, "Boost path roundtrip failed");
        const std::string file = directory + u8"/消息.xml";
        pugi::xml_document xml;
        xml.append_child("probe").append_attribute("text") = u8"消息 内容";
        check(xml.save_file(file.c_str()), "XML write failed");
        pugi::xml_document loaded;
        check(loaded.load_file(file.c_str()) && std::string(loaded.child("probe").attribute("text").value()) == u8"消息 内容", "XML read failed");
        bool found = false;
        for (boost::filesystem::directory_iterator i(path), end; i != end; ++i)
            found = found || i->path().filename().string() == u8"消息.xml";
        check(found, "directory enumeration failed");
        uxas::common::log::FileLogger logger;
        check(logger.configure(directory + u8"/真实 日志", false), "logger configure failed");
        std::string log;
        check(logger.openStream(log), "logger open failed");
        check(logger.outputTextToStream(u8"日志 内容 9007199254740993"), "logger write failed");
        check(logger.closeStream(), "logger close failed");
        std::ifstream stream(log, std::ios::binary);
        const std::string text((std::istreambuf_iterator<char>(stream)), std::istreambuf_iterator<char>());
        check(text.find(u8"日志 内容 9007199254740993") != std::string::npos, "real log content differs");
        check(count_each_combination<uint64_t>(2, 3) == 10, "combination differs");
        check(count_each_permutation<uint64_t>(2, 3) == 20, "permutation differs");
        bool overflow = false;
        try { count_each_combination<uint64_t>(100, 100); }
        catch (const std::overflow_error&) { overflow = true; }
        check(overflow, "overflow exception missing");
        _tzset();
        char timezone[64] = {};
        check(GetEnvironmentVariableA("TZ", timezone, sizeof(timezone)) > 0, "process TZ missing");
        long timezoneSeconds = 0;
        check(_get_timezone(&timezoneSeconds) == 0, "CRT timezone query failed");
        check((std::string(timezone) == "UTC0" && timezoneSeconds == 0) ||
              (std::string(timezone) == "PST8PDT" && timezoneSeconds == 28800), "process timezone was not applied");
        auto& time = uxas::common::Time::getInstance();
        const int64_t wall = std::chrono::duration_cast<std::chrono::milliseconds>(std::chrono::system_clock::now().time_since_epoch()).count();
        check(std::llabs(time.getUtcTimeSinceEpoch_ms() - wall) < 1000, "UTC wall milliseconds differ");
        check(time.calibrateWithReferenceUtcTime(2020, 1, 2, 3, 4, 5, 678), "UTC calibration failed");
        const int64_t expected = 1577934245678LL;
        check(std::llabs(time.getUtcTimeSinceEpoch_ms() - expected) < 1000, "UTC date conversion depends on timezone");
        check(time.calibrateWithReferenceUtcTime(2020, 1, 2, 1, 678), "week calibration failed");
        check(std::llabs(time.getUtcTimeSinceEpoch_ms() - 1578528000678LL) < 1000, "week millisecond conversion differs");
        std::cout << "PLATFORM_OK ACP=" << GetACP() << " UTC=" << expected << " TZ=" << timezone << std::endl;
        std::cout << "CRT_TIMEZONE_SECONDS=" << timezoneSeconds << std::endl;
        return 0;
    }
    catch (const std::exception& error)
    {
        std::cerr << error.what() << std::endl;
        return 1;
    }
}
