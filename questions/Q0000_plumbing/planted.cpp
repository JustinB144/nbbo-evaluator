#include <duckdb.hpp>
#include <iostream>
#include <string>
int main(){
    duckdb::DuckDB database(nullptr);
    duckdb::Connection connection(database);
    //step 1
    auto days = connection.Query("SELECT day::VARCHAR FROM read_csv('docs/quick_subset.csv') ORDER BY day");
    if (days -> HasError()){
        std::cerr << "ERROR reading docs/quick_subset.csv: " << days -> GetError() << std::endl;
        return 1;
    }

    //step 2
    auto create_table = connection.Query("CREATE TABLE planted (day DATE, symbol VARCHAR, event_time BIGINT, true_move DOUBLE)");
    if (create_table -> HasError()){
        std::cerr << "ERROR creating table planted: " <<  create_table -> GetError() << std::endl;
        return 1;
    }

    auto fill_table = connection.Prepare(R"sql(
            INSERT INTO planted
            WITH q AS (SELECT symbol, nanos, bid, ask FROM read_parquet(?)),
                top AS (SELECT symbol FROM q GROUP BY symbol ORDER BY count(*) DESC, symbol LIMIT 5),
                e AS (SELECT symbol, 36000::BIGINT * 1000000000 + i * 30::BIGINT * 1000000000 AS event_time
                    FROM top, range(600) r(i))
            SELECT ?::DATE, e.symbol, e.event_time,
                   ((q1.bid + q1.ask) / 2 - (q0.bid + q0.ask) / 2) / ((q0.bid + q0.ask) / 2) * 10000
            FROM e
            ASOF JOIN q q0 ON e.symbol = q0.symbol AND e.event_time >= q0.nanos
            ASOF JOIN q q1 ON e.symbol = q1.symbol AND e.event_time + 10000000000 >= q1.nanos)sql");
    
    if (fill_table -> HasError()){
        std::cerr << "ERROR preparing the insert into planted: " <<  fill_table -> GetError() << std::endl;
        return 1;
    }

    for (duckdb::idx_t r = 0; r < days -> RowCount(); ++r){
        std::string day = days -> GetValue(0, r).ToString();
        auto result = fill_table->Execute(duckdb::Value("/mnt/data/artifacts/a1/nbbo/" + day + ".parquet"), duckdb::Value(day));
        if (result -> HasError()){
            std::cerr << "ERROR filling planted for " << day << ": " <<  result -> GetError() << std::endl;
            return 1;
        }
    }
    std::cout << connection.Query("SELECT day, count(*) FROM planted GROUP BY day ORDER BY day")->ToString();
}
