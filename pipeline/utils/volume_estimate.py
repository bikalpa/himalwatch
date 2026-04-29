"""
HimalWatch — Glacial Lake Volume Estimation

Empirical area-volume scaling from Cook & Quincey (2015):
  V = 0.104 * A^1.42
  V in m³, A in m²

Reference:
  Cook, S.J. & Quincey, D.J. (2015). Estimating the volume of Alpine glacial lakes.
  Earth Surface Dynamics, 3, 559–575. https://doi.org/10.5194/esurf-3-559-2015

Uncertainty: ±1 order of magnitude for individual lakes. More reliable as an
ensemble statistic across many lakes than for any single lake.
"""


def estimate_volume_m3(area_sqm: float) -> float:
    """
    Cook & Quincey (2015) empirical area-volume relationship.
    Returns volume in cubic metres. Input area in square metres.
    """
    return 0.104 * (area_sqm ** 1.42)


def estimate_volume_mcm(area_sqm: float) -> float:
    """Volume in million cubic metres (MCM), commonly used in GLOF literature."""
    return estimate_volume_m3(area_sqm) / 1_000_000


def volume_change_mcm(area_first: float, area_latest: float) -> float:
    """Estimated volume change between two area observations, in MCM."""
    return estimate_volume_mcm(area_latest) - estimate_volume_mcm(area_first)
