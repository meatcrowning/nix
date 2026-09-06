cmake_minimum_required(VERSION 3.20)
project(org_kde_lam_menubar LANGUAGES CXX)

find_package(ECM REQUIRED NO_MODULE)
set(CMAKE_MODULE_PATH ${ECM_MODULE_PATH})
include(KDEInstallDirs)

find_package(Qt6 REQUIRED COMPONENTS Core Gui Quick Widgets)
find_package(Plasma REQUIRED)
find_package(KF6 REQUIRED COMPONENTS Config CoreAddons)

add_library(org.kde.lam.menubar MODULE menubarapplet.cpp)
target_link_libraries(org.kde.lam.menubar PRIVATE
    Qt6::Core Qt6::Gui Qt6::Quick Qt6::Widgets Plasma::Plasma KF6::CoreAddons)
target_compile_features(org.kde.lam.menubar PRIVATE cxx_std_20)
install(TARGETS org.kde.lam.menubar DESTINATION ${KDE_INSTALL_PLUGINDIR}/plasma/applets)
