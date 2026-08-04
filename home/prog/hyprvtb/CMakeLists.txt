cmake_minimum_required(VERSION 3.27)

project(hyprvtb
    DESCRIPTION "vertical titlebar plugin for Hyprland"
    VERSION 0.1
)

set(CMAKE_CXX_STANDARD 23)

file(GLOB_RECURSE SRC "*.cpp")

add_library(hyprvtb SHARED ${SRC})

find_package(PkgConfig REQUIRED)
pkg_check_modules(deps REQUIRED IMPORTED_TARGET
    hyprland
    libdrm
    libinput
    libudev
    pixman-1
    wayland-server
    xkbcommon
    pangocairo
    fontconfig
    librsvg-2.0
)
target_link_libraries(hyprvtb PRIVATE rt PkgConfig::deps)

# Tell vtbCompat.hpp which Hyprland it is being built against (Tier 1 of its
# version detection; see the block at the top of that file). There is no
# preprocessor version macro in Hyprland's headers — pkg-config's Version:
# field is the only exact signal, so inject it: 0.56.0 -> 5600.
if(deps_hyprland_VERSION MATCHES "^([0-9]+)\\.([0-9]+)(\\.([0-9]+))?")
    set(_hl_patch "${CMAKE_MATCH_4}")
    if(NOT _hl_patch)
        set(_hl_patch 0)
    endif()
    math(EXPR VTB_HL_VERSION
         "${CMAKE_MATCH_1}*10000 + ${CMAKE_MATCH_2}*100 + ${_hl_patch}")
    message(STATUS "hyprvtb: Hyprland ${deps_hyprland_VERSION} -> VTB_HL_VERSION=${VTB_HL_VERSION}")
    target_compile_definitions(hyprvtb PRIVATE VTB_HL_VERSION=${VTB_HL_VERSION})
else()
    message(WARNING "hyprvtb: could not parse Hyprland version '${deps_hyprland_VERSION}'; vtbCompat.hpp falls back to header probes")
endif()

install(TARGETS hyprvtb)
