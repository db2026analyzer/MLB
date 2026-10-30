import numpy as np
import pandas as pd

# 左右別 Park Factor (例: Fenway Park等は右/左でHR/安打補正が大きく変化)
PARK_FACTORS_DETAILED = {
    "BOS": {
        "PF_Bat_R": 108,
        "PF_Bat_L": 102,
        "PF_HR_R": 92,
        "PF_HR_L": 115,
    },  # グリーンモンスター補正
    "COL": {"PF_Bat_R": 112, "PF_Bat_L": 114, "PF_HR_R": 110, "PF_HR_L": 112},
    "SEA": {"PF_Bat_R": 92, "PF_Bat_L": 91, "PF_HR_R": 94, "PF_HR_L": 93},
    "LAD": {"PF_Bat_R": 100, "PF_Bat_L": 100, "PF_HR_R": 101, "PF_HR_L": 99},
    "NYY": {
        "PF_Bat_R": 98,
        "PF_Bat_L": 101,
        "PF_HR_R": 96,
        "PF_HR_L": 118,
    },  # 右翼ショートポルチコ
}


def calculate_advanced_batter_war(df_b, df_fg_bat=None, df_fg_field=None, bat_side="R"):
    """
    FanGraphsのwRAA, wSB, OAA/UZRを取り込んだ野手WAR算定エンジン
    WAR = (wRAA + wSB + OAA + Positional Adj + Replacement Run) / 10
    """
    if df_b.empty:
        return df_b

    df = df_b.copy()

    # FanGraphsデータの結合 (存在する場合)
    if df_fg_bat is not None and not df_fg_bat.empty:
        df = pd.merge(
            df,
            df_fg_bat[
                [
                    "player_id",
                    "season",
                    "wraa",
                    "wsb",
                    "xwoba",
                    "barrel_pct",
                    "hardhit_pct",
                ]
            ],
            on=["player_id", "season"],
            how="left",
        )

    if df_fg_field is not None and not df_fg_field.empty:
        df = pd.merge(
            df,
            df_fg_field[["player_id", "season", "oaa", "uzr"]],
            on=["player_id", "season"],
            how="left",
        )

    # デフォルト補完ロジック
    pa = pd.to_numeric(df.get("plateAppearances", 0), errors="coerce").fillna(0)
    ops = pd.to_numeric(df.get("ops", 0.710), errors="coerce").fillna(0.710)

    # 左右別 Park Factor 補正の適用
    def get_split_pf(row):
        t_code = str(row.get("team_name", "")).upper()
        pf_info = PARK_FACTORS_DETAILED.get(
            t_code,
            {
                "PF_Bat_R": 100,
                "PF_Bat_L": 100,
                "PF_HR_R": 100,
                "PF_HR_L": 100,
            },
        )
        return pf_info["PF_Bat_R"] if bat_side == "R" else pf_info["PF_Bat_L"]

    df["split_park_factor"] = df.apply(get_split_pf, axis=1)

    # wRAA / wSB / OAA が未定義の場合は従来推定値、定義済みの場合はFanGraphs真値を使用
    wraa_val = df.get("wraa")
    if wraa_val is None or wraa_val.isnull().all():
        wraa_val = (ops - 0.710) * (pa / 12.0)

    wsb_val = df.get("wsb", 0.0).fillna(0.0)
    oaa_val = df.get("oaa", 0.0).fillna(0.0)

    pos_adj_map = {
        "C": 12.5,
        "SS": 7.5,
        "2B": 2.5,
        "3B": 2.5,
        "CF": 2.5,
        "RF": -7.5,
        "LF": -7.5,
        "1B": -12.5,
        "DH": -17.5,
    }
    pos_val = (
        str(df.get("pos", "DH").iloc[0] if len(df) > 0 else "DH").split(",")[0].strip()
    )
    pos_adj = pd.to_numeric(
        df.get("gamesPlayed", df.get("games", 0)), errors="coerce"
    ) * (pos_adj_map.get(pos_val, -5.0) / 162.0)
    rep_runs = pa / 600.0 * 20.0

    # 拡張WARの算出
    advanced_war = (wraa_val + wsb_val + oaa_val + pos_adj + rep_runs) / 10.0
    df["advanced_war"] = np.round(advanced_war, 1)

    return df
