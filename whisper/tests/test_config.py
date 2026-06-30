import pytest

from app.config import Settings


def test_only_one_supported_variant_is_selected():
    with pytest.raises(ValueError, match="small.en or small"):
        Settings(api_key="a" * 32, model_variant="both").validate()


def test_multilingual_variant_is_valid():
    Settings(api_key="a" * 32, model_variant="small").validate()
