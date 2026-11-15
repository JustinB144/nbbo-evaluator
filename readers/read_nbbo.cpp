// read_nbbo: one day of Complete NBBO -> /mnt/data/artifacts/a1/nbbo/<day>.parquet
// Usage: ./build/read_nbbo YYYY-MM-DD    
//
// Kept: quotes from 09:30:00 to before 16:00:00, in order of symbol, then time.
//
// Decisions:
// - Dropped and counted: NULL price, price that won't parse, zero price,
//   bad time, NULL symbol, NULL size.
// - Crossed (ask < bid) and locked (ask = bid) quotes: KEPT and counted.
//   They are real market states. Questions that use the spread must handle
//   a spread <= 0.
// - Rounded prices (more than 4 decimals): KEPT and counted. Rule 612 makes
//   them rare (0 found on 21 days, 2006-2025).
// - Symbol: sym_root + "-" + sym_suffix when there is a suffix (BF-B).


#include <iostream>
#include <string>
#include <duckdb.hpp>
#include <expected>
#include <filesystem>
#include "fixed_point.hpp"
#include "taq_time.hpp"
namespace fs = std::filesystem;

duckdb::DuckDB database(nullptr);
duckdb::Connection connection(database);


// QUERY

std::expected<int, std::string> get_quote(const fs::path &folder, std::string &day, int &bad_time_count, int &null_price_count, 
	int &bad_price_count, int &zero_price_count, int &kept_count, int &null_price_size_count, int &null_ticker_count, int &locked_qc, 
	int &crossed_qc, int &rounded_count, int& null_qu_cond_count, int& null_natbbo_ind_count){
	std::string sql;
	int row_count = 0;
	if (day >= "2018-01-02"){
		sql = R"sql(
			SELECT
				CAST(best_bid AS VARCHAR) AS bid,
				CAST(best_ask AS VARCHAR) AS ask,
				CAST(epoch_us(time_m) AS BIGINT) AS time_micro,
				CAST(time_m_nano AS BIGINT) AS time_nano,
				CAST(sym_root AS VARCHAR) AS ticker,
				CAST(sym_suffix AS VARCHAR) AS trading_class,
				CAST(best_bidsizeshares AS BIGINT) AS best_bid_size,
				CAST(best_asksizeshares AS BIGINT) AS best_ask_size,
				CAST(qu_cond AS VARCHAR) AS qu_cond,
				CAST(natbbo_ind AS VARCHAR) AS natbbo_ind
			FROM read_parquet(')sql"
			+ folder.string()
			+ R"sql(/*.parquet', filename = true, file_row_number = true)
			WHERE time_m >= TIME '09:30:00' AND time_m < TIME '16:00:00'
			ORDER BY ticker, trading_class, time_micro, time_nano, filename, file_row_number;
		)sql";
	}
	else {
		sql = R"sql(
			SELECT
				CAST(best_bid AS VARCHAR) AS bid,
				CAST(best_ask AS VARCHAR) AS ask,
				CAST(epoch_us(time_m) AS BIGINT) AS time_micro,
				0 AS time_nano,
				CAST(sym_root AS VARCHAR) AS ticker,
				CAST(sym_suffix AS VARCHAR) AS trading_class,
				CAST(best_bidsizeshares AS BIGINT) AS best_bid_size,
				CAST(best_asksizeshares AS BIGINT) AS best_ask_size,
				CAST(qu_cond AS VARCHAR) AS qu_cond,
				CAST(natbbo_ind AS VARCHAR) AS natbbo_ind
			FROM read_parquet(')sql"
			+ folder.string()
			+ R"sql(/*.parquet', filename = true, file_row_number = true)
			WHERE time_m >= TIME '09:30:00' AND time_m < TIME '16:00:00'
			ORDER BY ticker, trading_class, time_micro, time_nano, filename, file_row_number;
		)sql";
	}
	/*
	┌────────┬───────────────┐
	│ Number │    Column     │
	├────────┼───────────────┤
	│ 0      │ bid           │
	├────────┼───────────────┤
	│ 1      │ ask           │
	├────────┼───────────────┤
	│ 2      │ time_micro    │
	├────────┼───────────────┤
	│ 3      │ time_nano     │
	├────────┼───────────────┤
	│ 4      │ ticker        │
	├────────┼───────────────┤
	│ 5      │ trading_class │
	├────────┼───────────────┤
	│ 6      │ best_bid_size │
	├────────┼───────────────┤
	│ 7      │ best_ask_size │
	|────────┴───────────────┘ 
	|8 = qu_cond
	|9 = natbbo_ind
	*/
	
	auto quote_statement = connection.Query(sql);
	if (quote_statement -> HasError()){
		return std::unexpected(quote_statement -> GetError());
	}
	//create table and append adds to it then it gets copied to /mnt/data/artifacts/a1/nbbo/
	auto create_table = connection.Query("CREATE TABLE nbbo_rows (symbol VARCHAR, nanos BIGINT, bid BIGINT, ask BIGINT, bid_size BIGINT, ask_size BIGINT, qu_cond VARCHAR, natbbo_ind VARCHAR)");
	if (create_table -> HasError()){
    return std::unexpected(create_table -> GetError());
	}
	duckdb::Appender appender(connection, "nbbo_rows");
	while (true) {
		auto chunk = quote_statement->Fetch();
		if (chunk == nullptr) {
			break;  // no more data
		}
		for (duckdb::idx_t row = 0; row < chunk->size(); ++row){
			++row_count;
			// Time and symbol first: a row without them can't be placed, so it is
			// dropped before any side is counted. Every count below is then about kept rows.
			auto time_microsec = chunk -> GetValue(2, row);
			if (time_microsec.IsNull()){
				++bad_time_count;
				continue;
			}
			std::int64_t time_micro_no = time_microsec.GetValue<std::int64_t>();

			auto time_nanosec = chunk -> GetValue(3, row);
			if (time_nanosec.IsNull()){
				++bad_time_count;
				continue;
			}
			std::int64_t time_nano_no = time_nanosec.GetValue<std::int64_t>();
			auto nano_micro_parse = nanos_of_day(time_micro_no, time_nano_no);
			if (!nano_micro_parse){
				++bad_time_count;
				continue;
			}

			auto ticker = chunk -> GetValue(4, row);
			if (ticker.IsNull()){
				++null_ticker_count;
				continue;
			}
			std::string ticker_text = ticker.GetValue<std::string>();
			auto trading_group = chunk -> GetValue(5, row);
			if (!trading_group.IsNull()) ticker_text = ticker_text + "-" + trading_group.GetValue<std::string>();

			// Prices: a NULL, unparseable or zero side is kept as an empty side (NULL).
			bool missing_bid = false;
			std::int64_t bid_value = 0;
			bool bid_rounded = false;
			auto bid_price = chunk -> GetValue(0, row);
			if (bid_price.IsNull()){
				missing_bid = true;
				++null_price_count;
			}
			else {
				auto bid = parse_price(bid_price.GetValue<std::string>());
				if (!bid){
					missing_bid = true;
					++bad_price_count;
				}
				else if (bid -> value == 0){
					missing_bid = true;
					++zero_price_count;
				}
				else {
					bid_value = bid -> value;
					bid_rounded = bid -> rounded;
				}
			}

			bool missing_ask = false;
			std::int64_t ask_value = 0;
			bool ask_rounded = false;
			auto ask_price = chunk -> GetValue(1, row);
			if (ask_price.IsNull()){
				missing_ask = true;
				++null_price_count;
			}
			else {
				auto ask = parse_price(ask_price.GetValue<std::string>());
				if (!ask){
					missing_ask = true;
					++bad_price_count;
				}
				else if (ask -> value == 0){
					missing_ask = true;
					++zero_price_count;
				}
				else {
					ask_value = ask -> value;
					ask_rounded = ask -> rounded;
				}
			}

			if (bid_rounded || ask_rounded) ++rounded_count;
			if (!missing_bid && !missing_ask){
				if (ask_value < bid_value) ++crossed_qc;     // crossed: the ask is below the bid
				if (ask_value == bid_value) ++locked_qc;
			}

			// Sizes: read only when not NULL; a NULL size is kept as NULL.
			auto best_bid_size = chunk -> GetValue(6, row);
			bool null_bid_size = best_bid_size.IsNull();
			std::int64_t bid_size_no = 0;
			if (null_bid_size) ++null_price_size_count;
			else bid_size_no = best_bid_size.GetValue<std::int64_t>();

			auto best_ask_size = chunk -> GetValue(7, row);
			bool null_ask_size = best_ask_size.IsNull();
			std::int64_t ask_size_no = 0;
			if (null_ask_size) ++null_price_size_count;
			else ask_size_no = best_ask_size.GetValue<std::int64_t>();

			// Raw condition columns, kept as the file has them (NULL stays NULL).
			auto qu_cond = chunk -> GetValue(8, row);
			bool null_qu_cond = qu_cond.IsNull();
			std::string qu_cond_text;
			if (null_qu_cond) ++null_qu_cond_count;
			else qu_cond_text = qu_cond.GetValue<std::string>();

			auto natbbo_ind = chunk -> GetValue(9, row);
			bool null_natbbo_ind = natbbo_ind.IsNull();
			std::string natbbo_ind_text;
			if (null_natbbo_ind) ++null_natbbo_ind_count;
			else natbbo_ind_text = natbbo_ind.GetValue<std::string>();

			appender.BeginRow();
			appender.Append(ticker_text.c_str());
			appender.Append(*nano_micro_parse);

			if (missing_bid) appender.Append<std::nullptr_t>(nullptr);
			else appender.Append(bid_value);

			if (missing_ask) appender.Append<std::nullptr_t>(nullptr);
			else appender.Append(ask_value);

			if (null_bid_size) appender.Append<std::nullptr_t>(nullptr);
			else appender.Append(bid_size_no);

			if (null_ask_size) appender.Append<std::nullptr_t>(nullptr);
			else appender.Append(ask_size_no);

			if (null_qu_cond) appender.Append<std::nullptr_t>(nullptr);
			else appender.Append(qu_cond_text.c_str());

			if (null_natbbo_ind) appender.Append<std::nullptr_t>(nullptr);
			else appender.Append(natbbo_ind_text.c_str());

			appender.EndRow();
			++kept_count;
			
		}	
	}
	appender.Close();
	std::filesystem::create_directories("/mnt/data/artifacts/a1/nbbo/"); //only creates directory if it doesn't already exist
	auto copy = connection.Query("COPY nbbo_rows TO '/mnt/data/artifacts/a1/nbbo/" + day + ".parquet' (FORMAT parquet)");
	if (copy -> HasError()) return std::unexpected(copy -> GetError());
	return row_count;
}

