"""Date-grouped partitions, with labels purged before the next partition."""

import pandas as pd


def split_samples(samples: pd.DataFrame) -> tuple[dict[str, pd.DataFrame], dict]:
    dates = sorted(samples.as_of.unique())
    if len(dates) < 45:
        raise ValueError("Fewer than45 eligible valuation dates; cannot form research partitions")
    calibration_start = dates[int(len(dates) * 0.55)]
    validation_start = dates[int(len(dates) * 0.78)]
    partitions = {
        "train": samples[
            (samples.as_of < calibration_start) & (samples.label_available_at < calibration_start)
        ].copy(),
        "calibration": samples[
            (samples.as_of >= calibration_start)
            & (samples.as_of < validation_start)
            & (samples.label_available_at < validation_start)
        ].copy(),
        "validation": samples[samples.as_of >= validation_start].copy(),
    }
    manifest = {
        "version": "limited-2026-purged-v1",
        "calibration_start": calibration_start,
        "validation_start": validation_start,
        "test_opened": False,
        "purged_count": len(samples) - sum(map(len, partitions.values())),
        "partitions": {
            name: {
                "samples": len(frame),
                "valuation_dates": frame.as_of.nunique(),
                "first": None if frame.empty else frame.as_of.min(),
                "last": None if frame.empty else frame.as_of.max(),
                "positive_dates": frame.loc[frame.triggered > 0, "as_of"].nunique(),
            }
            for name, frame in partitions.items()
        },
    }
    return partitions, manifest
