vcpkg_download_distfile(ARCHIVE
    URLS "https://sqlite.org/2022/sqlite-autoconf-3390400.tar.gz"
    FILENAME "sqlite3-3.39.4.tar.gz"
    SHA512 cc1de214e69ef677cac3f6dd2000ccfcf4b672ab464a115d96f24707009a408630e762c3cda89741b728ab34c4d9f5b8f8b12e9b11448e8364642b4421c3393d
)
vcpkg_extract_source_archive(SOURCE_PATH ARCHIVE "${ARCHIVE}")
file(COPY "${CMAKE_CURRENT_LIST_DIR}/CMakeLists.txt" DESTINATION "${SOURCE_PATH}")
vcpkg_cmake_configure(SOURCE_PATH "${SOURCE_PATH}")
vcpkg_cmake_install()
file(REMOVE_RECURSE "${CURRENT_PACKAGES_DIR}/debug")
vcpkg_install_copyright(FILE_LIST "${CMAKE_CURRENT_LIST_DIR}/copyright")
