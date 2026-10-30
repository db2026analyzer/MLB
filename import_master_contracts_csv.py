import re
import sqlite3
import pandas as pd

DB_PATH = "mlb_player_stats.db"


def parse_money(val):
    if pd.isna(val) or not isinstance(val, str):
        return None
    val = val.strip().replace("$", "")
    if "M" in val:
        try:
            return float(val.replace("M", "")) * 1_000_000
        except ValueError:
            return None
    elif "K" in val:
        try:
            return float(val.replace("K", "")) * 1_000
        except ValueError:
            return None
    try:
        return float(val)
    except ValueError:
        return None


def parse_int_safe(val, default=1):
    if pd.isna(val):
        return default
    val_str = str(val).strip()
    match = re.search(r"\d+", val_str)
    if match:
        return int(match.group())
    return default


def parse_service_time(st_str):
    try:
        val = float(st_str)
        years = int(val)
        days = int(round((val - years) * 1000))
        return years, days
    except Exception:
        return 0, 0


def format_service_time(years, days):
    if days < 0:
        years -= 1
        days += 172
    if years < 0:
        return "0.000"
    return f"{years}.{days:03d}"


def estimate_past_salary(srv_years, current_salary, diff_years):
    if srv_years < 3:
        return 780000.0
    elif srv_years < 6:
        est = current_salary * (0.75**diff_years)
        return max(est, 780000.0)
    else:
        return current_salary


def import_csv_to_db(csv_path="contract_data.csv"):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute("DROP TABLE IF EXISTS contracts")
    cursor.execute("""
        CREATE TABLE contracts (
            player_id INTEGER,
            player_name TEXT,
            season INTEGER,
            salary REAL,
            aav REAL,
            service_time TEXT,
            contract_years INTEGER,
            free_agent_year INTEGER,
            contract_status TEXT,
            PRIMARY KEY (player_name, season)
        )
    """)

    q_players = """
        SELECT DISTINCT player_id, player_name FROM batting_stats WHERE player_name IS NOT NULL
        UNION
        SELECT DISTINCT player_id, player_name FROM pitching_stats WHERE player_name IS NOT NULL
    """
    try:
        df_players = pd.read_sql_query(q_players, conn)
        name_to_id = dict(zip(df_players["player_name"], df_players["player_id"]))
    except Exception:
        name_to_id = {}

    try:
        df = pd.read_csv(csv_path)
    except FileNotFoundError:
        print(f"⚠️ {csv_path} が見つかりませんでした。")
        conn.close()
        return

    records = []

    for _, row in df.iterrows():
        p_name = row.get("Name")
        if pd.isna(p_name):
            continue

        p_id = name_to_id.get(p_name, None)
        srv_tm_raw = str(row.get("SrvTm")) if pd.notna(row.get("SrvTm")) else "0.000"
        contract_status_raw = (
            str(row.get("Contract Status")).strip()
            if pd.notna(row.get("Contract Status"))
            else "1 yr"
        )

        # FA年推定
        fa_year = None
        for col_yr in range(2026, 2036):
            if str(row.get(str(col_yr))).strip() == "FA":
                fa_year = col_yr
                break

        salary_2026 = (
            parse_money(str(row.get("2026"))) if pd.notna(row.get("2026")) else 780000.0
        )
        if salary_2026 is None:
            salary_2026 = 780000.0

        contract_yrs = parse_int_safe(row.get("Yrs"), default=1)
        aav_val = salary_2026

        curr_y, curr_d = parse_service_time(srv_tm_raw)
        formatted_curr_srv = format_service_time(curr_y, curr_d)

        for season in range(2017, 2027):
            diff = 2026 - season
            past_y = curr_y - diff
            past_srv_years = max(0, past_y)

            if season == 2026:
                past_salary = salary_2026
            else:
                past_salary = estimate_past_salary(past_srv_years, salary_2026, diff)

            records.append(
                (
                    p_id,
                    p_name,
                    season,
                    past_salary,
                    aav_val,
                    formatted_curr_srv,  # 2026年現在のMLSで固定
                    contract_yrs,
                    int(fa_year) if fa_year else int(2026 + max(0, 6 - curr_y)),
                    contract_status_raw,
                )
            )

    cursor.executemany(
        """
        INSERT OR REPLACE INTO contracts 
        (player_id, player_name, season, salary, aav, service_time, contract_years, free_agent_year, contract_status)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """,
        records,
    )

    conn.commit()
    conn.close()
    print(f"✨ 成功: {len(records)} 件の契約データを DB に正常取り込みしました！")


if __name__ == "__main__":
    import_csv_to_db()
