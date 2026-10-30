import sqlite3
import time
import unicodedata
from concurrent.futures import ThreadPoolExecutor, as_completed
import pandas as pd
import statsapi

START_YEAR = 2017
END_YEAR = 2026
MAX_WORKERS = 15


def normalize_name(text):
    if not isinstance(text, str):
        return text
    normalized = unicodedata.normalize("NFD", text)
    return "".join(c for c in normalized if unicodedata.category(c) != "Mn")


def get_2026_player_ids():
    """2026年の全選手IDおよびメインポジションを取得"""
    print("全選手一覧および基本ポジションを取得中...")
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
            p_id = p.get("id")
            if p_id and p_id not in players:
                pos = p.get("primaryPosition", {}).get("abbreviation", "DH")
                players[p_id] = {
                    "name": p.get("fullName"),
                    "pos": pos,
                }

    print(f"対象選手数: {len(players)} 名")
    return players


def fetch_single_player_data(player_args):
    """1選手分の打撃・投手成績（両方）および移籍履歴を取得"""
    player_id, p_info = player_args
    player_name = p_info["name"]
    default_pos = p_info["pos"]

    batting_rows = []
    pitching_rows = []
    transaction_rows = []

    try:
        data = statsapi.get(
            "person",
            {
                "personId": player_id,
                "hydrate": "stats(type=[yearByYear,statSplits],gameType=R,group=[hitting,pitching]),transactions",
            },
        )
        people = data.get("people", [])
        if not people:
            return batting_rows, pitching_rows, transaction_rows

        person = people[0]
        primary_pos = person.get("primaryPosition", {}).get("abbreviation", default_pos)

        # 選手が就いたすべてのポジションを全期間から収集
        all_positions = []
        stats = person.get("stats", [])
        for stat_group in stats:
            for item in stat_group.get("splits", []):
                p_code = item.get("position", {}).get("abbreviation")
                if (
                    p_code
                    and p_code not in ["P", "TWP", "DH"]
                    and p_code not in all_positions
                ):
                    all_positions.append(p_code)

        # 複数ポジション文字列の作成 (例: "SS, 3B, 2B")
        pos_str_combined = ", ".join(all_positions) if all_positions else primary_pos

        # 1. 成績データ
        for stat_group in stats:
            group_name = stat_group.get("group", {}).get("displayName")
            type_name = stat_group.get("type", {}).get("displayName")
            if type_name != "yearByYear":
                continue

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
                    "pos": pos_str_combined,  # 複数ポジション情報を設定
                }
                row.update(stat)

                if group_name == "hitting":
                    batting_rows.append(row)
                elif group_name == "pitching":
                    if row.get("pos") in ["P", "TWP"]:
                        row["pos"] = "P"
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

    print(f"\n⚡ {MAX_WORKERS} スレッドで全{total_players}名のデータを並列取得中...")

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
    for df in [df_batting_all, df_pitching_all, df_trans_all]:
        if not df.empty:
            df["player_name"] = df["player_name"].apply(normalize_name)
            df.drop_duplicates(inplace=True)

    print("\n全期間 (2017-2026年) の契約・サービスタイム初期枠を作成中...")
    contract_rows = []
    all_player_ids = set()

    if not df_batting_all.empty:
        for p_id, p_name in (
            df_batting_all[["player_id", "player_name"]]
            .drop_duplicates()
            .itertuples(index=False)
        ):
            all_player_ids.add((p_id, p_name))

    if not df_pitching_all.empty:
        for p_id, p_name in (
            df_pitching_all[["player_id", "player_name"]]
            .drop_duplicates()
            .itertuples(index=False)
        ):
            all_player_ids.add((p_id, p_name))

    for p_id, p_name in all_player_ids:
        for yr in range(START_YEAR, END_YEAR + 1):
            contract_rows.append(
                {
                    "player_id": int(p_id),
                    "player_name": p_name,
                    "season": yr,
                    "salary": 780000.0,
                    "aav": 780000.0,
                    "service_time": f"{max(0, yr - START_YEAR)}.000",
                    "contract_years": 1,
                    "free_agent_year": yr + 3,
                }
            )

    df_contracts_all = pd.DataFrame(contract_rows).drop_duplicates(
        subset=["player_id", "season"]
    )

    # SQLite保存
    conn = sqlite3.connect("mlb_player_stats.db")
    df_batting_all.to_sql("batting_stats", conn, if_exists="replace", index=False)
    df_pitching_all.to_sql("pitching_stats", conn, if_exists="replace", index=False)
    df_trans_all.to_sql("transactions", conn, if_exists="replace", index=False)
    df_trans_all.to_sql("team_transactions", conn, if_exists="replace", index=False)
    df_contracts_all.to_sql("contracts", conn, if_exists="replace", index=False)
    conn.close()

    elapsed_time = round(time.time() - start_time, 2)
    print("\n==========================================")
    print(f"🎉 高速取得完了！ (所要時間: {elapsed_time} 秒)")
    print(f"・打者成績: {len(df_batting_all)} 行")
    print(f"・投手成績: {len(df_pitching_all)} 行")
    print(f"・全期間契約データ: {len(df_contracts_all)} 行")
    print("==========================================")


if __name__ == "__main__":
    main()
