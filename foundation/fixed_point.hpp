// Exact prices and share sizes, read from TAQ text with no floating point.
// A price is whole ten-thousandths of a dollar:  "491.96"   -> 4919600
// A size is whole millionths of a share:          "0.044583" -> 44583, "100" -> 100000000

#pragma once

#include <cstdint>
#include <expected>
#include <string>
#include <string_view>

struct Parsed {
    std::int64_t value = 0;
    bool rounded = false;   // a nonzero digit past the last kept decimal was dropped
};

// Both accept digits with at most one '.' and digits on both sides of it ("12", "12.5").
// Extra decimals are rounded half up and reported in Parsed::rounded.
// Any other text, or a value too large for int64_t, returns an error message.
std::expected<Parsed, std::string> parse_price(std::string_view text);   // keeps 4 decimals
std::expected<Parsed, std::string> parse_size(std::string_view text);    // keeps 6 decimals
