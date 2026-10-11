"""Maya time-unit names for frame rates (shared by hython and plain-python tools)."""

MAYA_TIME_UNITS = {24.0: "film", 25.0: "pal", 30.0: "ntsc", 48.0: "show", 50.0: "palf", 60.0: "ntscf",
                   24000 / 1001: "23.976fps", 30000 / 1001: "29.97fps", 60000 / 1001: "59.94fps",
                   48000 / 1001: "47.952fps"}


def maya_time_unit(fps):
    for k, v in MAYA_TIME_UNITS.items():
        if abs(k - fps) < 1e-6:
            return v
    if abs(fps - round(fps)) < 1e-6:
        return f"{int(round(fps))}fps"
    raise ValueError(f"no Maya time unit for fps={fps}")
