"""Köppen-Geiger climate classes (Kottek et al. 2006) from seasonal climate fields.

The planet climate keeps an annual mean temperature, warmest- and coldest-month
temperatures and warm- and cold-half-year precipitation. Monthly values are
rebuilt from them with a cosine annual cycle, then classified with the
standard Köppen-Geiger rules:

* E (polar) when the warmest month is below 10 °C: ET above 0 °C, else EF;
* B (arid) when annual precipitation is below 10 * P_th, where P_th = 2 T_ann
  (+14, or +28 with at least 70 % summer rain, +0 with 70 % winter rain); BW
  below 5 * P_th, else BS; h with T_ann >= 18 °C, else k;
* A (tropical) when the coldest month is at least 18 °C: f, m (monsoon, short
  dry season), s or w by the driest month and its half-year;
* C (temperate) when the coldest month is above -3 °C, else D (continental);
  s (dry summer), w (dry winter) or f, then a (hot summer, >= 22 °C), b (at
  least four months >= 10 °C), c, or d (coldest month below -38 °C).
"""

import numpy as np
from numpy.typing import NDArray

type F64 = NDArray[np.float64]
type B = NDArray[np.bool_]
type I8 = NDArray[np.int8]

KOPPEN = (
    "ocean",
    "Af", "Am", "Aw", "As",
    "BWh", "BWk", "BSh", "BSk",
    "Csa", "Csb", "Csc", "Cwa", "Cwb", "Cwc", "Cfa", "Cfb", "Cfc",
    "Dsa", "Dsb", "Dsc", "Dsd", "Dwa", "Dwb", "Dwc", "Dwd", "Dfa", "Dfb", "Dfc", "Dfd",
    "ET", "EF",
)
# Standard Köppen-Geiger map colours (Peel et al. 2007, as in Kottek/Beck maps).
KOPPEN_COLOURS: tuple[tuple[int, int, int], ...] = (
    (40, 60, 90),
    (0, 0, 255), (0, 120, 255), (70, 170, 250), (110, 190, 245),
    (255, 0, 0), (255, 150, 150), (245, 165, 0), (255, 220, 100),
    (255, 255, 0), (200, 200, 0), (150, 150, 0),
    (150, 255, 150), (100, 200, 100), (50, 150, 50),
    (200, 255, 80), (100, 255, 80), (50, 200, 0),
    (255, 0, 255), (200, 0, 200), (150, 50, 150), (150, 100, 150),
    (170, 175, 255), (90, 120, 220), (75, 80, 180), (50, 0, 135),
    (0, 255, 255), (55, 200, 255), (0, 125, 125), (0, 70, 95),
    (178, 178, 178), (102, 102, 102),
)
_INDEX = {code: k for k, code in enumerate(KOPPEN)}
KOPPEN_NAMES = {
    "Af": "tropical rainforest", "Am": "tropical monsoon", "Aw": "tropical savanna",
    "As": "tropical dry-summer savanna", "BWh": "hot desert", "BWk": "cold desert",
    "BSh": "hot steppe", "BSk": "cold steppe", "Csa": "hot-summer Mediterranean",
    "Csb": "warm-summer Mediterranean", "Csc": "cool-summer Mediterranean",
    "Cwa": "monsoon-influenced humid subtropical", "Cwb": "subtropical highland",
    "Cwc": "cold subtropical highland", "Cfa": "humid subtropical", "Cfb": "oceanic",
    "Cfc": "subpolar oceanic", "Dsa": "hot-summer dry continental",
    "Dsb": "warm-summer dry continental", "Dsc": "dry subarctic", "Dsd": "dry extreme subarctic",
    "Dwa": "monsoon hot-summer continental", "Dwb": "monsoon warm-summer continental",
    "Dwc": "monsoon subarctic", "Dwd": "monsoon extreme subarctic",
    "Dfa": "hot-summer humid continental", "Dfb": "warm-summer humid continental",
    "Dfc": "subarctic", "Dfd": "extreme subarctic", "ET": "tundra", "EF": "ice cap",
}


