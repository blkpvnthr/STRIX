# Build the STRIX native-CPU kernel shared library (R1 §5.3, §8, L).
#
# Produces libstrix_native.{dylib,so} loaded by strix.native.backends.native_cpu
# via ctypes. Correctness is certified by the Python parity harness against the
# PythonReferenceBackend — this library is a TOLERANCE-class backend, never the
# numerical reference.
cmake_minimum_required(VERSION 3.20)
project(strix_native C)

set(CMAKE_C_STANDARD 11)
set(CMAKE_C_STANDARD_REQUIRED ON)

if(NOT CMAKE_BUILD_TYPE)
  set(CMAKE_BUILD_TYPE Release)
endif()

add_library(strix_native SHARED strix_native.c)
target_include_directories(strix_native PRIVATE ${CMAKE_CURRENT_SOURCE_DIR})

# Deterministic math: no fast-math reassociation, which would break parity.
target_compile_options(strix_native PRIVATE -O2 -fPIC -Wall -Wextra)
if(NOT MSVC)
  target_compile_options(strix_native PRIVATE -fno-fast-math)
endif()

# Link the C math library where required (Linux); harmless elsewhere.
include(CheckLibraryExists)
check_library_exists(m sqrt "" HAVE_LIBM)
if(HAVE_LIBM)
  target_link_libraries(strix_native m)
endif()
