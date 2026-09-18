vcpkg_download_distfile(ARCHIVE
    URLS "https://codeload.github.com/zeromq/libzmq/tar.gz/refs/tags/v4.3.1"
    FILENAME "zeromq-4.3.1.tar.gz"
    SHA512 64855a73331a194c43b01aa86a985a149eba4ed32b9f6483d2a7415cfd8bba557aab5b7b33d160cd177141de02360b73c20e4696a19c2cd798eb5f82eeb72840
)
vcpkg_extract_source_archive(SOURCE_PATH ARCHIVE "${ARCHIVE}")
vcpkg_cmake_configure(SOURCE_PATH "${SOURCE_PATH}" OPTIONS
    -DBUILD_SHARED=OFF -DBUILD_STATIC=ON -DBUILD_TESTS=OFF -DZMQ_BUILD_TESTS=OFF
    -DWITH_DOC=OFF -DWITH_OPENPGM=OFF -DWITH_VMCI=OFF -DWITH_LIBSODIUM=OFF
    -DENABLE_CURVE=ON -DENABLE_DRAFTS=OFF -DENABLE_CPACK=OFF
    -DCMAKE_CXX_STANDARD=14)
vcpkg_cmake_install()
vcpkg_cmake_config_fixup(PACKAGE_NAME ZeroMQ CONFIG_PATH share/cmake/ZeroMQ)
vcpkg_fixup_pkgconfig()
vcpkg_copy_pdbs()
file(REMOVE_RECURSE "${CURRENT_PACKAGES_DIR}/debug")
vcpkg_install_copyright(FILE_LIST "${SOURCE_PATH}/COPYING" "${SOURCE_PATH}/COPYING.LESSER")
