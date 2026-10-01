# -*- coding: utf-8 -*-
"""구글 소재 행이 `인앱 액션`을 들고 온다 (규리님 2026-10-01).

*"용사의 발라드 구글에서 인앱 액션을 넣어야 해."*

구글에는 D0 coin·D0 read가 없다 — 설치 **이후**를 보는 지표가 인앱 액션뿐이다.

⚠ **표본이 얇다는 것을 알고 선택하신 것이다.** 9월 용사의 발라드 기준 캠페인 전체
96건 중 소재명이 붙은 애셋에 떨어지는 것은 13건뿐이다(소진·설치와 똑같이 애셋
유형별로 배분된다). 되돌리려면 먼저 물을 것.
"""
import pandas as pd
import pytest

import creative_data as cd
import google_ads_report as g


def asset_rows():
    """구글 애셋 리포트 모양의 최소 프레임."""
    return pd.DataFrame([
        {"asset": "u1", "asset_type": "YouTube 동영상", "os": "iOS",
         "creative_name": "11224_勇者之歌_VID_Madup_Trend_9X16_1",
         "impression": 1000, "click": 10, "cost": 50000.0,
         "total install": 20, "in_app_action": 5, "month": 9},
        {"asset": "u2", "asset_type": "이미지", "os": "iOS",
         "creative_name": "11224_勇者之歌_IMG_Madup_SingleImage_4X5_TITLE2",
         "impression": 500, "click": 4, "cost": 10000.0,
         "total install": 3, "in_app_action": 1, "month": 9},
    ])


class TestCarried:
    def test_소재_행에_인앱_액션이_실린다(self):
        out = g.as_creative_rows(asset_rows(), month=9)
        assert "in_app_action" in out.columns
        assert float(out["in_app_action"].sum()) == 6.0

    def test_값으로_고를_수_있다(self):
        assert "in_app_action" in cd.METRIC_COLUMNS
        assert "in_app_action" in cd.SELECTABLE_COLUMNS


class TestNotZeroFilled:
    """**이 테스트가 핵심 계약이다.**

    0으로 채우면 메타·틱톡 줄이 `인앱 액션 0`으로 찍혀 *"액션이 하나도 없었다"* 로
    읽힌다. 실제로는 **측정 자체가 없다**(구글 전용 지표). 구글 행의 `D0 read`를
    비워 두는 것과 정확히 같은 이유다.
    """

    def test_메타_틱톡_묶음은_결측으로_남는다(self):
        google = cd.add_derived_metrics(
            cd.attach_creative_attributes(g.as_creative_rows(asset_rows(), month=9)))
        meta = pd.DataFrame([{
            "ad": "11224_勇者之歌_VID_Madup_Trend_9X16_2", "media": "Meta",
            "os": "iOS", "impression": 2000, "click": 20, "cost": 90000.0,
            "total install": 30, "D0 read": 10, "month": 9,
        }])
        merged = pd.concat([meta, google], ignore_index=True)
        table = cd.aggregate_by(merged, ["media"])

        got = table.set_index("media")["in_app_action"]
        assert pd.isna(got["Meta"]), "메타가 0으로 찍히면 '액션 없음'으로 읽힌다"
        assert float(got["Google"]) == 6.0

    def test_시트_파서는_건드리지_않았다(self):
        """`SUM_METRICS`에 넣으면 parquet 스키마가 바뀌어 `PARSER_VERSION`을
        올려야 하고 캐시를 전부 다시 받아야 한다."""
        assert "in_app_action" not in cd.SUM_METRICS.values()
        assert "in_app_action" in cd.EXTRA_SUM_METRICS
