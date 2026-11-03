#include "taq_time.hpp"

#include <span>
#include <utility>

std::expected<std::int64_t, std::string> nanos_of_day(std::int64_t time_m_micros, std::int64_t time_m_nano) {
    if (time_m_micros < 0 || time_m_micros >= 86'400'000'000) {
        return std::unexpected("time_m out of range: " + std::to_string(time_m_micros));
    }
    if (time_m_nano < 0 || time_m_nano > 999) {
        return std::unexpected("time_m_nano out of range: " + std::to_string(time_m_nano));
    }
    return time_m_micros * 1000 + time_m_nano;
}

namespace {

// An era starts on first_day and lasts until the next era in its table starts.
struct Era {
    std::string_view first_day;
    Resolution most_rows;
};

// Measured on every file 2006-01-03 .. 2026-08-31 (research_system,
// docs/reference/TAQ_DATA.md section 4, evidence 2026-10-11-taq-eras).
constexpr Era NBBO_ERAS[] = {
    {"2006-01-03", Resolution::Second},       // some rows stop at the whole second
    {"2006-02-07", Resolution::Millisecond},
    {"2015-08-03", Resolution::Microsecond},
    {"2018-10-11", Resolution::Nanosecond},
};

constexpr Era CQM_ERAS[] = {
    {"2006-01-03", Resolution::Second},       // some rows stop at the whole second
    {"2006-02-07", Resolution::Millisecond},
    {"2010-05-07", Resolution::Second},       // one day: the day after the Flash Crash
    {"2010-05-10", Resolution::Millisecond},
    {"2015-08-03", Resolution::Microsecond},
    {"2018-10-11", Resolution::Nanosecond},
};

constexpr Era CTM_ERAS[] = {
    {"2006-01-03", Resolution::Millisecond},
    {"2015-08-03", Resolution::Microsecond},
    {"2019-05-23", Resolution::Nanosecond},
    {"2019-08-12", Resolution::Microsecond},  // one day: one feed sent no nanosecond digits
    {"2019-08-13", Resolution::Nanosecond},
};

std::span<const Era> eras_of(Product product) {
    switch (product) {
        case Product::CompleteNbbo: return NBBO_ERAS;
        case Product::Cqm:          return CQM_ERAS;
        case Product::Ctm:          return CTM_ERAS;
    }
    std::unreachable();
}

bool is_day_text(std::string_view day) {
    if (day.size() != 10 || day[4] != '-' || day[7] != '-') {
        return false;
    }
    for (const int i : {0, 1, 2, 3, 5, 6, 8, 9}) {
        if (day[i] < '0' || day[i] > '9') {
            return false;
        }
    }
    return true;
}

}  // namespace

std::expected<Resolution, std::string> time_resolution(Product product, std::string_view day) {
    if (!is_day_text(day)) {
        return std::unexpected("not a YYYY-MM-DD day: \"" + std::string(day) + "\"");
    }
    const std::span<const Era> eras = eras_of(product);
    if (day < eras.front().first_day) {
        return std::unexpected("nothing was measured before 2006-01-03: " + std::string(day));
    }
    // YYYY-MM-DD text sorts in date order, and the eras are in date order,
    // so the last era that has started is the one in force.
    Resolution found = eras.front().most_rows;
    for (const Era& era : eras) {
        if (era.first_day <= day) {
            found = era.most_rows;
        }
    }
    return found;
}
