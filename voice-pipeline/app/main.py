from voice_pipeline.config import load_config
from voice_pipeline.orchestrator import VoiceOrchestrator
from voice_pipeline.utils.logging_utils import configure_logging


def main() -> None:
    config = load_config()
    logger = configure_logging(config.log_level, config.debug_logging)
    orchestrator = VoiceOrchestrator(config, logger)
    orchestrator.run_forever()


if __name__ == "__main__":
    main()
