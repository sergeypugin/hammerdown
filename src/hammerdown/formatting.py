from __future__ import annotations


def format_duration(seconds: float) -> str:
    if seconds < 60:
        return f"{seconds:.1f}s"
    total_minutes = int(seconds // 60)
    rem_seconds = seconds - total_minutes * 60
    if total_minutes < 60:
        return f"{total_minutes}m {rem_seconds:.1f}s"
    hours = total_minutes // 60
    minutes = total_minutes % 60
    return f"{hours}h {minutes}m {rem_seconds:.1f}s"


def format_progress_bar(current: int, total: int, unit: str = "pages", bar_length: int = 20) -> str:
    if total <= 0:
        return f"{current} {unit}"
    percent = min(100.0, max(0.0, (current / total) * 100))
    filled_len = int(round(bar_length * current / float(total)))
    bar = "█" * filled_len + "░" * (bar_length - filled_len)
    return f"[{bar}] {percent:.0f}% ({current}/{total} {unit})"
