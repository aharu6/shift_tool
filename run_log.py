import sys
import datetime

from pathlib import Path

class TeeStream:
    def __init__(self, *streams):
        self.streams = streams

    def write(self, data):
        for stream in self.streams:
            stream.write(data)
        return len(data)

    def flush(self):
        for stream in self.streams:
            stream.flush()
            
class RunLog:
    @staticmethod
    def _setup_run_log() -> Path:
        log_dir = Path("logs")
        log_dir.mkdir(exist_ok=True)
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        log_path = log_dir / f"shift_run_{timestamp}.txt"

        log_file = open(log_path, "w", encoding="utf-8")
        sys.stdout = TeeStream(sys.stdout, log_file)
        sys.stderr = TeeStream(sys.stderr, log_file)

        print(f"実行ログを '{log_path}' に出力します。")
        return log_path

