#ifndef UXAS_WINDOWS_ENVIRONMENT_H
#define UXAS_WINDOWS_ENVIRONMENT_H

#ifdef _WIN32
#include <boost/filesystem/path.hpp>
#include <codecvt>
#include <locale>
#endif

namespace uxas
{
namespace common
{
// Call on the main thread before any path conversion or worker starts. This
// changes only Boost.Filesystem's conversion facet, never the global locale.
inline void initializeWindowsPaths()
{
#ifdef _WIN32
    boost::filesystem::path::imbue(std::locale(std::locale::classic(),
        new std::codecvt_utf8_utf16<wchar_t>));
#endif
}
}
}
#endif
