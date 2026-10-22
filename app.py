import sqlite3
import pandas as pd
import streamlit as st

st.set_page_config(
    page_title="MLB 選手キャリア＆チーム補強ダッシュボード", layout="wide"
)

DB_PATH = "mlb_player_stats.db"


@st.cache_data
def get_teams_2026():
    conn = sqlite3.connect(DB_PATH)
    query = """
        SELECT DISTINCT team_name FROM batting_stats WHERE season = 2026 AND team_name IS NOT NULL
        UNION
        SELECT DISTINCT team_name FROM pitching_stats WHERE season = 2026 AND team_name IS NOT NULL
        ORDER BY team_name
    """
    try:
        teams = pd.read_sql_query(query, conn)["team_name"].dropna().tolist()
    except Exception:
        teams = []
    conn.close()
    return teams


@st.cache_data
def get_roster_2026(team_name):
    conn = sqlite3.connect(DB_PATH)
    query_b = "SELECT DISTINCT player_id, player_name FROM batting_stats WHERE season = 2026 AND team_name = ?"
    query_p = "SELECT DISTINCT player_id, player_name FROM pitching_stats WHERE season = 2026 AND team_name = ?"

    df_b = pd.read_sql_query(query_b, conn, params=(team_name,))
    df_p = pd.read_sql_query(query_p, conn, params=(team_name,))
    conn.close()

    df_combined = pd.concat([df_b, df_p]).drop_duplicates(subset=["player_id"])
    return df_combined.sort_values(by="player_name")


def get_player_history(player_id):
    conn = sqlite3.connect(DB_PATH)
    query_b = "SELECT * FROM batting_stats WHERE CAST(player_id AS TEXT) = ? ORDER BY season DESC"
    query_p = "SELECT * FROM pitching_stats WHERE CAST(player_id AS TEXT) = ? ORDER BY season DESC"

    df_b = pd.read_sql_query(query_b, conn, params=(str(player_id),))
    df_p = pd.read_sql_query(query_p, conn, params=(str(player_id),))
    conn.close()
    return df_b, df_p


def get_player_transactions(player_id):
    conn = sqlite3.connect(DB_PATH)
    query = "SELECT date, type, description, from_team, to_team FROM transactions WHERE CAST(player_id AS TEXT) = ? ORDER BY date DESC"
    try:
        df_trans = pd.read_sql_query(query, conn, params=(str(player_id),))
    except Exception:
        df_trans = pd.DataFrame()
    conn.close()
    return df_trans


