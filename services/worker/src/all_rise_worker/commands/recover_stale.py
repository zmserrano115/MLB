from all_rise_worker.runtime import get_executor


def main() -> int:
    print(f"recovered={get_executor().recover_stale()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
