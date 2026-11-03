// TAQ times: one row's time as nanoseconds since midnight, and how precise a
// product's times are on a given day. Times are US Eastern wall-clock time,
// as the files store them.

#pragma once

#include <cstdint>
#include <expected>
#include <string>
#include <string_view>

// time_m_micros: the time_m column, microseconds since midnight.
// time_m_nano:   the time_m_nano column, the 3 digits after the microsecond;
//                pass 0 on days the file has no such column.
// Returns an error message when either is out of range.
std::expected<std::int64_t, std::string> nanos_of_day(std::int64_t time_m_micros, std::int64_t time_m_nano);

enum class Product { CompleteNbbo, Cqm, Ctm };

// Ordered coarse to fine, so `resolution >= Resolution::Millisecond` works.
enum class Resolution { Second, Millisecond, Microsecond, Nanosecond };

// The resolution at least 99% of the product's rows use on that day.
// day is "YYYY-MM-DD", the name of the day's folder.
// Returns an error message for other text, or for a day before 2006-01-03
// (nothing was measured there). Days after the last era get the latest era.
std::expected<Resolution, std::string> time_resolution(Product product, std::string_view day);