int main(int argc, char *argv[]){
	std::string base = "/mnt/data/taq/russell_21yr/raw/complete_nbbo";
	int bad_time_count = 0;
	int null_price_count = 0;
	int bad_price_count = 0;
	int zero_price_count = 0;
	int kept_count = 0;
	int null_price_size_count = 0;
	int null_ticker_count = 0;
	int locked_qc = 0;
	int crossed_qc = 0;
	int rounded_count = 0;
	int null_qu_cond_count = 0;
	int null_natbbo_ind_count = 0;
	if (argc != 2){
		std::cerr << "Usage: " << argv[0] << " YYYY-MM-DD\n";
		return 1;
	}

	std::string day = argv[1];
	fs::path folder = fs::path(base) / day;
	if (!fs::is_directory(folder)){
		std::cerr << argv[0] << ": no data folder for day " << day << ": " << folder << "\n";
		return 1;
	}
	
	auto result = get_quote(folder, day, bad_time_count, null_price_count, bad_price_count, zero_price_count, 
		kept_count, null_price_size_count, null_ticker_count, locked_qc, crossed_qc, rounded_count, null_qu_cond_count, null_natbbo_ind_count);
	if (!result) {                       // true when it holds an error
		std::cerr << result.error() << "\n";
		return 1;
	}
	// Rows read = rows kept + rows dropped. A missing price or size no longer drops
	// the row: that side is kept empty (NULL), and the counts below are sides, not rows.
	std::cout << "Rows read: " << *result << "  kept: " << kept_count            // * gets the int out
		<< "  dropped for bad time: " << bad_time_count << "  dropped for no symbol: " << null_ticker_count << "\n"
		<< "Empty sides kept: NULL price " << null_price_count << ", bad price " << bad_price_count
		<< ", zero price " << zero_price_count << ", NULL size " << null_price_size_count << "\n"
		<< "Two-sided quotes: locked " << locked_qc << ", crossed " << crossed_qc
		<< "  Rounded prices: " << rounded_count << " Null qu cond: " << null_qu_cond_count 
		<< " Null natbbo ind: " << null_natbbo_ind_count << "\n";
}
