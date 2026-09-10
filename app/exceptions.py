class FlipFinderError(Exception):
    """Base application error."""


class ScraperError(FlipFinderError):
    """Base scraper error."""


class ScraperBlockedError(ScraperError):
    """Raised when scraper encounters explicit anti-bot blocking."""


class AIAnalysisError(FlipFinderError):
    """Raised when LLM analysis cannot be parsed or validated."""


class ConfigurationError(FlipFinderError):
    """Raised when required runtime configuration is unavailable."""
