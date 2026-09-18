set(VCPKG_TARGET_ARCHITECTURE x64)
set(VCPKG_CRT_LINKAGE dynamic)
set(VCPKG_LIBRARY_LINKAGE static)
set(VCPKG_BUILD_TYPE release)
set(VCPKG_PLATFORM_TOOLSET v143)
set(VCPKG_PLATFORM_TOOLSET_VERSION 14.44.35207)
set(VCPKG_CMAKE_SYSTEM_VERSION 10.0.26100.0)
set(VCPKG_CXX_FLAGS "/std:c++14 /DBOOST_ALL_NO_LIB")
set(VCPKG_C_FLAGS "")
# vcpkg's clean child environment otherwise drops the pinned portable tools.
# Track the exact enabled PATH in the ABI instead of searching unrelated tools.
set(VCPKG_ENV_PASSTHROUGH VCPKG_FORCE_SYSTEM_BINARIES PATH)
include("${CMAKE_CURRENT_LIST_DIR}/../cmake/spdx-cmake331.cmake")
set(VCPKG_HASH_ADDITIONAL_FILES "${CMAKE_CURRENT_LIST_DIR}/../cmake/spdx-cmake331.cmake")
