"""Download issue PDFs from the Wanfang page for 电子信息对抗技术."""

from __future__ import annotations

from wanfang_journal_downloader import WanfangJournalConfig, main_for_config


CONFIG = WanfangJournalConfig(
    journal_id="dzdkjs",
    journal_name="电子信息对抗技术",
    output_slug="dzdkjs",
)


def main(argv: list[str] | None = None) -> int:
    return main_for_config(CONFIG, argv)


if __name__ == "__main__":
    raise SystemExit(main())
