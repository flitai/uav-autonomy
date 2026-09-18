option(UXAS_ENABLE_ZYRE "Enable Zyre after separately qualifying its dependency" OFF)
option(UXAS_ENABLE_SERIAL "Enable serial after separately qualifying its dependency" OFF)
if(UXAS_ENABLE_ZYRE OR UXAS_ENABLE_SERIAL)
    message(FATAL_ERROR "ZYRE/SERIAL ON is unavailable: the locked T02 package has no qualified optional bridge dependencies")
endif()
if(NOT CMAKE_GENERATOR STREQUAL "Visual Studio 17 2022" OR
   NOT CMAKE_VS_PLATFORM_TOOLSET STREQUAL "v143" OR
   NOT CMAKE_GENERATOR_PLATFORM STREQUAL "x64" OR
   NOT CMAKE_GENERATOR_TOOLSET STREQUAL "v143,host=x64,version=14.44.35207" OR
   NOT CMAKE_VS_WINDOWS_TARGET_PLATFORM_VERSION STREQUAL "10.0.26100.0")
    message(FATAL_ERROR "UxAS requires the qualified VS 2022/v143/14.44.35207/SDK 10.0.26100.0 toolchain")
endif()
if(CMAKE_TOOLCHAIN_FILE)
    message(FATAL_ERROR "UxAS consumes qualified packages; implicit dependency toolchains are not accepted")
endif()
if(NOT EXISTS "${UXAS_VALIDATION_CONTEXT}" OR NOT EXISTS "${UXAS_VALIDATION_PYTHON}")
    message(FATAL_ERROR "Missing qualified source context; run configure-uxas.ps1")
endif()
# This read-only validator runs on every configure, including manual preset reuse.
execute_process(COMMAND "${UXAS_VALIDATION_PYTHON}" -I -B -X utf8
    "${CMAKE_CURRENT_SOURCE_DIR}/scripts/uxas/graph.py" validate
    --root "${CMAKE_CURRENT_SOURCE_DIR}" --context "${UXAS_VALIDATION_CONTEXT}"
    --output "${CMAKE_CURRENT_BINARY_DIR}/uxas-graph.json"
    RESULT_VARIABLE _validation_result OUTPUT_VARIABLE _validation_output ERROR_VARIABLE _validation_error)
if(NOT _validation_result EQUAL 0)
    message(FATAL_ERROR "UxAS source validation failed: ${_validation_output}\n${_validation_error}")
endif()
include("${CMAKE_CURRENT_BINARY_DIR}/uxas-inputs.cmake")
# CMAKE_VS_PLATFORM_TOOLSET_VERSION may be empty when the selected version is
# the installation default. Bind the actual executables to the qualified tools.
foreach(_tool CMAKE_COMMAND CMAKE_CXX_COMPILER CMAKE_LINKER)
    file(REAL_PATH "${${_tool}}" _actual_tool)
    file(REAL_PATH "${UXAS_QUALIFIED_${_tool}}" _qualified_tool)
    string(TOLOWER "${_actual_tool}" _actual_tool)
    string(TOLOWER "${_qualified_tool}" _qualified_tool)
    if(NOT _actual_tool STREQUAL _qualified_tool)
        message(FATAL_ERROR "${_tool} differs from the qualified tool source")
    endif()
endforeach()
foreach(_package UxasDependencies UxasLmcp)
    if(_package STREQUAL "UxasDependencies")
        set(_prefix "${UXAS_DEPENDENCIES_PREFIX}")
    else()
        set(_prefix "${UXAS_LMCP_PREFIX}")
    endif()
    set(_qualified_dir "${_prefix}/share/${_package}")
    if(DEFINED ${_package}_DIR AND NOT "${${_package}_DIR}" STREQUAL "${_qualified_dir}")
        message(FATAL_ERROR "${_package}_DIR differs from the qualified package source")
    endif()
    set(${_package}_DIR "${_qualified_dir}")
    find_package(${_package} CONFIG REQUIRED NO_DEFAULT_PATH PATHS "${_qualified_dir}")
