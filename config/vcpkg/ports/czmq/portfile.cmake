vcpkg_download_distfile(ARCHIVE
    URLS "https://codeload.github.com/zeromq/czmq/tar.gz/refs/tags/v4.0.2"
    FILENAME "czmq-4.0.2.tar.gz"
    SHA512 8fb4ce059b9ded2f148be4d9602e2d734573e0b6a31936ee72fab2c51116906fefaef1f9c0f8673f3428c84f438cfad26a1120b79d702b54a71c65798f99e8d6
)
vcpkg_extract_source_archive(SOURCE_PATH ARCHIVE "${ARCHIVE}" PATCHES windows.patch)
vcpkg_cmake_configure(SOURCE_PATH "${SOURCE_PATH}" OPTIONS -DBUILD_SHARED_LIBS=OFF -DENABLE_DRAFTS=OFF -DCMAKE_CXX_STANDARD=14)
vcpkg_cmake_install()
vcpkg_fixup_pkgconfig()
file(REMOVE_RECURSE "${CURRENT_PACKAGES_DIR}/debug")
foreach(name readme.txt sha1.h sha1.inc_c slre.h slre.inc_c zgossip_engine.inc zgossip_msg.h zhash_primes.inc zsock_option.inc)
    file(REMOVE "${CURRENT_PACKAGES_DIR}/include/${name}")
endforeach()
vcpkg_install_copyright(FILE_LIST "${SOURCE_PATH}/LICENSE")
