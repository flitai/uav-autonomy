vcpkg_download_distfile(ARCHIVE
    URLS "https://codeload.github.com/zeromq/cppzmq/tar.gz/refs/tags/v4.2.2"
    FILENAME "cppzmq-4.2.2.tar.gz"
    SHA512 5f61ea4a16987c1363c3029cf46b3e83ddd86d65e8d639b0332d691f8fdb5cee121b5d72a9b8c89221daf52ea5892219e0bc4ea4e761bb1e7deb1659011dd3c9
)
vcpkg_extract_source_archive(SOURCE_PATH ARCHIVE "${ARCHIVE}")
file(INSTALL "${SOURCE_PATH}/zmq.hpp" "${SOURCE_PATH}/zmq_addon.hpp" DESTINATION "${CURRENT_PACKAGES_DIR}/include")
file(WRITE "${CURRENT_PACKAGES_DIR}/share/cppzmq/cppzmqConfig.cmake" "include(CMakeFindDependencyMacro)\nfind_dependency(ZeroMQ CONFIG)\nadd_library(cppzmq INTERFACE IMPORTED)\nset_target_properties(cppzmq PROPERTIES INTERFACE_LINK_LIBRARIES libzmq-static)\n")
vcpkg_install_copyright(FILE_LIST "${SOURCE_PATH}/LICENSE")
