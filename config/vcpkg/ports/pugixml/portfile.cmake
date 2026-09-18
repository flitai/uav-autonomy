vcpkg_download_distfile(ARCHIVE
    URLS "https://codeload.github.com/zeux/pugixml/tar.gz/refs/tags/v1.12.1"
    FILENAME "pugixml-1.12.1.tar.gz"
    SHA512 c1a80518e8d7b21f2a15b2023b77e87484f5b7581e68ff508785a60cab53d1689b5508f5a652d6f0d4fbcc91f66d59246fdfe499fd6b0e188c7914ed5919980b
)
vcpkg_extract_source_archive(SOURCE_PATH ARCHIVE "${ARCHIVE}" PATCHES windows.patch)
vcpkg_cmake_configure(SOURCE_PATH "${SOURCE_PATH}" OPTIONS -DBUILD_SHARED_LIBS=OFF -DPUGIXML_BUILD_TESTS=OFF -DPUGIXML_WCHAR_MODE=OFF -DCMAKE_CXX_STANDARD=14)
vcpkg_cmake_install()
vcpkg_cmake_config_fixup(CONFIG_PATH lib/cmake/pugixml)
file(REMOVE_RECURSE "${CURRENT_PACKAGES_DIR}/debug")
vcpkg_install_copyright(FILE_LIST "${SOURCE_PATH}/LICENSE.md")
