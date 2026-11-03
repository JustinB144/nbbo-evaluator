#include "taq_time.hpp"

#include <catch_amalgamated.hpp>

TEST_CASE("time_m and time_m_nano join into nanoseconds since midnight") {
    CHECK(*nanos_of_day(34'200'000'000, 0) == 34'200'000'000'000);           // 09:30:00
    CHECK(*nanos_of_day(34'200'123'456, 789) == 34'200'123'456'789);
    CHECK(*nanos_of_day(86'399'999'999, 999) == 86'399'999'999'999);         // the last nanosecond of the day
}

TEST_CASE("out-of-range time pieces are refused") {
    CHECK_FALSE(nanos_of_day(-1, 0).has_value());
    CHECK_FALSE(nanos_of_day(86'400'000'000, 0).has_value());
    CHECK_FALSE(nanos_of_day(0, -1).has_value());
    CHECK_FALSE(nanos_of_day(0, 1000).has_value());
}

TEST_CASE("each era starts on its first day") {
    CHECK(*time_resolution(Product::CompleteNbbo, "2006-02-06") == Resolution::Second);
    CHECK(*time_resolution(Product::CompleteNbbo, "2006-02-07") == Resolution::Millisecond);
    CHECK(*time_resolution(Product::CompleteNbbo, "2018-10-11") == Resolution::Nanosecond);
    CHECK(*time_resolution(Product::Ctm, "2006-01-03") == Resolution::Millisecond);
}

TEST_CASE("one-day exceptions apply to that day only") {
    CHECK(*time_resolution(Product::Cqm, "2010-05-06") == Resolution::Millisecond);
    CHECK(*time_resolution(Product::Cqm, "2010-05-07") == Resolution::Second);
    CHECK(*time_resolution(Product::Cqm, "2010-05-10") == Resolution::Millisecond);
    CHECK(*time_resolution(Product::Ctm, "2019-08-12") == Resolution::Microsecond);
    CHECK(*time_resolution(Product::Ctm, "2019-08-13") == Resolution::Nanosecond);
}

TEST_CASE("days after the last era get the latest era") {
    CHECK(*time_resolution(Product::Cqm, "2026-08-31") == Resolution::Nanosecond);
}

TEST_CASE("unmeasured days and bad day text are refused") {
    CHECK_FALSE(time_resolution(Product::Cqm, "2006-01-02").has_value());
    for (const char* day : {"", "2006-1-3", "2006/01/03", "20060103xx", "2006-01-0a"}) {
        CHECK_FALSE(time_resolution(Product::Cqm, day).has_value());
    }
}
