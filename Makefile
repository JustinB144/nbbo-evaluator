CXX := g++
# Everything builds with AddressSanitizer and UndefinedBehaviorSanitizer, so
# overflow and out-of-bounds reads stop the run instead of passing silently.
SANITIZE := -fsanitize=address,undefined -fno-sanitize-recover=undefined
CXXFLAGS := -std=c++23 -Wall -Wextra -Wpedantic -g $(SANITIZE)
CPPFLAGS := -Ifoundation -isystem third_party/catch2 -isystem third_party/duckdb

# DuckDB is a shared library. -L finds it when linking; -rpath records where
# it is, so the program also finds it when it runs.
DUCKDB := -Lthird_party/duckdb -lduckdb -Wl,-rpath,$(CURDIR)/third_party/duckdb

FOUNDATION := foundation/fixed_point.cpp foundation/taq_time.cpp
HEADERS := foundation/fixed_point.hpp foundation/taq_time.hpp
TESTS := tests/fixed_point_test.cpp tests/taq_time_test.cpp

# `make` with no target runs the first rule: build everything.
.PHONY: all test clean
all: build/read_nbbo build/tests

test: build/tests
	./build/tests

clean:
	rm -rf build

build:
	mkdir -p build

# The TAQ reader: ./build/read_nbbo YYYY-MM-DD
build/read_nbbo: readers/read_nbbo.cpp $(FOUNDATION) $(HEADERS) Makefile | build
	$(CXX) $(CPPFLAGS) $(CXXFLAGS) readers/read_nbbo.cpp $(FOUNDATION) $(DUCKDB) -o $@

# Catch2 is built once, without our warning flags: it is not our code.
build/catch.o: third_party/catch2/catch_amalgamated.cpp | build
	$(CXX) -std=c++23 -g $(SANITIZE) -c $< -o $@

build/tests: $(TESTS) $(FOUNDATION) $(HEADERS) build/catch.o Makefile | build
	$(CXX) $(CPPFLAGS) $(CXXFLAGS) $(TESTS) $(FOUNDATION) build/catch.o -o $@
