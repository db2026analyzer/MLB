import sqlite3
import time
import unicodedata
from concurrent.futures import ThreadPoolExecutor, as_completed
import pandas as pd
import statsapi

START_YEAR = 2017
END_YEAR = 2026
MAX_WORKERS = 15  # 並列スレッド数（10〜15程度が最適）


def normalize_name(text):
    if not isinstance(text, str):
        return text
    normalized = unicodedata.normalize("NFD", text)
    return "".join(c for c in normalized if unicodedata.category(c) != "Mn")


def get_2026_player_ids():
    """2026年の全選手IDリストを取得"""
    print("2026年の選手一覧を取得中...")
    players = {}

    for group in ["hitting", "pitching"]:
        data = statsapi.get(
            "stats",
            {
                "stats": "season",
                "group": group,
                "season": 2026,
                "gameType": "R",
                "playerPool": "all",
                "limit": 10000,
            },
        )

        splits = data.get("stats", [{}])[0].get("splits", [])
        for item in splits:
            p = item.get("player", {})
            if p.get("id"):
                players[p.get("id")] = p.get("fullName")

    print(f"対象選手数: {len(players)} 名")
    return players


def fetch_single_player_data(player_args):
    """【並列処理用】1選手分の成績・移籍履歴を取得する関数"""
    player_id, player_name = player_args
    batting_rows = []
    pitching_rows = []
    transaction_rows = []

    try:
        data = statsapi.get(
            "person",
            {
                "personId": player_id,
                "hydrate": "stats(type=yearByYear,gameType=R),transactions",
            },
        )
        people = data.get("people", [])
        if not people:
            return batting_rows, pitching_rows, transaction_rows

        person = people[0]

        # 1. 成績データ
        stats = person.get("stats", [])
        for stat_group in stats:
            group_name = stat_group.get("group", {}).get("displayName")
            splits = stat_group.get("splits", [])

            for item in splits:
                season = item.get("season")
                if not season:
                    continue

                season_num = int(season)
                if season_num < START_YEAR or season_num > END_YEAR:
                    continue

                team = item.get("team", {})
                team_name = team.get("name")
                if not team_name:
                    continue

                stat = item.get("stat", {})
                row = {
                    "season": season_num,
                    "player_id": player_id,
                    "player_name": player_name,
                    "team_id": team.get("id"),
                    "team_name": team_name,
                }
                row.update(stat)

                if group_name == "hitting":
                    batting_rows.append(row)
                elif group_name == "pitching":
                    pitching_rows.append(row)

        # 2. 移籍・公示履歴
        transactions = person.get("transactions", [])
        for t in transactions:
            date_str = t.get("date", "")
            season_val = (
                int(date_str[:4])
                if len(date_str) >= 4 and date_str[:4].isdigit()
                else None
            )

            if season_val and (START_YEAR <= season_val <= END_YEAR):
                transaction_rows.append(
                    {
                        "season": season_val,
                        "player_id": player_id,
                        "player_name": player_name,
                        "date": date_str,
                        "type": t.get("typeDesc"),
                        "description": t.get("description"),
                        "from_team": t.get("fromTeam", {}).get("name", "-"),
                        "to_team": t.get("toTeam", {}).get("name", "-"),
                    }
                )

    except Exception:
        pass

    return batting_rows, pitching_rows, transaction_rows


def main():
    start_time = time.time()
    player_dict = get_2026_player_ids()

    all_batting = []
    all_pitching = []
    all_transactions = []

    total_players = len(player_dict)
    player_items = list(player_dict.items())

    print(
        f"\n⚡ {MAX_WORKERS} スレッドで全{total_players}名のデータを高速並列取得中..."
    )

    # ThreadPoolExecutor を使用して並列リクエストを実行
    completed_count = 0
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = [
            executor.submit(fetch_single_player_data, item) for item in player_items
        ]

        for future in as_completed(futures):
            b_rows, p_rows, t_rows = future.result()
            all_batting.extend(b_rows)
            all_pitching.extend(p_rows)
            all_transactions.extend(t_rows)

            completed_count += 1
            if completed_count % 100 == 0 or completed_count == total_players:
                print(f"  └ 進捗: {completed_count}/{total_players} 名完了")

    df_batting_all = pd.DataFrame(all_batting)
    df_pitching_all = pd.DataFrame(all_pitching)
    df_trans_all = pd.DataFrame(all_transactions)

    print("\n選手名の正規化・重複削除を実行中...")
    if not df_batting_all.empty:
        df_batting_all["player_name"] = df_batting_all["player_name"].apply(
            normalize_name
        )
        df_batting_all = df_batting_all.drop_duplicates()

    if not df_pitching_all.empty:
        df_pitching_all["player_name"] = df_pitching_all["player_name"].apply(
            normalize_name
        )
        df_pitching_all = df_pitching_all.drop_duplicates()

    if not df_trans_all.empty:
        df_trans_all["player_name"] = df_trans_all["player_name"].apply(normalize_name)
        df_trans_all = df_trans_all.drop_duplicates()

    # CSV保存
    df_batting_all.to_csv(
        "mlb_batting_stats_2017_2026.csv", index=False, encoding="utf-8-sig"
    )
    df_pitching_all.to_csv(
        "mlb_pitching_stats_2017_2026.csv", index=False, encoding="utf-8-sig"
    )
    df_trans_all.to_csv("mlb_transactions.csv", index=False, encoding="utf-8-sig")

    # SQLite保存
    conn = sqlite3.connect("mlb_player_stats.db")
    df_batting_all.to_sql("batting_stats", conn, if_exists="replace", index=False)
    df_pitching_all.to_sql("pitching_stats", conn, if_exists="replace", index=False)
    df_trans_all.to_sql("transactions", conn, if_exists="replace", index=False)
    df_trans_all.to_sql("team_transactions", conn, if_exists="replace", index=False)
    conn.close()

    elapsed_time = round(time.time() - start_time, 2)
    print("\n==========================================")
    print(f"🎉 高速取得完了！ (所要時間: {elapsed_time} 秒)")
    print(f"・打者成績: {len(df_batting_all)} 行")
    print(f"・投手成績: {len(df_pitching_all)} 行")
    print(f"・全公示・移籍履歴: {len(df_trans_all)} 行")
    print("==========================================")


if __name__ == "__main__":
    main()