def get_team_reinforcements(team_name, season):
    """指定チーム・年度の補強(IN)および放出(OUT)を厳密に定義して抽出。

    Assigned 等のチーム内移動は IN/OUT から除外します。
    """
    conn = sqlite3.connect(DB_PATH)

    # 1. 公式トランザクションデータの取得
    query = """
        SELECT date as 日付, type as 種別, player_name as 選手名, from_team as 旧所属, to_team as 新所属, description as 詳細
        FROM team_transactions 
        WHERE (from_team = ? OR to_team = ?) AND season = ?
        ORDER BY date DESC
    """
    try:
        df = pd.read_sql_query(query, conn, params=(team_name, team_name, season))
    except Exception:
        df = pd.DataFrame()

    # 対象となる指定キーワード（部分一致対応）
    IN_TYPES = [
        "Signed",
        "Signed as Free Agent",
        "Claimed Off Waivers",
        "Trade",
        "Traded",
    ]
    OUT_TYPES = [
        "Claimed Off Waivers",
        "Trade",
        "Traded",
        "Released",
        "Designated for Assignment",
    ]

    def judge_direction(row):
        t_type = str(row["種別"])

        # Assigned（ロースター割り当て等）が含まれている場合は IN/OUT 対象外
        if "assigned" in t_type.lower():
            return "OTHER"

        is_to_me = row["新所属"] == team_name
        is_from_me = row["旧所属"] == team_name

        # 補強(IN) 判定
        if is_to_me and any(k.lower() in t_type.lower() for k in IN_TYPES):
            return "IN"

        # 放出(OUT) 判定
        if is_from_me and any(k.lower() in t_type.lower() for k in OUT_TYPES):
            return "OUT"

        return "OTHER"

    if not df.empty:
        df["区分"] = df.apply(judge_direction, axis=1)
    else:
        df = pd.DataFrame(
            columns=[
                "日付",
                "種別",
                "選手名",
                "旧所属",
                "新所属",
                "詳細",
                "区分",
            ]
        )

    # 2. シーズン終了後のFA退団（契約満了）の補完検知
    fa_departures = []
    try:
        q_current = f"""
            SELECT DISTINCT player_id, player_name FROM batting_stats WHERE season = {season} AND team_name = '{team_name}'
            UNION
            SELECT DISTINCT player_id, player_name FROM pitching_stats WHERE season = {season} AND team_name = '{team_name}'
        """
        q_next = f"""
            SELECT DISTINCT player_id, team_name FROM batting_stats WHERE season = {season + 1}
            UNION
            SELECT DISTINCT player_id, team_name FROM pitching_stats WHERE season = {season + 1}
        """

        df_curr = pd.read_sql_query(q_current, conn)
        df_next = pd.read_sql_query(q_next, conn)

        if not df_curr.empty:
            for _, p in df_curr.iterrows():
                p_id = p["player_id"]
                p_name = p["player_name"]

                next_teams = df_next[df_next["player_id"] == p_id]["team_name"].tolist()

                if team_name not in next_teams:
                    already_logged = not df[
                        (df["選手名"] == p_name) & (df["区分"] == "OUT")
                    ].empty

                    if not already_logged:
                        fa_departures.append(
                            {
                                "日付": f"{season}-11-01 (オフシーズン)",
                                "種別": "FA Departure",
                                "選手名": p_name,
                                "旧所属": team_name,
                                "新所属": (
                                    next_teams[0] if next_teams else "FA / 未所属"
                                ),
                                "詳細": f"{season}年シーズン終了に伴うFA権行使・退団",
                                "区分": "OUT",
                            }
                        )
    except Exception:
        pass

    conn.close()

    if fa_departures:
        df_fa = pd.DataFrame(fa_departures)
        df = pd.concat([df, df_fa], ignore_index=True)

    return df


# --- UI アプリメインレイアウト ---

st.title("⚾ MLB 選手過去10年データ＆チーム補強検索ダッシュボード")

mode = st.sidebar.radio(
    "📌 表示モード切替",
    ["👤 選手検索（個人キャリア）", "🏢 チーム補強・放出・公示一覧"],
)

teams = get_teams_2026()
if not teams:
    st.error("2026年のデータが見つかりませんでした。データベースを確認してください。")
    st.stop()


# ------------------------------------------------------------------
# モード 1: 👤 選手検索（個人キャリア）
# ------------------------------------------------------------------
if mode == "👤 選手検索（個人キャリア）":
    selected_team = st.sidebar.selectbox("① チームを選択してください", teams)

    if selected_team:
        st.header(f"🏢 {selected_team} (2026年所属選手)")

        roster_df = get_roster_2026(selected_team)

        if roster_df.empty:
            st.warning("該当する選手データがありません。")
        else:
            player_names = roster_df["player_name"].tolist()
            selected_player_name = st.selectbox(
                "② 選手を選択してください", player_names
            )

            selected_player_id = roster_df[
                roster_df["player_name"] == selected_player_name
            ]["player_id"].values[0]

            st.divider()

            if selected_player_id is not None:
                st.subheader(f"👤 {selected_player_name} 選手のキャリア情報")

                tab_stats, tab_trans = st.tabs(
                    ["📊 成績推移 (2017–2026)", "📜 移籍・公示履歴 (Transactions)"]
                )

                with tab_stats:
                    df_b_hist, df_p_hist = get_player_history(selected_player_id)

                    if not df_b_hist.empty:
                        st.write("### 🏏 打撃成績")
                        cols_to_drop = [
                            c
                            for c in ["player_id", "team_id"]
                            if c in df_b_hist.columns
                        ]
                        df_b_display = df_b_hist.drop(columns=cols_to_drop)
                        first_cols = [
                            c
                            for c in ["season", "team_name", "player_name"]
                            if c in df_b_display.columns
                        ]
                        other_cols = [
                            c for c in df_b_display.columns if c not in first_cols
                        ]
                        st.dataframe(
                            df_b_display[first_cols + other_cols],
                            use_container_width=True,
                        )

                    if not df_p_hist.empty:
                        st.write("### ⚾ 投手成績")
                        cols_to_drop = [
                            c
                            for c in ["player_id", "team_id"]
                            if c in df_p_hist.columns
                        ]
                        df_p_display = df_p_hist.drop(columns=cols_to_drop)
                        first_cols = [
                            c
                            for c in ["season", "team_name", "player_name"]
                            if c in df_p_display.columns
                        ]
                        other_cols = [
                            c for c in df_p_display.columns if c not in first_cols
                        ]
                        st.dataframe(
                            df_p_display[first_cols + other_cols],
                            use_container_width=True,
                        )

                with tab_trans:
                    df_trans = get_player_transactions(selected_player_id)
                    if not df_trans.empty:
                        st.write("### 📜 公式公示・移籍タイムライン")
                        df_trans_display = df_trans.rename(
                            columns={
                                "date": "日付",
                                "type": "公式種別",
                                "description": "詳細内容",
                                "from_team": "旧所属",
                                "to_team": "新所属",
                            }
                        )
                        st.dataframe(df_trans_display, use_container_width=True)
                    else:
                        st.info("この選手の移籍・公示履歴データはありません。")