def monthly(mean: F64, warmest: F64, coldest: F64, p_warm: F64, p_cold: F64) -> tuple[F64, F64]:
    """Twelve monthly temperatures (°C) and precipitations (mm), warmest month first.

    ``p_warm`` and ``p_cold`` are warm- and cold-half-year rates in mm/yr.
    """
    phase = np.cos(2 * np.pi * np.arange(12) / 12)[:, None]  # 1 = mid-summer
    half = (warmest - coldest) / 2
    centre = (warmest + coldest) / 2
    temperature = centre + half * phase + 0 * mean
    precipitation = ((p_warm + p_cold) / 2 + (p_warm - p_cold) / 2 * phase) / 12
    return temperature, np.maximum(precipitation, 0.0)


def classify_koppen(
    mean: F64, warmest: F64, coldest: F64, p_warm: F64, p_cold: F64, land: B
) -> I8:
    temperature, precipitation = monthly(mean, warmest, coldest, p_warm, p_cold)
    annual = precipitation.sum(axis=0)
    t_ann = temperature.mean(axis=0)
    t_max, t_min = temperature.max(axis=0), temperature.min(axis=0)
    summer = precipitation[[0, 1, 2, 10, 11, 9]]  # the six months around mid-summer
    winter = precipitation[3:9]
    p_smin, p_smax = summer.min(axis=0), summer.max(axis=0)
    p_wmin, p_wmax = winter.min(axis=0), winter.max(axis=0)
    p_min = precipitation.min(axis=0)
    summer_share = summer.sum(axis=0) / np.maximum(annual, 1e-9)
    threshold = 2 * t_ann + np.select(
        [summer_share >= 0.7, summer_share <= 0.3], [28.0, 0.0], 14.0
    )
    warm_months = (temperature >= 10).sum(axis=0)

    dry_summer = (p_smin < p_wmin) & (p_wmax > 3 * p_smin) & (p_smin < 40)
    dry_winter = (p_wmin < p_smin) & (p_smax > 10 * p_wmin)
    second = np.where(dry_summer, "s", np.where(dry_winter, "w", "f"))
    third = np.where(
        t_max >= 22, "a", np.where(warm_months >= 4, "b", np.where(t_min < -38, "d", "c"))
    )
    temperate = np.char.add(np.char.add("C", second.astype(str)), third.astype(str))
    continental = np.char.add(np.char.add("D", second.astype(str)), third.astype(str))
    temperate = np.where(
        third == "d", np.char.add(np.char.add("C", second.astype(str)), "c"), temperate
    )
    code = np.where(t_min > -3, temperate, continental)
    tropical = np.where(
        p_min >= 60,
        "Af",
        np.where(
            annual >= 25 * (100 - p_min), "Am", np.where(p_smin < p_wmin, "As", "Aw")
        ),
    )
    code = np.where(t_min >= 18, tropical, code)
    arid = np.char.add(
        np.where(annual < 5 * threshold, "BW", "BS").astype(str),
        np.where(t_ann >= 18, "h", "k").astype(str),
    )
    code = np.where(annual < 10 * threshold, arid, code)
    code = np.where(t_max < 10, np.where(t_max > 0, "ET", "EF"), code)
    names, inverse = np.unique(np.asarray(code).astype(str), return_inverse=True)
    lookup = np.array([_INDEX[str(name)] for name in names], dtype=np.int8)
    return np.where(land, lookup[inverse.reshape(mean.shape)], 0).astype(np.int8)


def koppen_group_share(koppen: I8, weight: F64) -> dict[str, float]:
    """Area share of the main groups A-E over the weighted nodes."""
    total = float(weight.sum())
    groups: dict[str, float] = {}
    for letter in "ABCDE":
        mask = np.array([code.startswith(letter) for code in KOPPEN])[koppen]
        groups[letter] = round(float(weight[mask].sum()) / max(total, 1e-12), 4)
    return groups
