# kwin-momentum — touchpad kinetic scrolling for KWin (book / Plasma-Wayland).
#
# Built ON book with FEDORA's toolchain against Fedora's KWin+Qt6 headers, NOT
# by nix: a KWin binary plugin must link the exact Fedora libkwin.so.6 / Qt6
# ABI or kwin_wayland refuses to load it (runbook §0). So this is a plain
# CMake/ECM project a person runs on the machine, never a home-manager
# derivation. See docs/agents/kwin-momentum-plugin-runbook.md.
#
#   cmake -B build -S . -DCMAKE_BUILD_TYPE=Release
#   cmake --build build
#   install -D build/kwin_momentum.so \
#       ~/.local/lib64/qt6/plugins/kwin/plugins/kwin_momentum.so
#
# Loading it is the USER's step, in his Plasma session (runbook §5).

cmake_minimum_required(VERSION 3.20)

# C is enabled alongside CXX so CMake picks up the multiarch lib dir (/usr/lib64
# on Fedora aarch64); without it FindOpenGL — pulled in transitively by Qt6::Gui
# / KWin — searches only /usr/lib and fails to resolve libOpenGL/libGLX.
project(kwin_momentum VERSION 0.1.0 LANGUAGES C CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_AUTOMOC ON)

find_package(ECM 6.0.0 REQUIRED NO_MODULE)
list(APPEND CMAKE_MODULE_PATH ${ECM_MODULE_PATH})

include(KDEInstallDirs)
include(KDECMakeSettings)

# KWin::kwin's INTERFACE_LINK_LIBRARIES pulls Qt6::DBus and Qt6::Widgets, but
# Fedora's KWinConfig.cmake find_dependency list omits both — so we must define
# those imported targets ourselves before find_package(KWin), or the config
# fails at the KWinTargets import-check with "target not found".
find_package(Qt6 6.6 REQUIRED COMPONENTS Core Gui DBus Widgets Quick)
find_package(KWin REQUIRED)

add_library(kwin_momentum MODULE
    main.cpp
    momentumfilter.cpp
    momentumengine.cpp
)

# KWin's imported target carries /usr/include/kwin on its interface, which is
# where the private ABI headers (input.h, input_event.h, pointer_input.h,
# plugin.h) live.
target_link_libraries(kwin_momentum
    PRIVATE
        Qt6::Core
        Qt6::Gui
        KWin::kwin
)

# No "lib" prefix — KWin scans plugin dirs by plugin id, not soname.
set_target_properties(kwin_momentum PROPERTIES PREFIX "")

# Default install lands in the user plugin dir; override with -DCMAKE_INSTALL_PREFIX.
install(TARGETS kwin_momentum
    DESTINATION "$ENV{HOME}/.local/lib64/qt6/plugins/kwin/plugins")
