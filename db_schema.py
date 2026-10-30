import os
import sqlite3
import pandas as pd

DB_PATH = "mlb_player_stats.db"


def setup_normalized_schema():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # 1. 選手マスター (players) の定義
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS players (
        player_id INTEGER PRIMARY KEY,
        player_name TEXT NOT NULL,
        birth_date TEXT,
        bats TEXT,
        throws TEXT,
        height TEXT,
        weight INTEGER,
        primary_pos TEXT
    )
    """)

    # 既存テーブルに primary_pos カラムが存在しない場合は動的に追加
    cursor.execute("PRAGMA table_info(players)")
    columns = [column[1] for column in cursor.fetchall()]
    if "primary_pos" not in columns:
        cursor.execute("ALTER TABLE players ADD COLUMN primary_pos TEXT")

    # 2. 契約マスター & 詳細 (contracts_master & contract_details)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS contracts_master (
        contract_id INTEGER PRIMARY KEY AUTOINCREMENT,
        player_id INTEGER NOT NULL,
        total_years INTEGER,
        total_amount REAL,
        free_agent_year INTEGER,
        contract_status TEXT,
        service_time TEXT,
        FOREIGN KEY(player_id) REFERENCES players(player_id)
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS contract_details (
        detail_id INTEGER PRIMARY KEY AUTOINCREMENT,
        contract_id INTEGER NOT NULL,
        season INTEGER NOT NULL,
        salary REAL,
        aav REAL,
        option_type TEXT,
        buyout REAL DEFAULT 0.0,
        incentive REAL DEFAULT 0.0,
        FOREIGN KEY(contract_id) REFERENCES contracts_master(contract_id),
        UNIQUE(contract_id, season)
    )
    """)

    # 3. FanGraphs 高度打撃・守備指標テーブル
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS batting_advanced (
        player_id INTEGER,
        player_name TEXT,
        season INTEGER,
        wraa REAL,
        wsb REAL,
        woba REAL,
        xwoba REAL,
        barrel_pct REAL,
        hardhit_pct REAL,
        PRIMARY KEY (player_id, season)
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS fielding_advanced (
        player_id INTEGER,
        player_name TEXT,
        season INTEGER,
        pos TEXT,
        oaa REAL,
        uzr REAL,
        drs REAL,
        PRIMARY KEY (player_id, season, pos)
    )
    """)

    # 4. 既存互換用ビュー (V_contracts_legacy)
    cursor.execute("""
    CREATE VIEW IF NOT EXISTS V_contracts_legacy AS
    SELECT 
        p.player_id,
        p.player_name,
        cd.season,
        cd.salary,
        cd.aav,
        cm.service_time,
        cm.total_years AS contract_years,
        cm.free_agent_year,
        cm.contract_status,
        cd.option_type,
        cd.buyout
    FROM contract_details cd
    JOIN contracts_master cm ON cd.contract_id = cm.contract_id
    JOIN players p ON cm.player_id = p.player_id
    """)

    conn.commit()

    # --- 既存データの抽出・移行 ---
    # 選手マスター移行
    cursor.execute("""
    INSERT OR IGNORE INTO players (player_id, player_name, primary_pos)
    SELECT DISTINCT player_id, player_name, pos FROM batting_stats WHERE player_id IS NOT NULL
    UNION
    SELECT DISTINCT player_id, player_name, pos FROM pitching_stats WHERE player_id IS NOT NULL
    """)

    # 契約移行
    cursor.execute("SELECT DISTINCT player_id, player_name FROM contracts")
    existing_contracts = cursor.fetchall()
    for p_id, p_name in existing_contracts:
        if not p_id:
            continue
        cursor.execute(
            "SELECT contract_id FROM contracts_master WHERE player_id = ?",
            (p_id,),
        )
        if not cursor.fetchone():
            cursor.execute(
                """
                INSERT INTO contracts_master (player_id, total_years, free_agent_year, contract_status, service_time)
                SELECT player_id, contract_years, free_agent_year, contract_status, service_time 
                FROM contracts WHERE player_id = ? ORDER BY season DESC LIMIT 1
            """,
                (p_id,),
            )
            c_id = cursor.lastrowid
            cursor.execute(
                """
                INSERT OR IGNORE INTO contract_details (contract_id, season, salary, aav, option_type)
                SELECT ?, season, salary, aav, COALESCE(contract_status, 'None') FROM contracts WHERE player_id = ?
            """,
                (c_id, p_id),
            )

    conn.commit()

    # --- FanGraphs CSVの自動ロード (存在する場合) ---
    for csv_file, table_name in [
        ("batting_advanced_stats_2.csv", "batting_advanced"),
        ("fielding_advanced_stats_2.csv", "fielding_advanced"),
    ]:
        if os.path.exists(csv_file):
            try:
                df_fg = pd.read_csv(csv_file)
                # 列名のクリーンアップ・マッピング処理
                df_fg.to_sql(table_name, conn, if_exists="append", index=False)
                print(f"✅ {csv_file} を {table_name} にインポートしました。")
            except Exception as e:
                print(f"⚠️ {csv_file} のインポート失敗: {e}")

    conn.close()
    print("🎉 DB正規化および移行が完了しました！")


if __name__ == "__main__":
    setup_normalized_schema()
