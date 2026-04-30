import os

import chromadb.config


def disable_chroma_telemetry():
    os.environ.setdefault("ANONYMIZED_TELEMETRY", "False")
    chromadb.config.System = lambda *args, **kwargs: chromadb.config.Settings(anonymized_telemetry=False)

    try:
        import posthog

        posthog.capture = lambda *args, **kwargs: None
    except Exception:
        pass
