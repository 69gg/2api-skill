"""注册机 CLI 入口。

用法：
    uv run python -m registrar -n 5 -w 2 --proxy http://host:port
    uv run python -m registrar --count 0 --workers 3   # 无限运行直到 Ctrl+C

并发模型：ThreadPoolExecutor 维持 -w 个任务在飞；单账号失败不致命，仅记日志。
"""
from __future__ import annotations

import argparse
import sys
import traceback
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait

from registrar.http_client import HttpClient
from registrar.models import RegistrarConfig, load_registrar_config
from registrar.pipeline import register_one


def _build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="registrar", description="{{Platform}}2api 注册机（临邮 + captcha）")
    ap.add_argument("-n", "--count", type=int, default=1,
                    help="本次注册数量上限（0=无限循环直到 Ctrl+C）")
    ap.add_argument("-w", "--workers", type=int, default=1, help="并发线程数")
    ap.add_argument("--proxy", default=None, help="HTTP/HTTPS/SOCKS 代理 URL（注册请求与 captcha 共用）")
    ap.add_argument("--config", default=None, help="config.toml 路径（默认 $TWOAPI_CONFIG 或 config.toml）")
    ap.add_argument("--captcha-method", default=None,
                    help="覆盖 config [captcha].method（semi/cdp/api）")
    return ap


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    cfg = load_registrar_config(args.config)
    http = HttpClient(proxy=args.proxy)

    infinite = args.count <= 0
    target = args.count
    workers = max(args.workers, 1)
    success = failed = submitted = 0

    try:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            def fill(futures: set) -> None:
                nonlocal submitted
                while len(futures) < workers and (infinite or submitted < target):
                    futures.add(pool.submit(_safe_register, cfg, http, args))
                    submitted += 1

            futures: set = set()
            fill(futures)
            while futures:
                done, futures = wait(futures, return_when=FIRST_COMPLETED)
                for fut in done:
                    ok, msg = fut.result()
                    if ok:
                        success += 1
                        print(f"[OK]   {msg}", flush=True)
                    else:
                        failed += 1
                        print(f"[FAIL] {msg}", flush=True, file=sys.stderr)
                fill(futures)
    except KeyboardInterrupt:
        print("\n[!] 收到中断，等待在飞任务结束后退出...", file=sys.stderr)

    print(f"\n==== 完成：成功 {success}，失败 {failed} ====", flush=True)
    return 0


def _safe_register(
    cfg: RegistrarConfig, http: HttpClient, args: argparse.Namespace
) -> tuple[bool, str]:
    """单账号注册的异常包装：失败返回 (False, 错误摘要)。"""
    try:
        acc = register_one(cfg, http, proxy=args.proxy, captcha_method=args.captcha_method)
        return True, f"{acc.source_email} -> account/{acc.name}.json"
    except Exception as exc:  # noqa: BLE001 - 单账号失败不致命
        tail = traceback.format_exc().splitlines()[-1]
        return False, f"{exc} | {tail}"


if __name__ == "__main__":
    raise SystemExit(main())
