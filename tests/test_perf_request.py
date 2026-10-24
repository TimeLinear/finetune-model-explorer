"""요청 단위 성능 기록 (웹 화면, F2013 후속 A-1). LLM 을 부르지 않는다.

- 동시에 진행되는 두 요청의 LLM 호출·단계 기록이 서로 섞이지 않는지
- 작업 스레드 풀(위키 P2 처럼 copy_context 로 넘긴 경우)에서도 요청 기록이 보이는지
- 프로세스 전역 기록(Streamlit 경로)이 요청 기록과 섞이지 않는지
- web.api.traced_stream 으로 돌린 두 스트림이 각자 한 줄씩 기록되는지
기록 파일은 임시 파일로 바꿔 실제 logs/perf.jsonl 에 쓰지 않는다.
"""
import contextvars
import json
import sys
import tempfile
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from common import perf  # noqa: E402

USAGE = {"input_tokens": 10, "output_tokens": 2}


class RequestTraceTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "perf.jsonl"
        self.patch = mock.patch.object(perf, "PERF_PATH", self.path)
        self.patch.start()

    def tearDown(self):
        self.patch.stop()
        self.tmp.cleanup()

    def lines(self):
        return [json.loads(l) for l in self.path.read_text(encoding="utf-8").splitlines() if l.strip()]

    def test_concurrent_requests_do_not_mix(self):
        barrier = threading.Barrier(2)

        def request(name):
            trace = perf.start_request_trace("web_test", name=name)
            for i in range(5):
                barrier.wait()  # 두 요청이 번갈아 기록하도록 맞춘다
                perf.record_llm(f"{name}_call", "fake-model", USAGE, 0.01)
                with perf.step(f"{name}_step"):
                    time.sleep(0.001)
            # 작업 스레드 풀 (data_prep/wiki.py 의 P2 와 같은 방식)
            with ThreadPoolExecutor(max_workers=2) as pool:
                for f in [pool.submit(contextvars.copy_context().run, perf.record_llm, f"{name}_pool", "fake-model",
                                      USAGE, 0.01) for _ in range(2)]:
                    f.result()
            perf.finish_request_trace(trace, done=True)

        threads = [threading.Thread(target=contextvars.copy_context().run, args=(request, n)) for n in ("A", "B")]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        lines = {l["meta"]["name"]: l for l in self.lines()}
        self.assertEqual(set(lines), {"A", "B"})
        for name, line in lines.items():
            self.assertEqual(line["mode"], "web_test")
            self.assertEqual(sorted({c["purpose"] for c in line["llm_calls"]}), [f"{name}_call", f"{name}_pool"])
            self.assertEqual(len(line["llm_calls"]), 7)
            self.assertEqual(set(line["steps"]), {f"{name}_step"})
            self.assertEqual(line["steps"][f"{name}_step"]["count"], 5)
            self.assertTrue(line["meta"]["done"])
            self.assertIn("total_sec", line)  # 기존 기록과 같은 형식
        self.assertIsNone(perf.current())  # 요청이 끝나면 남는 기록이 없다

    def test_global_trace_unaffected(self):
        """Streamlit 경로의 전역 기록은 요청 기록과 따로 쌓이고, 요청이 없을 때는 지금처럼 전역 기록을 쓴다."""
        perf.start_trace("app", model_id="m")
        perf.record_llm("global_call", "fake-model", USAGE, 0.01)

        def request():
            trace = perf.start_request_trace("web_test", name="R")
            perf.record_llm("request_call", "fake-model", USAGE, 0.01)
            perf.finish_request_trace(trace)

        t = threading.Thread(target=contextvars.copy_context().run, args=(request,))
        t.start()
        t.join()
        perf.record_llm("global_call2", "fake-model", USAGE, 0.01)
        perf.finish_trace(cited=0)
        by_mode = {l["mode"]: l for l in self.lines()}
        self.assertEqual([c["purpose"] for c in by_mode["app"]["llm_calls"]], ["global_call", "global_call2"])
        self.assertEqual([c["purpose"] for c in by_mode["web_test"]["llm_calls"]], ["request_call"])

    def test_web_traced_stream(self):
        from web import api

        def events(name):
            for i in range(3):
                perf.record_llm(f"{name}_{i}", "fake-model", USAGE, 0.01)
                time.sleep(0.002)
                yield f"{name}{i}"

        out = {}

        def consume(name):
            out[name] = list(api.traced_stream(events(name), "web_chat", model_id=name))

        threads = [threading.Thread(target=consume, args=(n,)) for n in ("X", "Y")]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(out, {"X": ["X0", "X1", "X2"], "Y": ["Y0", "Y1", "Y2"]})
        lines = {l["meta"]["model_id"]: l for l in self.lines()}
        for name in ("X", "Y"):
            self.assertEqual([c["purpose"] for c in lines[name]["llm_calls"]], [f"{name}_0", f"{name}_1", f"{name}_2"])


if __name__ == "__main__":
    unittest.main()
