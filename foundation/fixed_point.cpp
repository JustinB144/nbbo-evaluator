#include "fixed_point.hpp"

#include <limits>

namespace {

constexpr std::int64_t LARGEST = std::numeric_limits<std::int64_t>::max();

std::unexpected<std::string> fail(const char* what, std::string_view text) {
    return std::unexpected(std::string(what) + ": \"" + std::string(text) + "\"");
}

// Reads text as a whole number of units, where one unit is 10^-decimals.
std::expected<Parsed, std::string> parse_fixed(std::string_view text, int decimals) {
    std::int64_t value = 0;
    int digits_before = 0;    // digits before the '.'
    int digits_after = 0;     // digits after the '.'
    bool seen_point = false;
    bool rounded = false;
    bool round_up = false;

    for (const char c : text) {
        if (c == '.') {
            if (seen_point) {
                return fail("not a number", text);
            }
            seen_point = true;
            continue;
        }
        if (c < '0' || c > '9') {
            return fail("not a number", text);
        }
        const int digit = c - '0';
        if (seen_point) {
            digits_after++;
        } else {
            digits_before++;
        }

        if (digits_after <= decimals) {
            // A kept digit. value * 10 + digit must fit in int64_t.
            if (value > (LARGEST - digit) / 10) {
                return fail("too large", text);
            }
            value = value * 10 + digit;
        } else {
            // A dropped digit. Only the first one decides rounding up.
            if (digits_after == decimals + 1 && digit >= 5) {
                round_up = true;
            }
            if (digit != 0) {
                rounded = true;
            }
        }
    }

    // Catches "", ".", ".5" and "5.".
    if (digits_before == 0 || (seen_point && digits_after == 0)) {
        return fail("not a number", text);
    }

    // Fill the decimals the text did not have: "12.5" with 4 decimals -> 125000.
    for (int i = digits_after; i < decimals; i++) {
        if (value > LARGEST / 10) {
            return fail("too large", text);
        }
        value = value * 10;
    }

    if (round_up) {
        if (value == LARGEST) {
            return fail("too large", text);
        }
        value = value + 1;
    }
    return Parsed{value, rounded};
}

}  // namespace

std::expected<Parsed, std::string> parse_price(std::string_view text) {
    return parse_fixed(text, 4);
}

std::expected<Parsed, std::string> parse_size(std::string_view text) {
    return parse_fixed(text, 6);
}
