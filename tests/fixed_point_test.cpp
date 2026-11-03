#include "fixed_point.hpp"

#include <catch_amalgamated.hpp>

TEST_CASE("prices keep 4 decimals") {
    CHECK(parse_price("491.96")->value == 4919600);
    CHECK(parse_price("12")->value == 120000);
    CHECK(parse_price("0.0001")->value == 1);
    CHECK_FALSE(parse_price("491.96")->rounded);
}

TEST_CASE("sizes keep 6 decimals") {
    CHECK(parse_size("0.044583")->value == 44583);
    CHECK(parse_size("100")->value == 100000000);
}

TEST_CASE("extra decimals round half up and are reported") {
    CHECK(parse_price("1.23455")->value == 12346);
    CHECK(parse_price("1.23454")->value == 12345);
    CHECK(parse_price("1.23454")->rounded);
    CHECK(parse_price("0.00005")->value == 1);
}

TEST_CASE("extra zeros are not rounding") {
    CHECK(parse_price("1.230000")->value == 12300);
    CHECK_FALSE(parse_price("1.230000")->rounded);
}

TEST_CASE("text that is not a number is refused") {
    for (const char* text : {"", ".", ".5", "5.", "1.2.3", "-1", "1e5", " 1", "1,000"}) {
        CHECK_FALSE(parse_price(text).has_value());
    }
}

TEST_CASE("values too large for int64_t are refused") {
    // The largest int64_t is 9223372036854775807; with 4 decimals the largest price is 922337203685477.5807.
    CHECK(parse_price("922337203685477.5807")->value == 9223372036854775807);
    CHECK_FALSE(parse_price("922337203685477.5808").has_value());
    CHECK_FALSE(parse_price("922337203685477.58075").has_value());   // fits, then rounding up overflows
    CHECK_FALSE(parse_price("922337203685478").has_value());         // fits as a whole number, not once scaled
    CHECK_FALSE(parse_price("99999999999999999999").has_value());
}
