"""Download issue PDFs from the Wanfang page for 信息对抗技术."""

from __future__ import annotations

from wanfang_journal_downloader import WanfangJournalConfig, main_for_config


CONFIG = WanfangJournalConfig(
    journal_id="xxdkjs",
    journal_name="信息对抗技术",
    output_slug="xxdkjs",
)


def main(argv: list[str] | None = None) -> int:
    return main_for_config(CONFIG, argv)


if __name__ == "__main__":
    raise SystemExit(main())
