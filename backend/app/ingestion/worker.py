import argparse
import logging
import socket
import time

from app.config import settings
from app.database import SessionLocal
from app.ingestion.embeddings import create_embedding_provider
from app.ingestion.parsers import ParserRegistry
from app.ingestion.service import IngestionError, IngestionService
from app.infrastructure.object_storage import get_object_storage
from app.repositories.ingestion_repository import IngestionRepository


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("commonplan.ingestion")


def run_once(worker_id: str) -> bool:
    with SessionLocal() as db:
        repository = IngestionRepository(db)
        event = repository.claim_next(worker_id, settings.ingestion_lease_seconds)
        if event is None:
            return False
        event_id = event.id
        aggregate_id = event.aggregate_id
        event_type = event.event_type
        event_attempts = event.attempts
        service = IngestionService(
            repository,
            get_object_storage(),
            ParserRegistry(),
            create_embedding_provider(),
        )
        try:
            service.process(event)
            logger.info("processed event=%s type=%s", event_id, event_type)
        except Exception as exc:
            repository.rollback()
            if isinstance(exc, IngestionError):
                code = exc.code
                public_message = str(exc)
                max_attempts = settings.ingestion_max_attempts if exc.retryable else event_attempts
            else:
                code = exc.__class__.__name__
                public_message = "Document processing failed; retry or contact support"
                max_attempts = settings.ingestion_max_attempts
            repository.mark_ingestion_failed(aggregate_id, code, public_message)
            repository.retry_or_fail(event_id, str(exc), max_attempts)
            logger.exception("ingestion failed event=%s", event_id)
        return True


def main() -> None:
    parser = argparse.ArgumentParser(description="Process CommonPlan attachment ingestion events")
    parser.add_argument("--once", action="store_true", help="process at most one event")
    args = parser.parse_args()
    worker_id = f"{settings.ingestion_worker_id}@{socket.gethostname()}"
    while True:
        processed = run_once(worker_id)
        if args.once:
            return
        if not processed:
            time.sleep(settings.ingestion_poll_seconds)


if __name__ == "__main__":
    main()