endforeach()
set(_uxas_manifest "${CMAKE_CURRENT_SOURCE_DIR}/OpenUxAS/src/cpp/Includes/uxas.manifest")
add_executable(uxas ${UXAS_SOURCES} ${UXAS_EMBEDDED_RESOURCES} "${_uxas_manifest}")
set_source_files_properties(${UXAS_EMBEDDED_RESOURCES} PROPERTIES HEADER_FILE_ONLY ON)
target_include_directories(uxas PRIVATE ${UXAS_INCLUDE_DIRS})
# Preserve configuration, service identity and shutdown evidence for native runs.
target_compile_definitions(uxas PRIVATE DPSS_STATIC NOMINMAX UXAS_INFO_LOGGING_ENABLED UXAS_ENABLE_ZYRE=0 UXAS_ENABLE_SERIAL=0
    BOOST_ALLOW_DEPRECATED_HEADERS BOOST_GEOMETRY_DISABLE_DEPRECATED_03_WARNING)
target_compile_options(uxas PRIVATE /W3 /utf-8 /MP8 /EHsc)
target_link_options(uxas PRIVATE "/MAP:${CMAKE_CURRENT_BINARY_DIR}/uxas.map" /VERBOSE:LIB)
target_link_libraries(uxas PRIVATE Uxas::lmcp UxasDeps::zeromq UxasDeps::cppzmq
    UxasDeps::czmq UxasDeps::pugixml UxasDeps::sqlite3 UxasDeps::sqlitecpp UxasDeps::boost)
# These targets exercise production policy without compiling or starting UxAS.
foreach(_probe bridge_configuration_probe bridge_legacy_defaults_probe)
    add_executable(${_probe} EXCLUDE_FROM_ALL tests/uxas_cmake/bridge_probe.cpp)
    target_include_directories(${_probe} PRIVATE OpenUxAS/src/cpp/Communications)
    target_link_libraries(${_probe} PRIVATE UxasDeps::pugixml)
    target_compile_options(${_probe} PRIVATE /W4 /utf-8)
endforeach()
target_compile_definitions(bridge_configuration_probe PRIVATE UXAS_ENABLE_ZYRE=0 UXAS_ENABLE_SERIAL=0)

# Reuse real utility implementations and their logger/configuration closure.
# This is a separate, file-only entry point; it never starts the UxAS services.
add_executable(uxas_platform_probe EXCLUDE_FROM_ALL tests/uxas_build/platform_probe.cpp "${_uxas_manifest}"
    OpenUxAS/src/cpp/Utilities/FileSystemUtilities.cpp
    OpenUxAS/src/cpp/Utilities/TimeUtilities.cpp
    OpenUxAS/src/cpp/Utilities/UxAS_Time.cpp
    OpenUxAS/src/cpp/Utilities/UxAS_FileLogger.cpp
    OpenUxAS/src/cpp/Utilities/UxAS_LogManager.cpp
    OpenUxAS/src/cpp/Utilities/UxAS_ConsoleLogger.cpp
    OpenUxAS/src/cpp/Utilities/UxAS_DatabaseLogger.cpp
    OpenUxAS/src/cpp/Utilities/UxAS_DatabaseLoggerHelper.cpp
    OpenUxAS/src/cpp/Utilities/UxAS_HeadLogDataDatabaseLogger.cpp
    OpenUxAS/src/cpp/Utilities/UxAS_ConfigurationManager.cpp)
target_include_directories(uxas_platform_probe PRIVATE ${UXAS_INCLUDE_DIRS})
target_compile_definitions(uxas_platform_probe PRIVATE DPSS_STATIC NOMINMAX UXAS_ENABLE_ZYRE=0 UXAS_ENABLE_SERIAL=0)
target_compile_options(uxas_platform_probe PRIVATE /W3 /utf-8 /EHsc)
target_link_libraries(uxas_platform_probe PRIVATE Uxas::lmcp UxasDeps::pugixml UxasDeps::sqlitecpp UxasDeps::boost)
