#include <cstring>
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

std::expected<int, std::string> get_quote(const fs::path &folder, std::string day, int &bad_time_count, int &null_price_count, int &bad_price_count, int &zero_price_count, int &kept_count, int &null_price_size_count, int &null_ticker_count){
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
				CAST(best_asksizeshares AS BIGINT) AS best_ask_size
			FROM read_parquet(')sql"
			+ folder.string()
			+ R"sql(/*.parquet')
			WHERE time_m >= TIME '09:30:00' AND time_m < TIME '16:00:00'
			ORDER BY ticker, trading_class, time_micro, time_nano;
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
				CAST(best_asksizeshares AS BIGINT) AS best_ask_size
			FROM read_parquet(')sql"
			+ folder.string()
			+ R"sql(/*.parquet')
			WHERE time_m >= TIME '09:30:00' AND time_m < TIME '16:00:00'
			ORDER BY ticker, trading_class, time_micro, time_nano;
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
	└────────┴───────────────┘ 
	*/
	
	auto quote_statement = connection.Query(sql);
	if (quote_statement->HasError()) {
		return std::unexpected(quote_statement->GetError());
	}

	while (true) {
		auto chunk = quote_statement->Fetch();
		if (chunk == nullptr) {
			break;  // no more data
		}
		for (duckdb::idx_t row = 0; row < chunk->size(); ++row){
			++row_count;

			auto bid_price = chunk -> GetValue(0, row);
			if (bid_price.IsNull()){
				++null_price_count;
				continue;
			}
			std::string bid_text = bid_price.GetValue<std::string>();
			auto bid = parse_price(bid_text);
			if (!bid){
				++bad_price_count;
				continue;
			}
			if (bid -> value == 0){
				++zero_price_count;
				continue;
			}
			
			auto ask_price = chunk -> GetValue(1, row);
			if (ask_price.IsNull()){
				++null_price_count;
				continue;
			}	
			std::string ask_text = ask_price.GetValue<std::string>();
			auto ask = parse_price(ask_text);
			if (!ask){
				++bad_price_count;
				continue;
			}
			if (ask -> value == 0){
				++zero_price_count;
				continue;
			}
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
			std::int64_t time_nano_no = time_nanosec.GetValue<int64_t>();
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
			
			
			auto best_bid_size = chunk -> GetValue(6, row);
			if (best_bid_size.IsNull()){
				++null_price_size_count;
				continue;
			}
			std::int64_t bid_size_no = best_bid_size.GetValue<std::int64_t>();
				
			auto best_ask_size = chunk -> GetValue(7, row);
			if (best_ask_size.IsNull()){
				++null_price_size_count;
				continue;
			}
			std::int64_t ask_size_no = best_ask_size.GetValue<int64_t>();

			++kept_count;
		}
	}
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
	
	auto result = get_quote(folder, day, bad_time_count, null_price_count, bad_price_count, zero_price_count, kept_count, null_price_size_count, null_ticker_count);
	if (!result) {                       // true when it holds an error
		std::cerr << result.error() << "\n";
		return 1;
	}
	std::cout << "Row count: " << *result << " Rows kept: " << kept_count << " Bad times: " << bad_time_count << " Null prices: " << null_price_count << " Bad prices: " << bad_price_count << " Zero prices: " << zero_price_count << " Null price sizes: " 
		<< null_price_size_count << " Null symbols: " << null_ticker_count << "\n";   // * gets the int out
}
