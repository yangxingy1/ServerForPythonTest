import time

# 时间源
class TimeSrc:
    # 可注入的时间源。now() = 真实时间 + offset

    def __init__(self):
        self._offset = 0.0

    def now(self) -> float:
        return time.time() + self._offset

    def set_time(self, target_ts: float):
        # 跳到指定绝对时间
        self._offset = target_ts - time.time()

    def advance(self, seconds: float):
        # 往前跳 seconds 秒
        self._offset += seconds