# ------------------------------------------------------------------
# モード 2: 🏢 チーム補強・放出・公示一覧
# ------------------------------------------------------------------
elif mode == "🏢 チーム補強・放出・公示一覧":
    st.header("🏢 チーム別 補強(IN)・放出(OUT)・全公示動向")

    col1, col2 = st.columns(2)
    with col1:
        selected_team = st.selectbox("① チームを選択", teams)
    with col2:
        selected_year = st.selectbox("② 対象年度を選択", list(range(2026, 2016, -1)))

    if selected_team and selected_year:
        df_reinforce = get_team_reinforcements(selected_team, selected_year)

        if not df_reinforce.empty:
            df_in = df_reinforce[df_reinforce["区分"] == "IN"].drop(columns=["区分"])
            df_out = df_reinforce[df_reinforce["区分"] == "OUT"].drop(columns=["区分"])
            df_other = df_reinforce[df_reinforce["区分"] == "OTHER"].drop(
                columns=["区分"]
            )

            m1, m2, m3 = st.columns(3)
            m1.metric("🟩 補強 (IN)", f"{len(df_in)} 件")
            m2.metric("🟥 放出 (OUT)", f"{len(df_out)} 件")
            m3.metric("🔄 その他 (契約更新/IL指定等)", f"{len(df_other)} 件")

            st.divider()

            tab_in, tab_out, tab_all = st.tabs(
                [
                    f"🟩 補強 (IN): {len(df_in)}件",
                    f"🟥 放出 (OUT): {len(df_out)}件",
                    f"📋 全公示履歴: {len(df_reinforce)}件",
                ]
            )

            # 🟩 IN タブ
            with tab_in:
                st.subheader(
                    f"🟩 {selected_team} への加入・獲得選手 ({selected_year}年)"
                )
                if not df_in.empty:
                    st.dataframe(
                        df_in[["日付", "種別", "選手名", "旧所属", "詳細"]],
                        use_container_width=True,
                    )
                else:
                    st.info(
                        "指定された条件（Signed, Trade, Waivers等）の補強データはありません。"
                    )

            # 🟥 OUT タブ
            with tab_out:
                st.subheader(
                    f"🟥 {selected_team} からの退団・放出選手 ({selected_year}年)"
                )
                if not df_out.empty:
                    st.dataframe(
                        df_out[["日付", "種別", "選手名", "新所属", "詳細"]],
                        use_container_width=True,
                    )
                else:
                    st.info(
                        "指定された条件（DFA, Release, Trade, FA退団等）の放出データはありません。"
                    )

            # 📋 全公示 タブ
            with tab_all:
                st.subheader(f"📋 {selected_team} 全公示データ ({selected_year}年)")
                st.dataframe(
                    df_reinforce[
                        ["日付", "種別", "選手名", "旧所属", "新所属", "詳細"]
                    ],
                    use_container_width=True,
                )
        else:
            st.info("該当するデータがありません。")
