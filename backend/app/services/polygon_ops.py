from __future__ import annotations

import numpy as np


def points_in_polygon(points: np.ndarray, vertices: np.ndarray) -> np.ndarray:
    x = points[:, 0]
    y = points[:, 1]
    xv = vertices[:, 0]
    yv = vertices[:, 1]
    inside = np.zeros(points.shape[0], dtype=bool)

    j = len(vertices) - 1
    for i in range(len(vertices)):
        yi = yv[i]
        yj = yv[j]
        xi = xv[i]
        xj = xv[j]
        intersects = ((yi > y) != (yj > y)) & (
            x < (xj - xi) * (y - yi) / ((yj - yi) + 1e-12) + xi
        )
        inside ^= intersects
        j = i

    return inside


def union_polygon_mask(points: np.ndarray, polygons: list[list[list[float]]]) -> np.ndarray:
    mask = np.zeros(points.shape[0], dtype=bool)
    for vertices in polygons:
        if len(vertices) < 3:
            continue
        polygon = np.asarray(vertices, dtype=float)
        mask |= points_in_polygon(points, polygon)
    return mask
