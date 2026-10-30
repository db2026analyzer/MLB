import datetime
import sqlite3
import pandas as pd
import statsapi

DB_PATH = "mlb_player_stats.db"


def run_incremental_update():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # DB内の最終公示日付を取得
    cursor.execute("SELECT MAX(date) FROM transactions")
    last_date_str = cursor.fetchone()[0]

    if not last_date_str:
        start_date = "2026-01-01"
    else:
        # 最終更新日の翌日から取得
        last_date = datetime.datetime.strptime(last_date_str[:10], "%Y-%m-%d").date()
        start_date = (last_date + datetime.timedelta(days=1)).strftime("%Y-%m-%d")

    today_str = datetime.date.today().strftime("%Y-%m-%d")

    if start_date > today_str:
        print("⚡ データは既に最新状態です。")
        conn.close()
        return

    print(f"🔄 差分データを取得中 ({start_date} ～ {today_str})...")

    try:
        # 最新トランザクション（公示）の取得
        trans = statsapi.get(
            "transactions",
            {"startDate": start_date, "endDate": today_str},
        )
        new_trans = []
        for t in trans.get("transactions", []):
            p_id = t.get("person", {}).get("id")
            p_name = t.get("person", {}).get("fullName")
            date_val = t.get("date")
            if p_id and date_val:
                new_trans.append(
                    {
                        "season": int(date_val[:4]),
                        "player_id": p_id,
                        "player_name": p_name,
                        "date": date_val,
                        "type": t.get("typeDesc"),
                        "description": t.get("description"),
                        "from_team": t.get("fromTeam", {}).get("name", "-"),
                        "to_team": t.get("toTeam", {}).get("name", "-"),
                    }
                )

        if new_trans:
            df_new = pd.DataFrame(new_trans)
            df_new.to_sql("transactions", conn, if_exists="append", index=False)
            df_new.to_sql("team_transactions", conn, if_exists="append", index=False)
            print(f"✅ {len(new_trans)} 件の最新公示データを反映しました。")
        else:
            print("新規の公示データはありませんでした。")

    except Exception as e:
        print(f"⚠️ 差分更新中にエラーが発生しました: {e}")

    conn.close()


if __name__ == "__main__":
    run_incremental_update()
