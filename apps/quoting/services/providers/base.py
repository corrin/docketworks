import abc
from typing import Any, Dict, Optional, Tuple


class PriceExtractionProvider(abc.ABC):
    """Abstract base class for AI price extraction providers."""

    provider_name: str
    model_name: str

    @abc.abstractmethod
    def extract_price_data(
        self, file_path: str, content_type: Optional[str] = None
    ) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
        """
        Extract price data from a supplier price list file.

        Args:
            file_path: Path to the price list file
            content_type: MIME type of the file

        Returns:
            Tuple containing extracted data dict and error message if any
        """
